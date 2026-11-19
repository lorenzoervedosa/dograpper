#!/usr/bin/env bash
# Regenerate html/ from src/ with rustdoc 1.96: RUSTDOC=/path/to/rustdoc ./regenerate.sh
# Only the crate's pages are kept; rustdoc's static files, source pages, search index and redirect stubs are not committed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
rustdoc="${RUSTDOC:-rustdoc}"
"$rustdoc" --version | grep -q '^rustdoc 1\.96\.' || { echo "regenerate.sh: needs rustdoc 1.96" >&2; exit 1; }
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
# -D warnings: a warning (e.g. a broken intra-doc link) fails the build instead of changing the pages.
"$rustdoc" --edition 2021 --crate-name fixture --crate-type lib --crate-version 0.1.0 -D warnings \
    -o "$out" "$here/src/lib.rs"
rm -rf "$here/html"
mkdir -p "$here/html"
cp -R "$out/fixture" "$here/html/"
find "$here/html" -type f \( ! -name '*.html' -o -name '*!.html' \) -delete
