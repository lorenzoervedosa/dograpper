#!/usr/bin/env bash
# Regenerate html/ from src/ and docs/ with Sphinx 9.2: SPHINX_BUILD=/path/to/sphinx-build ./regenerate.sh
# Only the documentation pages are kept; Sphinx's static files, sources, indexes and search page are not committed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
sphinx_build="${SPHINX_BUILD:-sphinx-build}"
"$sphinx_build" --version | grep -q '^sphinx-build 9\.2\.' || { echo "regenerate.sh: needs Sphinx 9.2" >&2; exit 1; }
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
# -W: a warning (e.g. a duplicate object description) fails the build instead of changing the pages.
PYTHONDONTWRITEBYTECODE=1 "$sphinx_build" -q -W -E -b html "$here/docs" "$out"
rm -rf "$here/html"
mkdir -p "$here/html"
cp "$out"/index.html "$out"/shapes.html "$out"/tools.html "$here/html/"
