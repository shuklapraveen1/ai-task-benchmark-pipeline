from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pipeline.task_history import HistoryChange, RegressionTest
from pipeline.task_miner import ExcisionCandidate
from pipeline.task_synthesis import (
    TaskSynthesisError,
    synthesize_excision_task,
    synthesize_history_task,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def init_git_repo(path: Path) -> None:
    git(path, "init")

    git(
        path,
        "config",
        "user.email",
        "benchmark@example.com",
    )
    git(
        path,
        "config",
        "user.name",
        "Benchmark",
    )


def commit(repo: Path, message: str) -> str:
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        content,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Synthetic History candidate
# ---------------------------------------------------------------------------


def make_history_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    init_git_repo(repo)

    write(
        repo,
        "example.py",
        """\
def calculate(value):
    return value + 1
""",
    )

    write(
        repo,
        "test_example.py",
        """\
from example import calculate


def test_calculate():
    assert calculate(1) == 2
""",
    )

    parent = commit(
        repo,
        "initial implementation",
    )

    # Behavioral change.
    write(
        repo,
        "example.py",
        """\
def calculate(value):
    if value < 0:
        return 0
    return value + 1
""",
    )

    write(
        repo,
        "test_example.py",
        """\
from example import calculate


def test_calculate():
    assert calculate(1) == 2
    assert calculate(-1) == 0
""",
    )

    target = commit(
        repo,
        "fix negative values",
    )

    return repo, parent, target


def test_synthesize_history_task_checks_out_parent_and_target(
    tmp_path,
):
    repo, parent, target = make_history_repo(
        tmp_path
    )

    fixing_test_content = (
        """\
from example import calculate


def test_calculate():
    assert calculate(1) == 2
    assert calculate(-1) == 0
"""
    )

    candidate = HistoryChange(
            commit=target,
            parent=parent,
            subject="fix negative values",
            files=("example.py", "test_example.py"),
            source_files=("example.py",),
            test_files=("test_example.py",),
            modules=("example",),
            score=1.0,
            rationale="test rationale",
            regression_tests=(
                RegressionTest(
                    path="test_example.py",
                    content=fixing_test_content,
                ),
            ),
        )

    task_dir = (
        tmp_path / "history-task"
    )

    result = synthesize_history_task(
        repo,
        candidate,
        task_dir,
    )

    assert result.task_type == "history"
    assert result.source_commit == parent
    assert result.solution_commit == target

    # The regression-test oracle must be materialized into verifier/,
    # using the exact fixing-commit content (not whatever is present
    # in input/ or solution/).
    assert result.verifier_dir == (
        task_dir / "verifier"
    )

    oracle_file = (
        result.verifier_dir
        / "test_example.py"
    )

    assert oracle_file.exists()
    assert (
        oracle_file.read_text(
            encoding="utf-8"
        )
        == fixing_test_content
    )

    input_example = (
        task_dir
        / "input"
        / "example.py"
    )

    solution_example = (
        task_dir
        / "solution"
        / "example.py"
    )

    input_test = (
        task_dir
        / "input"
        / "test_example.py"
    )

    solution_test = (
        task_dir
        / "solution"
        / "test_example.py"
    )

    assert input_example.exists()
    assert solution_example.exists()
    assert input_test.exists()
    assert solution_test.exists()

    assert (
        input_example.read_text(
            encoding="utf-8"
        )
        == """\
def calculate(value):
    return value + 1
"""
    )

    assert (
        solution_example.read_text(
            encoding="utf-8"
        )
        == """\
def calculate(value):
    if value < 0:
        return 0
    return value + 1
"""
    )

    assert (
        input_test.read_text(
            encoding="utf-8"
        )
        != solution_test.read_text(
            encoding="utf-8"
        )
    )


# ---------------------------------------------------------------------------
# Synthetic Excision candidate
# ---------------------------------------------------------------------------


def make_excision_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    write(
        repo,
        "sample.py",
        """\
def add(a, b):
    \"\"\"Return the sum of two values.\"\"\"
    total = a + b
    return total


def multiply(a, b):
    return a * b
""",
    )

    return repo


def make_excision_candidate() -> ExcisionCandidate:
    return ExcisionCandidate(
        function_id="function:sample.add",
        module_id="module:sample",
        name="add",
        file_path="sample.py",
        line_start=1,
        line_end=4,
        public=True,
        callers=("function:other.caller",),
        caller_count=2,
        coverage_percent=100.0,
        side_effect_signals=(),
        side_effect_penalty=0.0,
        public_api_bonus=30.0,
        coverage_score=30.0,
        caller_score=10.0,
        complexity_score=10.0,
        score=80.0,
        rationale=("public API", "multiple internal callers", "high baseline coverage"),
    )


def test_synthesize_excision_replaces_function_body(
    tmp_path,
):
    repo = make_excision_repo(
        tmp_path
    )

    candidate = make_excision_candidate()

    task_dir = (
        tmp_path / "excision-task"
    )

    result = synthesize_excision_task(
        repo,
        candidate,
        task_dir,
    )

    assert result.task_type == "excision"

    input_file = (
        task_dir
        / "input"
        / "sample.py"
    )

    solution_file = (
        task_dir
        / "solution"
        / "sample.py"
    )

    assert input_file.exists()
    assert solution_file.exists()

    input_source = input_file.read_text(
        encoding="utf-8"
    )

    solution_source = solution_file.read_text(
        encoding="utf-8"
    )

    # The original implementation must remain in solution/.
    assert (
        "total = a + b"
        in solution_source
    )
    assert (
        "return total"
        in solution_source
    )

    # The input implementation must be removed.
    assert (
        "total = a + b"
        not in input_source
    )

    assert (
        "return None"
        in input_source
    )

    # The function signature must remain intact.
    assert (
        "def add(a, b):"
        in input_source
    )

    # The docstring belongs to the function body and is therefore removed
    # along with the implementation.
    assert (
        '"""Return the sum of two values."""'
        not in input_source
    )

    # Unrelated functions must remain untouched.
    assert (
        "def multiply(a, b):"
        in input_source
    )
    assert (
        "return a * b"
        in input_source
    )


def test_excision_does_not_modify_original_repository(
    tmp_path,
):
    repo = make_excision_repo(
        tmp_path
    )

    original = (
        repo
        / "sample.py"
    ).read_text(
        encoding="utf-8"
    )

    candidate = make_excision_candidate()

    synthesize_excision_task(
        repo,
        candidate,
        tmp_path / "task",
    )

    assert (
        repo
        / "sample.py"
    ).read_text(
        encoding="utf-8"
    ) == original


def test_history_synthesis_does_not_modify_original_repository(
    tmp_path,
):
    repo, parent, target = make_history_repo(
        tmp_path
    )

    before = git(
        repo,
        "status",
        "--porcelain",
    )

    candidate = HistoryChange(
            commit=target,
            parent=parent,
            subject="fix negative values",
            files=("example.py", "test_example.py"),
            source_files=("example.py",),
            test_files=("test_example.py",),
            modules=("example",),
            score=1.0,
            rationale="test rationale",
            regression_tests=(
                RegressionTest(
                    path="test_example.py",
                    content=(
                        "from example import calculate\n"
                        "\n\n"
                        "def test_calculate():\n"
                        "    assert calculate(1) == 2\n"
                        "    assert calculate(-1) == 0\n"
                    ),
                ),
            ),
        )

    synthesize_history_task(
        repo,
        candidate,
        tmp_path / "history-task",
    )

    after = git(
        repo,
        "status",
        "--porcelain",
    )

    assert after == before

    assert (
        git(repo, "rev-parse", "HEAD")
        == target
    )


def test_history_synthesis_fails_closed_without_regression_tests(
    tmp_path,
):
    """
    A History candidate with no extractable regression-test oracle must
    never silently fall back to comparing against whatever (possibly
    stale, pre-fix) test file happens to sit in input/ or solution/.
    """

    repo, parent, target = make_history_repo(
        tmp_path
    )

    candidate = HistoryChange(
            commit=target,
            parent=parent,
            subject="fix negative values",
            files=("example.py", "test_example.py"),
            source_files=("example.py",),
            test_files=("test_example.py",),
            modules=("example",),
            score=1.0,
            rationale="test rationale",
            # No regression_tests supplied.
        )

    with pytest.raises(
        TaskSynthesisError
    ):
        synthesize_history_task(
            repo,
            candidate,
            tmp_path / "history-task",
        )


def test_excision_preserves_solution_as_independent_copy(
    tmp_path,
):
    repo = make_excision_repo(
        tmp_path
    )

    candidate = make_excision_candidate()

    task_dir = (
        tmp_path / "task"
    )

    synthesize_excision_task(
        repo,
        candidate,
        task_dir,
    )

    input_file = (
        task_dir
        / "input"
        / "sample.py"
    )

    solution_file = (
        task_dir
        / "solution"
        / "sample.py"
    )

    input_file.write_text(
        input_file.read_text(
            encoding="utf-8"
        )
        + "\n# input only\n",
        encoding="utf-8",
    )

    assert (
        "# input only"
        in input_file.read_text(
            encoding="utf-8"
        )
    )

    assert (
        "# input only"
        not in solution_file.read_text(
            encoding="utf-8"
        )
    )


def test_excision_fails_closed_for_missing_function(
    tmp_path,
):
    repo = make_excision_repo(
        tmp_path
    )

    candidate = ExcisionCandidate(
            function_id="function:sample.missing",
            module_id="module:sample",
            name="missing",
            file_path="sample.py",
            line_start=1,
            line_end=2,
            public=True,
            callers=(),
            caller_count=1,
            coverage_percent=100.0,
            side_effect_signals=(),
            side_effect_penalty=0.0,
            public_api_bonus=0.0,
            coverage_score=0.0,
            caller_score=0.0,
            complexity_score=0.0,
            score=1.0,
            rationale=(),
        )

    with pytest.raises(
        TaskSynthesisError
    ):
        synthesize_excision_task(
            repo,
            candidate,
            tmp_path / "task",
        )


def test_excision_fails_closed_for_missing_source_file(
    tmp_path,
):
    repo = make_excision_repo(
        tmp_path
    )

    candidate = ExcisionCandidate(
            function_id="function:sample.add",
            module_id="module:sample",
            name="add",
            file_path="does_not_exist.py",
            line_start=1,
            line_end=4,
            public=True,
            callers=(),
            caller_count=1,
            coverage_percent=100.0,
            side_effect_signals=(),
            side_effect_penalty=0.0,
            public_api_bonus=0.0,
            coverage_score=0.0,
            caller_score=0.0,
            complexity_score=0.0,
            score=1.0,
            rationale=(),
        )

    with pytest.raises(
        TaskSynthesisError
    ):
        synthesize_excision_task(
            repo,
            candidate,
            tmp_path / "task",
        )