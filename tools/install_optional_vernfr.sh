#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NFRCHECK_DIR="$ROOT_DIR/tools/nfrcheck"
VERNFR_DIR="$ROOT_DIR/tools/vernfr"
TOOL_DIR=""

if ! command -v opam >/dev/null 2>&1; then
  echo "Error: opam is required but was not found in PATH." >&2
  exit 1
fi

if ! command -v dune >/dev/null 2>&1; then
  echo "Error: dune is required but was not found in PATH." >&2
  exit 1
fi

if [ -d "$NFRCHECK_DIR" ]; then
  TOOL_DIR="$NFRCHECK_DIR"
elif [ -d "$VERNFR_DIR" ]; then
  TOOL_DIR="$VERNFR_DIR"
else
  echo "Error: neither tools/vernfr nor tools/nfrcheck was found." >&2
  exit 1
fi

echo "[vernfr] Activating opam environment"
eval "$(opam env --switch=ocaml5)"

echo "[vernfr] Building and installing $TOOL_DIR"
cd "$TOOL_DIR"
dune build @install
dune install

echo "[vernfr] Done. Vernfr optional critic tooling is installed."
