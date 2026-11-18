#!/usr/bin/env bash
# Regenerate html/ from src/ with javadoc 25: JAVADOC=/path/to/jdk-25/bin/javadoc ./regenerate.sh
# Only the package's own pages are kept; javadoc's scripts, styles, fonts and indexes are not committed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
javadoc="${JAVADOC:-javadoc}"
"$javadoc" --version | grep -q '^javadoc 25' || { echo "regenerate.sh: needs javadoc 25" >&2; exit 1; }
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
"$javadoc" -quiet -private -notimestamp -Xdoclint:none -d "$out" -sourcepath "$here/src" fixture.api
rm -rf "$here/html"
mkdir -p "$here/html/fixture/api"
cp "$out"/fixture/api/*.html "$here/html/fixture/api/"
