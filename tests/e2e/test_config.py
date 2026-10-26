"""End-to-end tests for finding the content repository."""

import shutil
from pathlib import Path

from .harness import Kb

INFRA_COUNT = "knowledge/infra | 4 articles\n"


def write_config(kb: Kb, text: str) -> Path:
    """Write the config file at the path kb reads when XDG_CONFIG_HOME is set."""
    path = kb.home / "xdg" / "kb" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_environment_names_the_content_root(kb: Kb) -> None:
    result = kb("map", "--depth", "1")
    assert result.returncode == 0
    assert result.stdout.startswith(INFRA_COUNT)


def test_config_file_names_the_content_root(kb: Kb) -> None:
    write_config(kb, f'content = "{kb.content}"\n')
    result = kb("map", "--depth", "1", env={"KB_CONTENT": None})
    assert result.returncode == 0
    assert result.stdout.startswith(INFRA_COUNT)


def test_default_config_location_without_xdg_config_home(kb: Kb) -> None:
    path = kb.home / ".config" / "kb" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f'content = "{kb.content}"\n', encoding="utf-8")
    result = kb("map", "--depth", "1", env={"KB_CONTENT": None, "XDG_CONFIG_HOME": None})
    assert result.returncode == 0
    assert result.stdout.startswith(INFRA_COUNT)


def test_environment_overrides_the_config_file(kb: Kb) -> None:
    write_config(kb, f'content = "{kb.home / "missing"}"\n')
    result = kb("map", "--depth", "1")
    assert result.returncode == 0
    assert result.stdout.startswith(INFRA_COUNT)


def test_empty_environment_value_counts_as_unset(kb: Kb) -> None:
    write_config(kb, f'content = "{kb.content}"\n')
    result = kb("map", "--depth", "1", env={"KB_CONTENT": ""})
    assert result.returncode == 0
    assert result.stdout.startswith(INFRA_COUNT)


def test_missing_content_root_names_the_config_file(kb: Kb) -> None:
    result = kb("map", "--depth", "1", env={"KB_CONTENT": None})
    config = kb.home / "xdg" / "kb" / "config.toml"
    assert result.returncode == 1
    assert result.stderr == (
        'knowledge base: no content repository; set KB_CONTENT or add content = "PATH" '
        f"to {config}\n"
    )


def test_content_root_that_is_not_a_directory_is_reported(kb: Kb) -> None:
    missing = kb.home / "missing"
    result = kb("map", env={"KB_CONTENT": str(missing)})
    assert result.returncode == 1
    assert result.stderr == f"knowledge base: content root is not a directory: {missing}\n"


def test_config_path_with_quote_and_backslash_round_trips(kb: Kb) -> None:
    odd = kb.home / 'odd "name" \\dir'
    shutil.copytree(kb.content, odd)
    escaped = str(odd).replace("\\", "\\\\").replace('"', '\\"')
    write_config(kb, f'content = "{escaped}"\n')
    result = kb("map", "--depth", "1", env={"KB_CONTENT": None})
    assert result.returncode == 0
    assert result.stdout.startswith(INFRA_COUNT)


def test_tilde_in_the_config_file_is_expanded(kb: Kb) -> None:
    shutil.copytree(kb.content, kb.home / "notes")
    write_config(kb, 'content = "~/notes"\n')
    result = kb("map", "--depth", "1", env={"KB_CONTENT": None})
    assert result.returncode == 0
    assert result.stdout.startswith(INFRA_COUNT)


def test_invalid_config_file_is_reported(kb: Kb) -> None:
    config = write_config(kb, "content = \n")
    result = kb("map", "--depth", "1", env={"KB_CONTENT": None})
    assert result.returncode == 1
    assert result.stderr.startswith(f"knowledge base: invalid config file {config}: ")


def test_config_content_must_be_a_string(kb: Kb) -> None:
    config = write_config(kb, "content = 3\n")
    result = kb("map", "--depth", "1", env={"KB_CONTENT": None})
    assert result.returncode == 1
    assert result.stderr == (
        f"knowledge base: invalid config file {config}: content must be a string\n"
    )
