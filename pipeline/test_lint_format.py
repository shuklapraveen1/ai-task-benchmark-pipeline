from pathlib import Path

from pipeline.discover import RepoContext
from pipeline.lint_format import discover_lint_format


def write_file(root, relative_path, content):
    path = root / relative_path
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        content,
        encoding="utf-8",
    )
    return path


def tool_names(info):
    return {(tool.name, tool.kind) for tool in info.tools}


def test_existing_ruff_configuration(tmp_path):
    write_file(
        tmp_path,
        "pyproject.toml",
        """
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F"]
""",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    assert info.existing_conventions is True
    assert info.default_standard_proposed is False

    assert ("ruff", "formatter") in tool_names(info)
    assert ("ruff", "linter") in tool_names(info)

    assert "pyproject.toml" in info.formatter_config_files
    assert "pyproject.toml" in info.linter_config_files

    for tool in info.tools:
        assert tool.confidence == "explicit"


def test_existing_black_configuration(tmp_path):
    write_file(
        tmp_path,
        "pyproject.toml",
        """
[tool.black]
line-length = 88
target-version = ["py310"]
""",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    assert info.existing_conventions is True
    assert info.default_standard_proposed is False

    assert ("black", "formatter") in tool_names(info)
    assert ("ruff", "formatter") not in tool_names(info)

    assert "pyproject.toml" in info.formatter_config_files


def test_ci_only_ruff_invocation(tmp_path):
    write_file(
        tmp_path,
        ".github/workflows/tests.yml",
        """
name: tests

on:
  push:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python -m ruff check .
""",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    assert info.existing_conventions is True
    assert info.default_standard_proposed is False

    assert ("ruff", "linter") in tool_names(info)

    ruff = [
        tool for tool in info.tools if tool.name == "ruff" and tool.kind == "linter"
    ][0]

    assert ruff.confidence == "explicit"
    assert ruff.source == ".github/workflows/tests.yml"


def test_no_configuration_proposes_default(tmp_path):
    write_file(
        tmp_path,
        "module.py",
        "def hello():\n    return 'hello'\n",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    assert info.tools == []
    assert info.existing_conventions is False
    assert info.default_standard_proposed is True

    assert info.formatter_config_files == []
    assert info.linter_config_files == []

    assert info.warnings


def test_unrelated_tools_are_ignored(tmp_path):
    write_file(
        tmp_path,
        "pyproject.toml",
        """
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.coverage.run]
branch = true

[tool.coverage.report]
show_missing = true
""",
    )

    write_file(
        tmp_path,
        ".github/workflows/tests.yml",
        """
name: tests

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: python -m pytest
      - run: python -m coverage run -m pytest
""",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    assert info.tools == []
    assert info.existing_conventions is False
    assert info.default_standard_proposed is True


def test_multiple_existing_tools_are_preserved(tmp_path):
    write_file(
        tmp_path,
        "pyproject.toml",
        """
[tool.black]
line-length = 88

[tool.isort]
profile = "black"
""",
    )

    write_file(
        tmp_path,
        ".flake8",
        """
max-line-length = 88
exclude = .venv
""",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    names = tool_names(info)

    assert ("black", "formatter") in names
    assert ("isort", "formatter") in names
    assert ("flake8", "linter") in names

    assert info.existing_conventions is True
    assert info.default_standard_proposed is False


def test_generated_directories_are_ignored(tmp_path):
    write_file(
        tmp_path,
        "build/lib/ruff.toml",
        """
[tool.ruff]
line-length = 88
""",
    )

    write_file(
        tmp_path,
        "dist/.flake8",
        """
max-line-length = 88
""",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    assert info.tools == []
    assert info.default_standard_proposed is True


def test_tool_commands_are_safe_check_commands(tmp_path):
    write_file(
        tmp_path,
        "pyproject.toml",
        """
[tool.black]
line-length = 88

[tool.ruff]
line-length = 88
""",
    )

    context = RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

    info = discover_lint_format(
        tmp_path,
        context,
    )

    for tool in info.tools:
        assert tool.command is not None

        command_text = " ".join(tool.command)

        assert "--check" in command_text or (
            tool.name == "ruff" and tool.kind == "linter"
        )

        # Discovery must never produce an in-place formatting command.
        assert "--fix" not in command_text
