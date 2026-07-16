#!/usr/bin/env bash
set -euo pipefail

required=(
  "README.md"
  ".gitignore"
  "LICENSE"
  "docs/PRODUCT_BRIEF.md"
  "docs/GOAL.md"
  "docs/REQUIREMENTS.md"
  "docs/ARCHITECTURE.md"
  "pyproject.toml"
  "src/astro_true_north/__init__.py"
  "src/astro_true_north/cli.py"
  "tests/test_cli.py"
)

for path in "${required[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "missing required file: $path" >&2
    exit 1
  fi
done

if grep -R "TODO: Fill this in\\|TODO: Capture\\|TODO: Describe" \
  README.md docs src tests >/dev/null; then
  echo "bootstrap placeholder remains" >&2
  exit 1
fi

PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m unittest discover -s tests

echo "check ok"
