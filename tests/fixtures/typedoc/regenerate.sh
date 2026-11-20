#!/usr/bin/env bash
# Regenerate html/ from src/ with TypeDoc 0.28.20: TYPEDOC=/path/to/typedoc ./regenerate.sh
# TypeDoc is never a dependency of this repository: install it in a scratch directory
# (npm install typedoc@0.28.20 typescript) and point TYPEDOC at its node_modules/.bin/typedoc.
# The exact version is pinned: tests/test_api_reference_typedoc.py asserts record texts, and
# TypeDoc's own output (union order, constructor docs) differs between 0.28 releases.
# Only the documentation pages are kept; TypeDoc's assets/ (scripts, styles, search index) are not committed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
typedoc="${TYPEDOC:-typedoc}"
"$typedoc" --version | grep -q '^TypeDoc 0\.28\.20$' || { echo "regenerate.sh: needs TypeDoc 0.28.20" >&2; exit 1; }
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
# treatWarningsAsErrors (typedoc.json): a warning (e.g. a broken {@link}) fails the build instead of changing the pages.
# Source links are on, as in TypeDoc's default, with a fixed sourceLinkTemplate; excludeExternals keeps the
# "Defined in" paths of TypeScript's own lib files (members inherited from Error), which point into the
# local TypeDoc install, out of the pages.
(cd "$here" && "$typedoc" --options typedoc.json --out "$out" --logLevel Warn)
rm -rf "$here/html"
mkdir -p "$here/html"
(cd "$out" && find . -name '*.html' -not -path './assets/*') | while read -r page; do
    mkdir -p "$here/html/$(dirname "$page")"
    cp "$out/$page" "$here/html/$page"
done
