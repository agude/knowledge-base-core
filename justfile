set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

sync *args:
    scripts/sync {{ args }}

install:
    scripts/install

shellcheck:
    find scripts -type d -name node_modules -prune -o -type f ! -name '*.ts' ! -name '*.json' -exec shellcheck -x -P scripts -s bash {} +

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

lint: shellcheck portability

check: lint test

check-all: check pi-check
