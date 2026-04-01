# syntax=docker/dockerfile:1
FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    OPAMYES=1 \
    OPAMROOT=/opt/opam \
    VENV_DIR=/opt/venv \
    OPAMJOBS=4

# --- System deps (no Debian dune; we’ll use opam dune) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget unzip git \
    build-essential pkg-config m4 bubblewrap \
    zlib1g-dev libgmp-dev libexpat1-dev \
    python3 python3-venv python3-pip \
    clang cppcheck graphviz \
    opam ocaml-findlib \
    autoconf \
    libgtksourceview-3.0-dev \
    file \
  && rm -rf /var/lib/apt/lists/*

ARG INSTALL_AWSCLI=0

# --- Optional AWS CLI v2 (disabled by default for public/open-source builds) ---
RUN if [ "$INSTALL_AWSCLI" = "1" ]; then \
      set -eux; \
      apt-get update; \
      apt-get install -y --no-install-recommends curl unzip ca-certificates less; \
      arch="$(uname -m)"; \
      case "$arch" in \
        x86_64)  url="https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" ;; \
        aarch64) url="https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" ;; \
        arm64)   url="https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" ;; \
        *) echo "Unsupported arch: $arch"; exit 1 ;; \
      esac; \
      curl -fsSL "$url" -o /tmp/awscliv2.zip; \
      unzip -q /tmp/awscliv2.zip -d /tmp; \
      /tmp/aws/install --update; \
      rm -rf /tmp/aws /tmp/awscliv2.zip; \
      rm -rf /var/lib/apt/lists/*; \
      aws --version; \
    else \
      echo "Skipping AWS CLI install (INSTALL_AWSCLI=0)"; \
    fi

# Make boto3/CLI use SSO profiles in ~/.aws/config and avoid pager errors
ENV AWS_SDK_LOAD_CONFIG=1 \
    AWS_PAGER=""
# --- OPAM init + OCaml 5.1.1 switch ---
RUN opam init -y --disable-sandboxing \
 && opam repository add default https://opam.ocaml.org \
 && opam update \
 && opam switch create ocaml5 ocaml-base-compiler.5.1.1

# --- Install dune + Frama-C 31.0 + Why3 + Alt-Ergo in that switch ---
RUN bash -lc 'eval "$(opam env --switch=ocaml5)" \
 && opam install -y dune \
 && opam install -y opam-depext \
 && opam depext -y frama-c.31.0 why3 alt-ergo \
 && opam install -y frama-c.31.0 why3 alt-ergo'

# --- Solvers ---
RUN set -eux; \
  arch="$(dpkg --print-architecture)"; \
  if [ "$arch" = "amd64" ]; then \
    CVC5_URL="https://github.com/cvc5/cvc5/releases/download/cvc5-1.2.0/cvc5-Linux-x86_64-static.zip"; \
    wget -O /tmp/cvc5.zip "$CVC5_URL"; \
    unzip /tmp/cvc5.zip -d /tmp; \
    install -m 0755 /tmp/cvc5-Linux-x86_64-static/bin/cvc5 /usr/local/bin/cvc5; \
    rm -rf /tmp/cvc5*; \
    Z3_URL="https://github.com/Z3Prover/z3/releases/download/z3-4.8.6/z3-4.8.6-x64-ubuntu-16.04.zip"; \
    wget -O /tmp/z3.zip "$Z3_URL"; \
    unzip /tmp/z3.zip -d /tmp; \
    install -m 0755 /tmp/z3-4.8.6-x64-ubuntu-16.04/bin/z3 /usr/local/bin/z3; \
    rm -rf /tmp/z3*; \
  else \
    apt-get update; \
    apt-get install -y --no-install-recommends z3 cvc5; \
    rm -rf /var/lib/apt/lists/*; \
  fi; \
  z3 --version; \
  cvc5 --version

# --- Python venv (inside image) ---
RUN python3 -m venv "$VENV_DIR" \
 && "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel

WORKDIR /workspace

# Cache python deps if present
COPY requirements.txt /workspace/requirements.txt
RUN if [ -f requirements.txt ]; then "$VENV_DIR/bin/pip" install -r requirements.txt; fi

# Copy project for reproducible image builds
COPY . /workspace

# --- cppcheck MISRA rules ---
RUN mkdir -p /root/.config/cppcheck \
 && if [ -f /workspace/src/spec2code/pipeline_modules/critics/misra_rules_2012.txt ]; then \
      cp /workspace/src/spec2code/pipeline_modules/critics/misra_rules_2012.txt /root/.config/cppcheck/misra_rules_2012.txt; \
    else \
      echo "WARN: MISRA rules file not found at src/spec2code/pipeline_modules/critics/misra_rules_2012.txt"; \
    fi

# --- Build/install Vernfr (tools/nfrcheck) ---
# Default on; disable only when needed with --build-arg BUILD_NFRCHECK=0
ARG BUILD_NFRCHECK=1
RUN if [ "$BUILD_NFRCHECK" = "1" ] && [ -d /workspace/tools/nfrcheck ]; then \
      bash -lc 'eval "$(opam env --switch=ocaml5)" && cd /workspace/tools/nfrcheck && dune build -j $(nproc) @install && dune install' ; \
    else \
      echo "Skipping tools/nfrcheck build (BUILD_NFRCHECK=$BUILD_NFRCHECK)"; \
    fi

# --- Environment: prefer ocaml5 switch + venv ---
ENV PATH="$VENV_DIR/bin:/opt/opam/ocaml5/bin:/usr/local/bin:/usr/bin:/bin" \
    OPAM_SWITCH="ocaml5"

RUN echo 'eval "$(opam env --switch=ocaml5)"' >> /etc/bash.bashrc

CMD ["bash"]
