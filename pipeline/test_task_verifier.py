import json
import subprocess
from pathlib import Path
import sys
import pytest

from pipeline.task_verifier import (
    TaskVerifier,
    VerifierConfig,
)


def make_runner(
    *,
    input_passed=False,
    solution_passed=True,
    deterministic=True,
):
    calls = []

    def runner(command, **kwargs):
        calls.append(
            {
                "command": list(command),
                "cwd": kwargs["cwd"],
            }
        )

        cwd = Path(kwargs["cwd"])

        marker = (
            cwd / "implementation.txt"
        )

        content = marker.read_text(
            encoding="utf-8"
        )

        is_solution = (
            content == "solution\n"
        )

        # Realistic pytest-style output is required so that
        # TaskVerifier._is_assertion_failure() can correctly classify
        # a failing run as a genuine assertion-level behavioral
        # failure (as opposed to an infrastructure failure such as an
        # ImportError or a collection error).
        if is_solution:
            return_code = (
                0 if solution_passed else 1
            )
            stdout = (
                "1 passed in 0.01s\n"
                if solution_passed
                else (
                    "F                                                      "
                    "                   [100%]\n"
                    "=================================== FAILURES "
                    "===================================\n"
                    "____________________________ test_solution "
                    "_____________________________\n\n"
                    "    def test_solution():\n"
                    ">       assert False\n"
                    "E       AssertionError: assert False\n\n"
                    "test_solution.py:2: AssertionError\n"
                    "=========================== short test summary "
                    "info ============================\n"
                    "FAILED test_solution.py::test_solution - "
                    "AssertionError: assert False\n"
                    "1 failed in 0.01s\n"
                )
            )
        else:
            return_code = (
                0 if input_passed else 1
            )
            stdout = (
                "1 passed in 0.01s\n"
                if input_passed
                else (
                    "F                                                      "
                    "                   [100%]\n"
                    "=================================== FAILURES "
                    "===================================\n"
                    "____________________________ test_input "
                    "_____________________________\n\n"
                    "    def test_input():\n"
                    ">       assert False\n"
                    "E       AssertionError: assert False\n\n"
                    "test_input.py:2: AssertionError\n"
                    "=========================== short test summary "
                    "info ============================\n"
                    "FAILED test_input.py::test_input - "
                    "AssertionError: assert False\n"
                    "1 failed in 0.01s\n"
                )
            )

        if not deterministic and is_solution:
            stdout += str(len(calls))

        return subprocess.CompletedProcess(
            args=command,
            returncode=return_code,
            stdout=stdout,
            stderr="",
        )

    return runner, calls


def make_candidate_dirs(tmp_path):
    input_dir = (
        tmp_path / "input"
    )

    solution_dir = (
        tmp_path / "solution"
    )

    input_dir.mkdir()
    solution_dir.mkdir()

    (
        input_dir / "implementation.txt"
    ).write_text(
        "input\n",
        encoding="utf-8",
    )

    (
        solution_dir / "implementation.txt"
    ).write_text(
        "solution\n",
        encoding="utf-8",
    )

    return input_dir, solution_dir


def test_successful_fail_before_pass_after_and_determinism(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, calls = make_runner()

    evidence = (
        tmp_path / "evidence"
    )

    verifier = TaskVerifier(
        runner=runner,
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        evidence,
        task_id="task-001",
    )

    assert result.accepted is True

    validation = result.validation

    assert validation.fail_before_verified is True
    assert validation.pass_after_verified is True
    assert validation.deterministic_verified is True
    assert validation.validation_passed is True

    assert len(calls) == 3


def test_input_state_must_fail(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, calls = make_runner(
        input_passed=True,
    )

    evidence = (
        tmp_path / "evidence"
    )

    verifier = TaskVerifier(
        runner=runner,
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        evidence,
        task_id="task-002",
    )

    assert result.accepted is False

    assert (
        result.validation.fail_before_verified
        is False
    )

    # Solution must never execute when fail-before
    # does not establish the required failing state.
    assert len(calls) == 1


def test_solution_state_must_pass(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, calls = make_runner(
        solution_passed=False,
    )

    evidence = (
        tmp_path / "evidence"
    )

    verifier = TaskVerifier(
        runner=runner,
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        evidence,
        task_id="task-003",
    )

    assert result.accepted is False

    assert (
        result.validation.fail_before_verified
        is True
    )

    assert (
        result.validation.pass_after_verified
        is False
    )

    assert (
        result.validation.deterministic_verified
        is False
    )

    # No second solution run after a failed solution run.
    assert len(calls) == 2


def test_solution_must_be_deterministic(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, calls = make_runner(
        deterministic=False,
    )

    evidence = (
        tmp_path / "evidence"
    )

    verifier = TaskVerifier(
        runner=runner,
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        evidence,
        task_id="task-004",
    )

    assert result.accepted is False

    assert (
        result.validation.fail_before_verified
        is True
    )

    assert (
        result.validation.pass_after_verified
        is True
    )

    assert (
        result.validation.deterministic_verified
        is False
    )

    assert len(calls) == 3


def test_original_input_and_solution_are_untouched(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    before_input = (
        input_dir / "implementation.txt"
    ).read_text(
        encoding="utf-8"
    )

    before_solution = (
        solution_dir / "implementation.txt"
    ).read_text(
        encoding="utf-8"
    )

    runner, _ = make_runner()

    verifier = TaskVerifier(
        runner=runner,
    )

    verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        tmp_path / "evidence",
        task_id="task-005",
    )

    assert (
        input_dir / "implementation.txt"
    ).read_text(
        encoding="utf-8"
    ) == before_input

    assert (
        solution_dir / "implementation.txt"
    ).read_text(
        encoding="utf-8"
    ) == before_solution


def test_each_stage_runs_in_an_isolated_workspace(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, calls = make_runner()

    verifier = TaskVerifier(
        runner=runner,
    )

    verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        tmp_path / "evidence",
        task_id="task-006",
    )

    assert len(calls) == 3

    workspaces = {
        Path(call["cwd"])
        for call in calls
    }

    # The three executions are not sharing the same workspace.
    assert len(workspaces) == 2

    assert all(
        workspace != input_dir
        and workspace != solution_dir
        for workspace in workspaces
    )


def test_fail_before_evidence_is_machine_readable(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, _ = make_runner()

    evidence = (
        tmp_path / "evidence"
    )

    verifier = TaskVerifier(
        runner=runner,
    )

    verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        evidence,
        task_id="task-007",
    )

    path = (
        evidence / "fail_before.json"
    )

    assert path.exists()

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert data["task_id"] == "task-007"
    assert data["stage"] == "fail_before"
    assert data["expected"] == "assertion-level behavioral failure"
    assert data["verified"] is True

    assert data["actual"]["passed"] is False


def test_pass_after_evidence_is_machine_readable(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, _ = make_runner()

    evidence = (
        tmp_path / "evidence"
    )

    verifier = TaskVerifier(
        runner=runner,
    )

    verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        evidence,
        task_id="task-008",
    )

    data = json.loads(
        (
            evidence / "pass_after.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert data["stage"] == "pass_after"
    assert data["verified"] is True
    assert data["actual"]["passed"] is True


def test_determinism_evidence_contains_two_runs(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, _ = make_runner()

    evidence = (
        tmp_path / "evidence"
    )

    verifier = TaskVerifier(
        runner=runner,
    )

    verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        evidence,
        task_id="task-009",
    )

    data = json.loads(
        (
            evidence / "determinism.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert data["stage"] == "determinism"
    assert data["verified"] is True

    assert "first_run" in data
    assert "second_run" in data

    assert (
        data["first_run"]["return_code"]
        == data["second_run"]["return_code"]
    )


def test_command_is_preserved_exactly(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    runner, calls = make_runner()

    command = [
        "python",
        "-m",
        "pytest",
        "-q",
        "verifier",
    ]

    verifier = TaskVerifier(
        runner=runner,
    )

    verifier.verify(
        input_dir,
        solution_dir,
        command,
        tmp_path / "evidence",
        task_id="task-010",
    )

    assert all(
        call["command"] == command
        for call in calls
    )


def test_timeout_is_treated_as_failure(
    tmp_path,
):
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    def timeout_runner(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            timeout=kwargs["timeout"],
        )

    verifier = TaskVerifier(
        config=VerifierConfig(
            timeout_seconds=1,
        ),
        runner=timeout_runner,
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        tmp_path / "evidence",
        task_id="task-011",
    )

    # A timeout carries no assertion evidence at all, so it is
    # correctly classified as a non-assertion (infrastructure-style)
    # failure rather than a valid fail-before state. The task must
    # remain rejected either way.
    assert result.accepted is False

    assert (
        result.validation.fail_before_verified
        is False
    )

    assert (
        result.validation.pass_after_verified
        is False
    )


def test_missing_input_directory_is_rejected(
    tmp_path,
):
    solution_dir = (
        tmp_path / "solution"
    )
    solution_dir.mkdir()

    verifier = TaskVerifier()

    with pytest.raises(
        ValueError,
        match="input directory does not exist",
    ):
        verifier.verify(
            tmp_path / "missing",
            solution_dir,
            ["python", "-m", "pytest"],
            tmp_path / "evidence",
            task_id="task-012",
        )


def _run_test_module_runner(module_name: str, function_name: str):
    """
    A runner that actually executes a named test function from a named
    module in the workspace, using nothing but the stdlib (no pytest
    dependency required). Uncaught AssertionError -> non-zero exit,
    exactly like a real test runner would report a failing assertion.
    """
    import sys

    def runner(command, **kwargs):
        script = (
            "import sys; sys.path.insert(0, '.'); "
            f"import {module_name} as m; m.{function_name}(); "
            "print('ok')"
        )

        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=kwargs["cwd"],
            capture_output=True,
            text=True,
            timeout=kwargs.get("timeout"),
        )

    return runner


def test_oracle_overlay_replaces_stale_test_file_in_both_states(
    tmp_path,
):
    """
    Reproduces the History-task bug directly: a "parent" state whose own
    version of the test file has no regression assertion (so it looks
    like it passes even though the underlying bug is present), and a
    "fixing" state with the corrected source. An oracle_dir containing
    the fixing-commit's test file must be overlaid onto BOTH states, so
    the same regression assertion is what's actually exercised:

        parent source + oracle regression test -> FAIL
        fixing source + oracle regression test -> PASS
        fixing source + oracle regression test -> PASS (again)
    """
    import sys

    input_dir = tmp_path / "input"
    solution_dir = tmp_path / "solution"
    oracle_dir = tmp_path / "oracle"

    input_dir.mkdir()
    solution_dir.mkdir()
    oracle_dir.mkdir()

    # Buggy implementation.
    (input_dir / "calc.py").write_text(
        "def calculate(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    # The parent's own (stale) test file has no regression assertion at
    # all, so running it as-is against the buggy source would wrongly
    # report success.
    (input_dir / "test_calc.py").write_text(
        "from calc import calculate\n\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )

    # Fixed implementation.
    (solution_dir / "calc.py").write_text(
        "def calculate(value):\n"
        "    if value < 0:\n"
        "        return 0\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    (solution_dir / "test_calc.py").write_text(
        "from calc import calculate\n\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n"
        "    assert calculate(-5) == 0\n",
        encoding="utf-8",
    )

    # The task-local oracle: the fixing commit's version of the test,
    # which contains the actual regression assertion.
    (oracle_dir / "test_calc.py").write_text(
        "from calc import calculate\n\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n"
        "    assert calculate(-5) == 0\n",
        encoding="utf-8",
    )

    verifier = TaskVerifier(
        runner=_run_test_module_runner(
            "test_calc",
            "test_calculate",
        ),
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest", "-q", "test_calc.py"],
        tmp_path / "evidence",
        task_id="oracle-overlay-001",
        oracle_dir=oracle_dir,
    )

    assert result.validation.fail_before_verified is True
    assert result.validation.pass_after_verified is True
    assert result.validation.deterministic_verified is True
    assert result.accepted is True


def test_without_oracle_stale_parent_test_file_wrongly_passes(
    tmp_path,
):
    """
    Sanity check for the ORIGINAL bug: without an oracle overlay, running
    the parent's own (stale) test file against the buggy source
    incorrectly passes, so fail-before is never established and the task
    is correctly (but unhelpfully) rejected.
    """
    input_dir = tmp_path / "input"
    solution_dir = tmp_path / "solution"

    input_dir.mkdir()
    solution_dir.mkdir()

    (input_dir / "calc.py").write_text(
        "def calculate(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    (input_dir / "test_calc.py").write_text(
        "from calc import calculate\n\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )

    (solution_dir / "calc.py").write_text(
        "def calculate(value):\n"
        "    if value < 0:\n"
        "        return 0\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    (solution_dir / "test_calc.py").write_text(
        "from calc import calculate\n\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n"
        "    assert calculate(-5) == 0\n",
        encoding="utf-8",
    )

    verifier = TaskVerifier(
        runner=_run_test_module_runner(
            "test_calc",
            "test_calculate",
        ),
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest", "-q", "test_calc.py"],
        tmp_path / "evidence",
        task_id="no-oracle-001",
    )

    assert result.validation.fail_before_verified is False
    assert result.accepted is False


def test_oracle_dir_must_exist(
    tmp_path,
):
    input_dir = tmp_path / "input"
    solution_dir = tmp_path / "solution"

    input_dir.mkdir()
    solution_dir.mkdir()

    verifier = TaskVerifier()

    with pytest.raises(
        ValueError,
        match="oracle directory does not exist",
    ):
        verifier.verify(
            input_dir,
            solution_dir,
            ["python", "-m", "pytest"],
            tmp_path / "evidence",
            task_id="task-014",
            oracle_dir=tmp_path / "missing-oracle",
        )


def test_oracle_overlay_applies_to_configured_runner(
    tmp_path,
):
    """
    Using the scripted runner fixture: confirms the oracle file is
    physically present, at the right relative path, in the workspace
    each stage actually executes in.
    """
    input_dir, solution_dir = (
        make_candidate_dirs(tmp_path)
    )

    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()

    (oracle_dir / "oracle_marker.txt").write_text(
        "present\n",
        encoding="utf-8",
    )

    seen_markers = []

    def runner(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        marker = cwd / "oracle_marker.txt"
        seen_markers.append(marker.exists())

        content = (
            cwd / "implementation.txt"
        ).read_text(encoding="utf-8")

        is_solution = content == "solution\n"

        return_code = 0 if is_solution else 1

        stdout = (
            "1 passed in 0.01s\n"
            if is_solution
            else (
                "F                                                         "
                "                [100%]\n"
                "=================================== FAILURES "
                "===================================\n"
                "____________________________ test_input "
                "_____________________________\n\n"
                "    def test_input():\n"
                ">       assert False\n"
                "E       AssertionError: assert False\n\n"
                "test_input.py:2: AssertionError\n"
                "=========================== short test summary "
                "info ============================\n"
                "FAILED test_input.py::test_input - "
                "AssertionError: assert False\n"
                "1 failed in 0.01s\n"
            )
        )

        return subprocess.CompletedProcess(
            args=command,
            returncode=return_code,
            stdout=stdout,
            stderr="",
        )

    verifier = TaskVerifier(
        runner=runner,
    )

    result = verifier.verify(
        input_dir,
        solution_dir,
        ["python", "-m", "pytest"],
        tmp_path / "evidence",
        task_id="oracle-overlay-002",
        oracle_dir=oracle_dir,
    )

    # fail-before + pass-after + determinism == 3 executions, and the
    # oracle marker must have been present in every workspace.
    assert seen_markers == [True, True, True]
    assert result.accepted is True


def test_missing_solution_directory_is_rejected(
    tmp_path,
):
    input_dir = (
        tmp_path / "input"
    )
    input_dir.mkdir()

    verifier = TaskVerifier()

    with pytest.raises(
        ValueError,
        match="solution directory does not exist",
    ):
        verifier.verify(
            input_dir,
            tmp_path / "missing",
            ["python", "-m", "pytest"],
            tmp_path / "evidence",
            task_id="task-013",
        )

