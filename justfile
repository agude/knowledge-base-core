set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

deps:
    npm ci

shellcheck:
    find scripts -type f ! -name '*.ts' -exec shellcheck -x -P scripts -s bash {} +

portability:
    scripts/portability-lint

type-check: deps
    npm run type-check

adapter-test: deps
    npm test

test:
    bats tests/*.bats

lint: shellcheck portability

check: lint type-check test adapter-test
