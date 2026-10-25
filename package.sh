#!/usr/bin/env bash
set -euo pipefail
mkdir -p out
find py_modules -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
name="save-drive"
version=$(node -p "require('./package.json').version")
out="out/${name}-${version}.zip"
rm -f "$out"
zip -r "$out" \
  main.py \
  py_modules \
  src \
  dist \
  plugin.json \
  package.json \
  README.md \
  GOOGLE-SETUP.md \
  credentials.example.json \
  defaults \
  LICENSE \
  assets
printf 'Created %s\\n' "$out"
