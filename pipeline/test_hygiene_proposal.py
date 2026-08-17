from pipeline.discover import RepoContext
from pipeline.lint_format import LintFormatInfo, HygieneTool
from pipeline.hygiene_proposal import propose_hygiene


def make_context():
    return RepoContext(
        repo_path=".",
        ecosystem="python",
    )


def test_no_convention_proposes_ruff():
    info = LintFormatInfo(
        tools=[],
        formatter_config_files=[],
        linter_config_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[],
    )

    proposal = propose_hygiene(info, make_context())

    assert proposal.tool == "ruff"
    assert proposal.action == "introduce_default"
    assert proposal.confidence == "medium"
    assert "add Ruff configuration" in proposal.changes


def test_existing_ruff_is_preserved():
    info = LintFormatInfo(
        tools=[
            HygieneTool(
                name="ruff",
                kind="linter",
                source="pyproject.toml",
                config_files=["pyproject.toml"],
                command=[
                    "python",
                    "-m",
                    "ruff",
                    "check",
                    ".",
                ],
                confidence="explicit",
            )
        ],
        formatter_config_files=["pyproject.toml"],
        linter_config_files=["pyproject.toml"],
        existing_conventions=True,
        default_standard_proposed=False,
        warnings=[],
    )

    proposal = propose_hygiene(info, make_context())

    assert proposal.tool == "ruff"
    assert proposal.action == "preserve_existing"
    assert proposal.confidence == "high"
    assert proposal.changes == []


def test_existing_black_is_preserved():
    info = LintFormatInfo(
        tools=[
            HygieneTool(
                name="black",
                kind="formatter",
                source="pyproject.toml",
                config_files=["pyproject.toml"],
                command=[
                    "python",
                    "-m",
                    "black",
                    "--check",
                    ".",
                ],
                confidence="explicit",
            )
        ],
        formatter_config_files=["pyproject.toml"],
        linter_config_files=[],
        existing_conventions=True,
        default_standard_proposed=False,
        warnings=[],
    )

    proposal = propose_hygiene(info, make_context())

    assert proposal.tool == "black"
    assert proposal.action == "preserve_existing"
    assert proposal.confidence == "high"
    assert proposal.changes == []


def test_multiple_existing_tools_preserve_first_detected():
    info = LintFormatInfo(
        tools=[
            HygieneTool(
                name="ruff",
                kind="linter",
                source=".github/workflows/tests.yml",
                config_files=[".github/workflows/tests.yml"],
                command=[
                    "python",
                    "-m",
                    "ruff",
                    "check",
                    ".",
                ],
                confidence="explicit",
            ),
            HygieneTool(
                name="black",
                kind="formatter",
                source="pyproject.toml",
                config_files=["pyproject.toml"],
                command=[
                    "python",
                    "-m",
                    "black",
                    "--check",
                    ".",
                ],
                confidence="explicit",
            ),
        ],
        formatter_config_files=["pyproject.toml"],
        linter_config_files=[".github/workflows/tests.yml"],
        existing_conventions=True,
        default_standard_proposed=False,
        warnings=[],
    )

    proposal = propose_hygiene(info, make_context())

    assert proposal.tool == "ruff"
    assert proposal.action == "preserve_existing"
    assert proposal.confidence == "high"
    assert proposal.changes == []
