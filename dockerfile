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
# --- OPAM init + OCaml 5.4 switch ---
RUN opam init -y --disable-sandboxing \
 && opam repository add default https://opam.ocaml.org \
 && opam update \
 && opam switch create ocaml5 ocaml-base-compiler.5.4.0

# --- Install the pinned OPAM critic stack ---
COPY spec2code.opam /tmp/spec2code.opam
RUN bash -lc 'eval "$(opam env --switch=ocaml5)" \
 && opam install -y opam-depext \
 && opam depext -y /tmp/spec2code.opam \
 && opam install -y --deps-only /tmp/spec2code.opam'

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

# --- Optional Valgrind critic ---
ARG INSTALL_VALGRIND=0
RUN if [ "$INSTALL_VALGRIND" = "1" ]; then \
      apt-get update; \
      apt-get install -y --no-install-recommends valgrind; \
      rm -rf /var/lib/apt/lists/*; \
      valgrind --version; \
    else \
      echo "Skipping Valgrind install (INSTALL_VALGRIND=0)"; \
    fi

# --- Optional ESBMC critic ---
ARG TARGETARCH
ARG INSTALL_ESBMC=0
ARG ESBMC_VERSION=7.6
RUN if [ "$INSTALL_ESBMC" = "1" ]; then \
      set -eux; \
      case "$TARGETARCH" in \
        amd64) \
          esbmc_asset="release-ubuntu-latest.zip"; \
          esbmc_sha256="0bd2494415b13725018ca6e506d28366d877acb640c195907f52b0b1dc2c6c4b" \
          ;; \
        arm64) \
          esbmc_asset="release-ARM64.zip"; \
          esbmc_sha256="7567cce6f8a42c26e04f13a4a19fe91ee3e08e1e81bbe7f0de491ffcef648cd5" \
          ;; \
        *) echo "Unsupported architecture for ESBMC: $TARGETARCH"; exit 1 ;; \
      esac; \
      wget -O /tmp/esbmc.zip "https://github.com/esbmc/esbmc/releases/download/v${ESBMC_VERSION}/${esbmc_asset}"; \
      echo "${esbmc_sha256}  /tmp/esbmc.zip" | sha256sum -c -; \
      mkdir -p /opt/esbmc; \
      unzip -q /tmp/esbmc.zip -d /opt/esbmc; \
      chmod 0755 /opt/esbmc/bin/esbmc; \
      ln -s /opt/esbmc/bin/esbmc /usr/local/bin/esbmc; \
      rm /tmp/esbmc.zip; \
      esbmc --version; \
    else \
      echo "Skipping ESBMC install (INSTALL_ESBMC=0)"; \
    fi

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

# --- Environment: prefer ocaml5 switch + venv ---
ENV PATH="$VENV_DIR/bin:/opt/opam/ocaml5/bin:/usr/local/bin:/usr/bin:/bin" \
    OPAM_SWITCH="ocaml5"

RUN echo 'eval "$(opam env --switch=ocaml5)"' >> /etc/bash.bashrc

CMD ["bash"]
