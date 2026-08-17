import re
from pipeline.baseline import (
    _parse_pytest_counts,
    _results_are_deterministic,
    _select_test_command,
)
from pipeline.discover import RepoContext


def test_pytest_with_doctest_uses_doctest_modules():
    class Context:
        test_frameworks = ["pytest", "doctest"]

    command, framework = _select_test_command(
        ".",
        Context(),
        "python",
    )

    assert framework == "pytest"
    assert command[:5] == [
        "python",
        "-m",
        "pytest",
        "-q",
        "--doctest-modules",
    ]


def test_pytest_without_doctest_does_not_add_doctest_flag():
    class Context:
        test_frameworks = ["pytest"]

    command, framework = _select_test_command(
        ".",
        Context(),
        "python",
    )

    assert framework == "pytest"
    assert "--doctest-modules" not in command


def test_parse_pytest_counts_all_results():
    output = """
    100 passed, 2 failed, 3 skipped in 4.21s
    """

    (
        tests_run,
        passed,
        failed,
        skipped,
    ) = _parse_pytest_counts(output)

    assert tests_run == 105
    assert passed == 100
    assert failed == 2
    assert skipped == 3


def test_parse_pytest_counts_only_passed():
    output = """
    25 passed in 1.20s
    """

    (
        tests_run,
        passed,
        failed,
        skipped,
    ) = _parse_pytest_counts(output)

    assert tests_run == 25
    assert passed == 25
    assert failed is None
    assert skipped is None


def test_parse_pytest_counts_empty_output():
    (
        tests_run,
        passed,
        failed,
        skipped,
    ) = _parse_pytest_counts("")

    assert tests_run is None
    assert passed is None
    assert failed is None
    assert skipped is None


def make_test_result(
    passed=True,
    return_code=0,
    tests_run=10,
    tests_passed=10,
    tests_failed=0,
    tests_skipped=0,
):
    from pipeline.baseline import TestResult

    return TestResult(
        framework="pytest",
        command=["python", "-m", "pytest", "-q"],
        passed=passed,
        return_code=return_code,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        tests_skipped=tests_skipped,
        duration_seconds=1.0,
        stdout="",
        stderr="",
    )


def test_deterministic_identical_verdicts():
    first = make_test_result()
    second = make_test_result()

    assert _results_are_deterministic([first, second]) is True


def test_deterministic_ignores_runtime_difference():
    first = make_test_result()
    second = make_test_result()

    second.duration_seconds = 1.5

    assert _results_are_deterministic([first, second]) is True


def test_deterministic_detects_different_pass_fail():
    first = make_test_result()

    second = make_test_result(
        passed=False,
        return_code=1,
        tests_passed=9,
        tests_failed=1,
    )

    assert _results_are_deterministic([first, second]) is False


def test_deterministic_detects_different_test_count():
    first = make_test_result(
        tests_run=10,
    )

    second = make_test_result(
        tests_run=11,
        tests_passed=11,
    )

    assert _results_are_deterministic([first, second]) is False


def test_deterministic_requires_two_runs():
    first = make_test_result()

    assert _results_are_deterministic([first]) is None


def test_coverage_reuses_selected_pytest_target(tmp_path):
    package = tmp_path / "mypackage"
    package.mkdir()

    (package / "__init__.py").write_text('"""Example package."""\n')

    context = RepoContext(
        repo_path=str(tmp_path),
        test_frameworks=["pytest", "doctest"],
        coverage_tools=["coverage.py"],
    )

    command, framework = _select_test_command(
        tmp_path,
        context,
        "python",
    )

    assert framework == "pytest"

    assert command == [
        "python",
        "-m",
        "pytest",
        "-q",
        "--doctest-modules",
        str(package),
    ]


def test_parse_coverage_report():
    output = """
Name                             Stmts   Miss  Cover
----------------------------------------------------
glom\\core.py                      1232     13    99%
glom\\cli.py                        137     14    90%
----------------------------------------------------
TOTAL                             4430     70    98%
"""

    match = re.search(
        r"TOTAL\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)%",
        output,
    )

    assert match is not None

    total = int(match.group(1))
    missing = int(match.group(2))
    percent = float(match.group(3))
    covered = total - missing

    assert total == 4430
    assert missing == 70
    assert covered == 4360
    assert percent == 98.0
