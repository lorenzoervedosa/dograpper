#!/usr/bin/env bash
# Regenerate html/ from src/ with rustdoc 1.96: RUSTDOC=/path/to/rustdoc ./regenerate.sh
# Keeps only the two pages of the re-exported fn: the real one (fixture/fn.kmerge_by.html) and the redirect stub rustdoc writes at the old path (fixture/imp/fn.kmerge_by.html).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
rustdoc="${RUSTDOC:-rustdoc}"
"$rustdoc" --version | grep -q '^rustdoc 1\.96\.' || { echo "regenerate.sh: needs rustdoc 1.96" >&2; exit 1; }
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
"$rustdoc" --edition 2021 --crate-name fixture --crate-type lib --crate-version 0.1.0 -D warnings \
    -o "$out" "$here/src/lib.rs"
rm -rf "$here/html"
mkdir -p "$here/html"
cp -R "$out/fixture" "$here/html/"
find "$here/html" -type f ! -name "fn.kmerge_by.html" -delete
