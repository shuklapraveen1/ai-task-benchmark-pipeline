from dataclasses import dataclass
from pathlib import Path

from pipeline.hygiene_mutation import (
    HygieneChange,
    apply_hygiene_change,
)


@dataclass
class FakeTestRun:
    tests_run: int
    tests_passed: int
    tests_failed: int


@dataclass
class FakeBaseline:
    overall_passed: bool
    deterministic: bool
    test_runs: list
    coverage: object = None


def make_baseline(
    passed=True,
    deterministic=True,
    tests_run=10,
    tests_passed=10,
    tests_failed=0,
):
    return FakeBaseline(
        overall_passed=passed,
        deterministic=deterministic,
        test_runs=[
            FakeTestRun(
                tests_run=tests_run,
                tests_passed=tests_passed,
                tests_failed=tests_failed,
            )
        ],
    )


def make_change():
    return HygieneChange(
        tool="fake",
        action="format",
        command=[
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "p=Path('example.py'); "
                "p.write_text('x = 1\\n')"
            ),
        ],
        files=["example.py"],
        reason="Synthetic formatting change.",
        confidence="high",
    )


def test_successful_formatting_preserves_baseline(tmp_path):
    source = tmp_path / "example.py"
    original = "x=1\n"
    source.write_text(original)

    baseline = make_baseline()

    def baseline_runner(
        repo_path,
        context,
        dependency_info,
    ):
        return make_baseline()

    result = apply_hygiene_change(
        tmp_path,
        None,
        None,
        baseline,
        make_change(),
        baseline_runner=baseline_runner,
    )

    assert result.accepted is True
    assert result.execution.applied is True
    assert result.validation.validation_passed is True
    assert result.rolled_back is False

    # Mutation happened in the isolated workspace, so original repo is untouched.
    assert result.original_repo_untouched is True
    assert source.read_text() == original
    assert result.execution.changed_files


def test_mutation_that_breaks_baseline_is_rejected_and_rolled_back(
    tmp_path,
):
    source = tmp_path / "example.py"

    original = "x=1\n"

    source.write_text(original)

    baseline = make_baseline()

    change = HygieneChange(
        tool="fake",
        action="break",
        command=[
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "Path('example.py').write_text("
                "'broken = True\\n'"
                ")"
            ),
        ],
        files=["example.py"],
        reason="Synthetic breaking change.",
        confidence="high",
    )

    def baseline_runner(
        repo_path,
        context,
        dependency_info,
    ):
        return make_baseline(
            passed=False,
            deterministic=True,
            tests_run=10,
            tests_passed=9,
            tests_failed=1,
        )

    result = apply_hygiene_change(
        tmp_path,
        None,
        None,
        baseline,
        change,
        baseline_runner=baseline_runner,
    )

    assert result.accepted is False
    assert result.validation.regression_detected is True
    assert result.rolled_back is True
    assert result.rollback_successful is True

    # The original repository was never mutated.
    assert source.read_text() == original

    assert result.original_repo_untouched is True


def test_non_deterministic_baseline_is_rejected_immediately(
    tmp_path,
):
    source = tmp_path / "example.py"

    original = "x=1\n"

    source.write_text(original)

    baseline = make_baseline(deterministic=False)

    change = make_change()

    command_was_run = False

    def baseline_runner(
        repo_path,
        context,
        dependency_info,
    ):
        nonlocal command_was_run
        command_was_run = True
        return make_baseline()

    result = apply_hygiene_change(
        tmp_path,
        None,
        None,
        baseline,
        change,
        baseline_runner=baseline_runner,
    )

    assert result.accepted is False

    assert result.validation.validation_passed is False

    assert "Cannot mutate a non-deterministic repository." in result.validation.reasons

    assert command_was_run is False

    assert source.read_text() == original

    assert result.original_repo_untouched is True
