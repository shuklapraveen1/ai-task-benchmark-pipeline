import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


SUPPORTED_FORMATTERS = {
    "ruff",
    "black",
    "isort",
}

SUPPORTED_LINTERS = {
    "ruff",
    "flake8",
    "pylint",
}

IGNORED_PATH_PARTS = {
    "build",
    "dist",
    ".tox",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


@dataclass
class HygieneTool:
    name: str
    kind: str
    source: str
    config_files: List[str]
    command: Optional[List[str]]
    confidence: str


@dataclass
class LintFormatInfo:
    tools: List[HygieneTool] = field(default_factory=list)

    formatter_config_files: List[str] = field(default_factory=list)
    linter_config_files: List[str] = field(default_factory=list)

    existing_conventions: bool = False
    default_standard_proposed: bool = False

    warnings: List[str] = field(default_factory=list)


@dataclass
class HygieneProposal:
    action: str
    tool: HygieneTool

    reason: str

    files_to_create: List[str] = field(default_factory=list)
    files_to_modify: List[str] = field(default_factory=list)

    safe_to_apply: bool = False


def _is_ignored_path(path):
    parts = Path(path).parts

    return any(part in IGNORED_PATH_PARTS for part in parts)


def _read_text(path):
    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""


def _relative(repo_path, path):
    try:
        return str(
            Path(path).resolve().relative_to(
                Path(repo_path).resolve()
            )
        ).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _make_tool(
    name,
    kind,
    source,
    config_files,
    confidence,
):
    if kind == "formatter":
        if name == "ruff":
            command = [
                "python",
                "-m",
                "ruff",
                "format",
                "--check",
                ".",
            ]

        elif name == "black":
            command = [
                "python",
                "-m",
                "black",
                "--check",
                ".",
            ]

        elif name == "isort":
            command = [
                "python",
                "-m",
                "isort",
                "--check-only",
                ".",
            ]

        else:
            command = None

    elif kind == "linter":
        if name == "ruff":
            command = [
                "python",
                "-m",
                "ruff",
                "check",
                ".",
            ]

        elif name == "flake8":
            command = [
                "python",
                "-m",
                "flake8",
                ".",
            ]

        elif name == "pylint":
            command = [
                "python",
                "-m",
                "pylint",
                ".",
            ]

        else:
            command = None

    else:
        command = None

    return HygieneTool(
        name=name,
        kind=kind,
        source=source,
        config_files=list(config_files),
        command=command,
        confidence=confidence,
    )


def _add_tool(
    tools,
    seen,
    name,
    kind,
    source,
    config_files,
    confidence,
):
    key = (name, kind)

    if key in seen:
        return

    tools.append(
        _make_tool(
            name=name,
            kind=kind,
            source=source,
            config_files=config_files,
            confidence=confidence,
        )
    )

    seen.add(key)


def _detect_from_pyproject(
    repo_path,
    tools,
    seen,
    formatter_configs,
    linter_configs,
):
    path = repo_path / "pyproject.toml"

    if not path.exists():
        return

    text = _read_text(path)

    # Explicit Ruff configuration.
    if re.search(
        r"(?m)^\s*\[tool\.ruff(?:[.\]]|$)",
        text,
    ):
        _add_tool(
            tools,
            seen,
            "ruff",
            "formatter",
            "pyproject.toml",
            ["pyproject.toml"],
            "explicit",
        )

        _add_tool(
            tools,
            seen,
            "ruff",
            "linter",
            "pyproject.toml",
            ["pyproject.toml"],
            "explicit",
        )

        formatter_configs.append("pyproject.toml")
        linter_configs.append("pyproject.toml")

    # Black configuration.
    if re.search(
        r"(?m)^\s*\[tool\.black\]\s*$",
        text,
    ):
        _add_tool(
            tools,
            seen,
            "black",
            "formatter",
            "pyproject.toml",
            ["pyproject.toml"],
            "explicit",
        )

        formatter_configs.append("pyproject.toml")

    # isort configuration.
    if re.search(
        r"(?m)^\s*\[tool\.isort\]\s*$",
        text,
    ):
        _add_tool(
            tools,
            seen,
            "isort",
            "formatter",
            "pyproject.toml",
            ["pyproject.toml"],
            "explicit",
        )

        formatter_configs.append("pyproject.toml")

    # Pylint configuration.
    if re.search(
        r"(?m)^\s*\[tool\.pylint(?:[.\]]|$)",
        text,
    ):
        _add_tool(
            tools,
            seen,
            "pylint",
            "linter",
            "pyproject.toml",
            ["pyproject.toml"],
            "explicit",
        )

        linter_configs.append("pyproject.toml")


def _detect_config_files(
    repo_path,
    tools,
    seen,
    formatter_configs,
    linter_configs,
):
    # Dedicated Ruff configuration.
    for filename in ("ruff.toml", ".ruff.toml"):
        path = repo_path / filename

        if not path.exists():
            continue

        _add_tool(
            tools,
            seen,
            "ruff",
            "formatter",
            filename,
            [filename],
            "explicit",
        )

        _add_tool(
            tools,
            seen,
            "ruff",
            "linter",
            filename,
            [filename],
            "explicit",
        )

        formatter_configs.append(filename)
        linter_configs.append(filename)

    # Black.
    for filename in ("pyproject.toml", "setup.cfg"):
        path = repo_path / filename

        if not path.exists():
            continue

        text = _read_text(path)

        if filename == "setup.cfg":
            detected = re.search(
                r"(?m)^\s*\[black\]\s*$",
                text,
            )
        else:
            detected = False

        if detected:
            _add_tool(
                tools,
                seen,
                "black",
                "formatter",
                filename,
                [filename],
                "explicit",
            )

            formatter_configs.append(filename)

    # isort.
    path = repo_path / "setup.cfg"

    if path.exists():
        text = _read_text(path)

        if re.search(
            r"(?m)^\s*\[isort\]\s*$",
            text,
        ):
            _add_tool(
                tools,
                seen,
                "isort",
                "formatter",
                "setup.cfg",
                ["setup.cfg"],
                "explicit",
            )

            formatter_configs.append("setup.cfg")

    # Flake8.
    for filename in (
        ".flake8",
        "setup.cfg",
        "tox.ini",
    ):
        path = repo_path / filename

        if not path.exists():
            continue

        text = _read_text(path)

        if filename == ".flake8":
            detected = True
        else:
            detected = bool(
                re.search(
                    r"(?m)^\s*\[flake8\]\s*$",
                    text,
                )
            )

        if detected:
            _add_tool(
                tools,
                seen,
                "flake8",
                "linter",
                filename,
                [filename],
                "explicit",
            )

            linter_configs.append(filename)

    # Pylint in common INI-style files.
    for filename in (
        "setup.cfg",
        "tox.ini",
        ".pylintrc",
    ):
        path = repo_path / filename

        if not path.exists():
            continue

        text = _read_text(path)

        if filename == ".pylintrc":
            detected = True
        else:
            detected = bool(
                re.search(
                    r"(?m)^\s*\[(?:MASTER|MAIN|MESSAGES CONTROL|"
                    r"BASIC|FORMAT|DESIGN|REFACTORING|TYPECHECK|"
                    r"WARNINGS|VARIABLES|SIMILARITIES)\]\s*$",
                    text,
                )
            )

        if detected:
            _add_tool(
                tools,
                seen,
                "pylint",
                "linter",
                filename,
                [filename],
                "explicit",
            )

            linter_configs.append(filename)


def _detect_from_ci(
    repo_path,
    tools,
    seen,
    formatter_configs,
    linter_configs,
):
    github = repo_path / ".github" / "workflows"

    if not github.exists():
        return

    for path in github.rglob("*"):
        if not path.is_file():
            continue

        if _is_ignored_path(path):
            continue

        text = _read_text(path)

        if not text:
            continue

        relative = _relative(
            repo_path,
            path,
        )

        # We deliberately require a command invocation rather
        # than merely seeing a package name.
        if re.search(
            r"\bruff\s+(?:check|format)\b",
            text,
        ):
            if re.search(
                r"\bruff\s+format\b",
                text,
            ):
                _add_tool(
                    tools,
                    seen,
                    "ruff",
                    "formatter",
                    relative,
                    [],
                    "explicit",
                )

            if re.search(
                r"\bruff\s+check\b",
                text,
            ):
                _add_tool(
                    tools,
                    seen,
                    "ruff",
                    "linter",
                    relative,
                    [],
                    "explicit",
                )

        if re.search(
            r"\bblack(?:\s+--check)?\b",
            text,
        ):
            _add_tool(
                tools,
                seen,
                "black",
                "formatter",
                relative,
                [],
                "explicit",
            )

        if re.search(
            r"\bisort\b",
            text,
        ):
            _add_tool(
                tools,
                seen,
                "isort",
                "formatter",
                relative,
                [],
                "explicit",
            )

        if re.search(
            r"\bflake8\b",
            text,
        ):
            _add_tool(
                tools,
                seen,
                "flake8",
                "linter",
                relative,
                [],
                "explicit",
            )

        if re.search(
            r"\bpylint\b",
            text,
        ):
            _add_tool(
                tools,
                seen,
                "pylint",
                "linter",
                relative,
                [],
                "explicit",
            )


def discover_lint_format(
    repo_path,
    context,
):
    """
    Discover existing linting and formatting conventions.

    This function is read-only.

    It does not:
      * install tools
      * create configuration files
      * modify repository files
      * run formatters
      * run linters

    It returns LintFormatInfo describing only repository evidence
    and whether a default standard may reasonably be proposed.
    """

    repo_path = Path(repo_path)

    tools = []
    seen = set()

    formatter_configs = []
    linter_configs = []

    warnings = []

    _detect_from_pyproject(
        repo_path,
        tools,
        seen,
        formatter_configs,
        linter_configs,
    )

    _detect_config_files(
        repo_path,
        tools,
        seen,
        formatter_configs,
        linter_configs,
    )

    _detect_from_ci(
        repo_path,
        tools,
        seen,
        formatter_configs,
        linter_configs,
    )

    # Deduplicate config paths while preserving order.
    formatter_configs = list(dict.fromkeys(formatter_configs))

    linter_configs = list(dict.fromkeys(linter_configs))

    existing_conventions = bool(tools)

    default_standard_proposed = not existing_conventions

    if not existing_conventions:
        warnings.append(
            "No existing linting or formatting convention was detected."
        )

    return LintFormatInfo(
        tools=tools,
        formatter_config_files=formatter_configs,
        linter_config_files=linter_configs,
        existing_conventions=existing_conventions,
        default_standard_proposed=default_standard_proposed,
        warnings=warnings,
    )