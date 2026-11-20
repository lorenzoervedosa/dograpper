#!/usr/bin/env bash
# Regenerate html/ from src/ with the measured nightly rustdoc: RUSTDOC=/path/to/rustdoc ./regenerate.sh
# Same recipe as ../regenerate.sh (the 1.96 fixture, which stays as is); only the version check differs.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
rustdoc="${RUSTDOC:-rustdoc}"
"$rustdoc" --version | grep -q '^rustdoc 1\.102\.0-nightly (6905905bb ' || { echo "regenerate.sh: needs rustdoc 1.102.0-nightly (6905905bb ...)" >&2; exit 1; }
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
"$rustdoc" --edition 2021 --crate-name nightly_fixture --crate-type lib --crate-version 0.1.0 -D warnings \
    -o "$out" "$here/src/lib.rs"
rm -rf "$here/html"
mkdir -p "$here/html"
cp -R "$out/nightly_fixture" "$here/html/"
find "$here/html" -type f \( ! -name '*.html' -o -name '*!.html' \) -delete
