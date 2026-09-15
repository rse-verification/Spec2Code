#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPAM_SWITCH="${SPEC2CODE_OPAM_SWITCH:-ocaml5}"
OPAM_MANIFEST="$ROOT_DIR/spec2code.opam"
NFRCHECK_DIR="$ROOT_DIR/tools/nfrcheck"
VERNFR_DIR="$ROOT_DIR/tools/vernfr"

if ! command -v opam >/dev/null 2>&1; then
  echo "Error: opam is required but was not found in PATH." >&2
  exit 1
fi

if [ ! -f "$OPAM_MANIFEST" ]; then
  echo "Error: OPAM manifest not found: $OPAM_MANIFEST" >&2
  exit 1
fi

if [ ! -d "$NFRCHECK_DIR" ] && [ ! -d "$VERNFR_DIR" ]; then
  echo "Error: neither tools/nfrcheck nor tools/vernfr scripts were found." >&2
  exit 1
fi

echo "[vernfr] Activating opam environment"
eval "$(opam env --switch="$OPAM_SWITCH")"

echo "[vernfr] Installing pinned Spec2Code critic dependencies"
opam install -y --deps-only "$OPAM_MANIFEST"

if ! frama-c -plugins | grep -qi vernfr; then
  echo "Error: frama-c-vernfr was not registered by Frama-C." >&2
  exit 1
fi

echo "[vernfr] Done. Pinned VerNFR plugin is installed."
