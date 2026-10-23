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

# Lint and format-check the Python test harness.
py-lint:
    uv run --locked ruff check .
    uv run --locked ruff format --check .

# Apply the Python formatter and safe lint fixes.
py-format:
    uv run --locked ruff format .
    uv run --locked ruff check --fix .

# Run the characterization suite against KB_IMPL (default bash).
test-py *args:
    uv run --locked pytest {{ args }}

# Check that every characterization test fails under a null implementation.
test-py-null *args:
    uv run --locked python tests/py/nullcheck.py {{ args }}

lint: shellcheck portability py-lint

check: lint test test-py test-py-null

check-all: check pi-check
