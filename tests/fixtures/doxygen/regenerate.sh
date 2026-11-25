#!/usr/bin/env bash
# Regenerate html/ and source-browser/ from src/ with Doxygen 1.9.8: DOXYGEN=/path/to/doxygen ./regenerate.sh
# One project per language, each run on the defaults except the lines below; only the
# *.html pages are kept (no stylesheets, scripts, images or search index). The C project
# is also built with the source browser on, into source-browser/c: the same pages with
# "Definition at line ..." and "References ..." / "Referenced by ..." added.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
doxygen="${DOXYGEN:-doxygen}"
[ "$("$doxygen" --version)" = "1.9.8" ] || { echo "regenerate.sh: needs Doxygen 1.9.8" >&2; exit 1; }
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
for build in cpp c c-browser; do
    lang="${build%-browser}"
    extra=""
    [ "$lang" = c ] && extra="OPTIMIZE_OUTPUT_FOR_C = YES"  # what C projects set: "Data Structures", "Data Fields"
    [ "$build" = c-browser ] && extra="$extra
SOURCE_BROWSER         = YES
REFERENCES_RELATION    = YES
REFERENCED_BY_RELATION = YES"
    # WARN_AS_ERROR: a warning (an undocumented member, a broken reference) fails the run
    # instead of changing the pages. HAVE_DOT = NO: no Graphviz graphs, only the built-in diagrams.
    (cd "$here/src/$lang" && "$doxygen" - <<EOF
PROJECT_NAME     = fixture-$lang
INPUT            = .
OUTPUT_DIRECTORY = $out/$build
GENERATE_LATEX   = NO
HAVE_DOT         = NO
QUIET            = YES
WARN_AS_ERROR    = YES
$extra
EOF
    )
done
rm -rf "$here/html" "$here/source-browser"
for lang in cpp c; do
    mkdir -p "$here/html/$lang"
    cp "$out/$lang/html/"*.html "$here/html/$lang/"
done
mkdir -p "$here/source-browser/c"
cp "$out/c-browser/html/"*.html "$here/source-browser/c/"
