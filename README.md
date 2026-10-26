# knowledge-base

`kb` lets LLM agent sessions read and search a knowledge base: curated
articles and source documents, and the observations and questions behind them.
It only reads the content repository. Recording and curation are handled by
other tools.

## Usage

```sh
kb recall QUERY...    # find the curated sections that answer a query
kb read LOCATOR...    # print the text that each locator names
kb map [PATH]         # list the articles under PATH, with their sections
kb --help             # every command
```

Locators look like `knowledge/infra/nas.md#2` (an H2 section), `#1.1` (an H3
section), `#top` (the prose before the first H2), `#title`, or a bare path. Every
locator that `recall` and `map` print is accepted by `read` unchanged.

The content repository comes from the `KB_CONTENT` environment variable, or
from `content = "PATH"` in `config.toml`. That file is
`$XDG_CONFIG_HOME/kb/config.toml`, or `~/.config/kb/config.toml` without
`XDG_CONFIG_HOME`, and `%LOCALAPPDATA%\kb\config.toml` on Windows.

## Development

Requires [uv](https://docs.astral.sh/uv/) 0.13 or newer and [just](https://just.systems/).

The `.python-version` file selects Python 3.15. uv 0.13 or newer can
download its final release. The lower uv minimum in `pyproject.toml` lets
Dependabot update the lock on Python 3.11; CI tests that minimum.

```sh
just sync           # Install the locked development environment.
just hooks-install  # Install the pre-commit hook, which runs `just lint`.
just check          # Run lint, type-check, and test.
just eval           # Score retrieval against the question sets under tests/fixtures.
```

Run `just` to list every recipe.

## Releasing

```sh
just release patch  # Or minor or major. Runs `just check`, then commits and tags.
git push origin HEAD vX.Y.Z
```

## License

[CC0 1.0 Universal](LICENSE.md)
