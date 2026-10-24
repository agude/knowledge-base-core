set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

sync *args:
    scripts/sync {{ args }}

install:
    scripts/install

shellcheck:
    find scripts -type d -name node_modules -prune -o -type f ! -name '*.ts' ! -name '*.json' ! -name '*.jq' -exec shellcheck -x -P scripts -s bash {} +

portability:
    scripts/portability-lint

pi-deps:
    cd scripts/adapters/pi && npm ci

pi-type-check: pi-deps
    cd scripts/adapters/pi && npm run type-check

pi-test: pi-deps
    cd scripts/adapters/pi && npm test

pi-check: pi-deps
    cd scripts/adapters/pi && npm run check

test:
    bats tests/*.bats

# Install the locked Python test environment.
py-sync:
    uv sync --locked
    # test_invocation.py checks how executables fail under an old interpreter.
    uv python install 3.9

# Lint and format-check the Python test harness.
py-lint:
    uv run --locked ruff check .
    uv run --locked ruff format --check .

# Regenerate python/ from kb/preamble.sh and kb/executables.py.
py-executables:
    uv run --locked python kb/executables.py

# Apply the Python formatter and safe lint fixes.
py-format:
    uv run --locked ruff format .
    uv run --locked ruff check --fix .

# Run the characterization suite against KB_IMPL (default bash).
test-py *args:
    uv run --locked pytest -n auto {{ args }}

# Run the characterization suite against the Python implementation in python/.
# Tests that need an executable not yet ported are skipped.
test-py-python *args:
    KB_IMPL=python uv run --locked pytest -n auto {{ args }}

# The part of the suite that runs on Windows (non-blocking CI job, plan 4.0).
test-windows:
    uv run --locked pytest -m "static"

# Check that every characterization test fails under a null implementation
# through contract goldens or semantic assertions, not reference goldens.
test-py-null *args:
    uv run --locked python tests/py/nullcheck.py --contract {{ args }}

# Time the read commands and hook workloads (tests/py/bench.py --help).
bench *args:
    uv run --locked python tests/py/bench.py {{ args }}

# Time Python start-up and the SessionEnd hook (tests/py/bench_startup.py --help).
bench-startup *args:
    uv run --locked python tests/py/bench_startup.py {{ args }}

# Run the benchmark once against the null implementation as a smoke test.
bench-smoke:
    uv run --locked python tests/py/bench.py --impl null0 --scale 1 --runs 1 > /dev/null

lint: shellcheck portability py-lint

check: lint test test-py test-py-python test-py-null bench-smoke

check-all: check pi-check
