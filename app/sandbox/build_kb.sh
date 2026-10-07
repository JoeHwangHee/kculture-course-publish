#!/bin/sh
# Build the knowledge index app/index/kb/ on the host ("training" here means indexing; no model weights change).
#   sh app/sandbox/build_kb.sh <model folder>
# 1. Gathers, whichever exist, into one temporary folder:
#      data/sweat/theme_packs/ -> theme_packs/    data/sweat/sources/ -> sources/    app/data/bulk/ -> bulk/
#    Each keeps its own folder so each _collection.json keeps its scope. data/sweat/kdh_pack/ (research notes)
#    is never gathered.
# 2. Runs the retrieval CLI from app/ (the index format belongs to app/retrieval; this script only calls it):
#      uv run python -m retrieval index --input <gathered folder> --index index/kb --embedder=local:<model folder>
# 3. The retrieval CLI itself copies theme_packs/*.json into app/index/kb/theme_packs/ (byte for byte; packs are
#    not indexed, and a pack it skips stays out). No extra copy here, so a skipped pack is never brought back.
# The previous app/index/kb is moved aside first and restored if the build fails or is interrupted.
# Needs the local-embed extra in app/ (uv sync --extra local-embed).
set -eu
[ $# -eq 1 ] || { echo "usage: build_kb.sh <model folder>" >&2; exit 2; }
[ -f "$1/config.json" ] || { echo "not a model folder: $1" >&2; exit 2; }
model=$(cd "$1" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
app=$(cd "$here/.." && pwd)
root=$(cd "$app/.." && pwd)
kb="$app/index/kb"

found=
for rel in data/sweat/theme_packs data/sweat/sources app/data/bulk; do
  if [ -d "$root/$rel" ]; then found="$found $rel"; else echo "skip (absent): $rel" >&2; fi
done
[ -n "$found" ] || { echo "no source folder found (data/sweat/theme_packs, data/sweat/sources, app/data/bulk)" >&2; exit 2; }
command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH" >&2; exit 2; }

tmp=$(mktemp -d "${TMPDIR:-/tmp}/kculture-kb.XXXXXX")
built=0
cleanup() {
  if [ "$built" -ne 1 ] && [ -e "$tmp/index-kb.prev" ]; then
    rm -rf "$kb"
    mv "$tmp/index-kb.prev" "$kb"
    echo "restored the previous app/index/kb" >&2
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

src="$tmp/kb"
mkdir "$src"
for rel in $found; do
  case $rel in
    data/sweat/theme_packs) cp -R "$root/$rel" "$src/theme_packs";;
    data/sweat/sources) cp -R "$root/$rel" "$src/sources";;
    app/data/bulk) cp -R "$root/$rel" "$src/bulk";;
  esac
done
find "$src" -name .DS_Store -type f -exec rm -f {} +

(cd "$app" && uv run python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('sentence_transformers') else 1)") \
  || { echo "sentence-transformers missing in app/: run 'uv sync --extra local-embed' there first" >&2; exit 2; }

if [ -e "$kb" ]; then mv "$kb" "$tmp/index-kb.prev"; fi
(cd "$app" && uv run python -m retrieval index --input "$src" --index index/kb --embedder="local:$model")
built=1
echo "built: app/index/kb (from:$found)"
