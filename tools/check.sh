#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
CHECK_DIR="$(mktemp -d)"
trap 'rm -rf -- "$CHECK_DIR"' EXIT
c++ -std=c++11 -Wall -Wextra tests/control_test.cpp -o "$CHECK_DIR/control-test"
"$CHECK_DIR/control-test"
c++ -std=c++11 -Wall -Wextra -I tests/stubs tests/firmware_test.cpp -o "$CHECK_DIR/firmware-test"
"$CHECK_DIR/firmware-test"
.venv/bin/python -m py_compile tools/conveyor.py backend/*.py
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
bash -n tools/*.sh
git diff --check
echo 'Control, firmware state transitions, panel, Python and shell checks passed.'
