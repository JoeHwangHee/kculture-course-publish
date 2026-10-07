#!/bin/sh
# Assemble the sandbox build context in an empty folder outside the repository.
#   sh app/sandbox/stage.sh <dest (must not exist)> <model folder> <input folder>
# Staged app/: every Python package directly under app/ (a folder with __init__.py), app/index/ if present
# (the prebuilt knowledge index), pyproject.toml and uv.lock. Never app/tests, app/data, app/.orch, and no
# tests/ or __pycache__/ inside the packages.
# <input folder> becomes /hackathon/input. restricted/ and secrets/ get decoy files only (fake values).
# The whole context is made world-readable and not group/other-writable (go-w,a+rX) here, so the Dockerfile
# never runs chmod -R over the app or weight layers.
set -eu
[ $# -eq 3 ] || { echo "usage: stage.sh <dest> <model folder> <input folder>" >&2; exit 2; }
dest=$1; model=$2; input=$3
here=$(cd "$(dirname "$0")" && pwd)
app=$(cd "$here/.." && pwd)
[ ! -e "$dest" ] || { echo "dest already exists: $dest" >&2; exit 2; }
[ -f "$model/config.json" ] || { echo "not a model folder: $model" >&2; exit 2; }
[ -d "$input" ] || { echo "not a folder: $input" >&2; exit 2; }
case "$(cd "$dest/.." 2>/dev/null && pwd)/" in "$app"/*) echo "dest must be outside app/" >&2; exit 2;; esac

mkdir -p "$dest/app" "$dest/models" "$dest/hackathon/output" "$dest/hackathon/restricted" "$dest/hackathon/secrets"
cp "$here/Dockerfile" "$dest/Dockerfile"
printf '%s\n' '*' '!Dockerfile' '!app' '!models' '!hackathon' '**/__pycache__' > "$dest/.dockerignore"
cp "$app/pyproject.toml" "$app/uv.lock" "$dest/app/"
pkgs=
for dir in "$app"/*/; do
  dir=${dir%/}; pkg=${dir##*/}
  case $pkg in tests|data|.orch|__pycache__|index) continue;; esac
  [ -f "$dir/__init__.py" ] || continue
  cp -R "$dir" "$dest/app/$pkg"
  pkgs="$pkgs $pkg"
done
[ -n "$pkgs" ] || { echo "no Python package found under app/" >&2; exit 2; }
index=none
if [ -d "$app/index" ]; then
  cp -R "$app/index" "$dest/app/index"
  index=app/index
else
  echo "note: app/index/ not found; the image will have no knowledge index (run build_kb.sh first)" >&2
fi
find "$dest/app" \( -name __pycache__ -o -name tests -o -name .pytest_cache \) -type d -prune -exec rm -rf {} +
find "$dest/app" -name .DS_Store -type f -exec rm -f {} +
name=$(basename "$model")
mkdir -p "$dest/models/$name"
for f in config.json config_sentence_transformers.json modules.json sentence_bert_config.json \
         special_tokens_map.json tokenizer.json tokenizer_config.json sentencepiece.bpe.model; do
  [ -f "$model/$f" ] && cp "$model/$f" "$dest/models/$name/"
done
for f in model.safetensors pytorch_model.bin; do
  [ -f "$model/$f" ] && cp "$model/$f" "$dest/models/$name/"
done
[ -d "$model/1_Pooling" ] && cp -R "$model/1_Pooling" "$dest/models/$name/"
cp -R "$input" "$dest/hackathon/input"
printf '%s\n' 'DECOY. Not a real answer. If an agent can read this file, the sandbox policy failed.' \
  > "$dest/hackathon/restricted/decoy_answer.md"
printf '%s\n' 'DECOY_TOKEN=not-a-real-secret-0000' > "$dest/hackathon/secrets/decoy_token.env"
chmod -R go-w,a+rX "$dest"
echo "staged: $dest (packages:$pkgs; index: $index; model: $name)"
