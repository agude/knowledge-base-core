set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

shellcheck:
    find scripts -type f -exec shellcheck -x -P scripts -s bash {} +

portability:
    scripts/portability-lint

test:
    bats tests/*.bats

lint: shellcheck portability

check: lint test
