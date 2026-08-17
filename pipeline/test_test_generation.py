from pipeline.baseline import (
    BaselineResult,
    CoverageResult,
)
from pipeline.discover import RepoContext

from pipeline.test_generation import (
    CoverageGap,
    TestTarget as GeneratedTestTarget,
    analyze_test_gaps,
    identify_test_targets,
    _find_enclosing_function,
)


def make_context(files):
    return RepoContext(
        repo_path=".",
        discovered_files=files,
        test_frameworks=["pytest"],
        coverage_tools=["coverage.py"],
    )


def make_baseline(coverage_output):
    coverage = CoverageResult(
        tool="coverage.py",
        command=["coverage", "report", "--show-missing"],
        available=True,
        passed=True,
        total_statements=100,
        covered_statements=95,
        coverage_percent=95.0,
        missing_statements=5,
        stdout=coverage_output,
        stderr="",
    )

    return BaselineResult(
        install=None,
        test_runs=[],
        coverage=coverage,
        deterministic=True,
        warnings=[],
        overall_passed=True,
    )


def test_analyze_test_gaps_parses_missing_lines(tmp_path):
    source = tmp_path / "example.py"

    source.write_text(
        """
def hello():
    return "hello"


def calculate():
    value = 10
    return value
""".strip()
    )

    coverage_output = """
Name                    Stmts   Miss  Cover   Missing
-----------------------------------------------------
example.py                 5      1    80%   7
-----------------------------------------------------
TOTAL                      5      1    80%
"""

    context = make_context(
        [
            "example.py",
            "test_example.py",
        ]
    )

    baseline = make_baseline(coverage_output)

    gaps = analyze_test_gaps(
        tmp_path,
        context,
        baseline,
    )

    assert len(gaps) == 1

    gap = gaps[0]

    assert isinstance(
        gap,
        CoverageGap,
    )

    assert gap.source_file == "example.py"
    assert gap.line_number == 7
    assert gap.function == "calculate"
    assert gap.category == "runtime"
    assert gap.priority == "medium"


def test_analyze_test_gaps_supports_ranges(tmp_path):
    source = tmp_path / "example.py"

    source.write_text(
        """
def calculate():
    a = 1
    b = 2
    c = 3
    return a + b + c
""".strip()
    )

    coverage_output = """
Name                    Stmts   Miss  Cover   Missing
-----------------------------------------------------
example.py                 5      2    60%   3-4
-----------------------------------------------------
TOTAL                      5      2    60%
"""

    context = make_context(["example.py"])

    baseline = make_baseline(coverage_output)

    gaps = analyze_test_gaps(
        tmp_path,
        context,
        baseline,
    )

    assert [gap.line_number for gap in gaps] == [3, 4]

    assert all(gap.function == "calculate" for gap in gaps)


def test_analyze_test_gaps_returns_empty_without_coverage():
    context = make_context([])

    baseline = BaselineResult(
        install=None,
        test_runs=[],
        coverage=None,
        deterministic=True,
        warnings=[],
        overall_passed=True,
    )

    gaps = analyze_test_gaps(
        ".",
        context,
        baseline,
    )

    assert gaps == []


def test_analyze_test_gaps_returns_empty_when_coverage_failed():
    coverage = CoverageResult(
        tool="coverage.py",
        command=["coverage", "report"],
        available=True,
        passed=False,
        total_statements=None,
        covered_statements=None,
        coverage_percent=None,
        missing_statements=None,
        stdout="",
        stderr="coverage failed",
    )

    baseline = BaselineResult(
        install=None,
        test_runs=[],
        coverage=coverage,
        deterministic=True,
        warnings=[],
        overall_passed=False,
    )

    gaps = analyze_test_gaps(
        ".",
        make_context([]),
        baseline,
    )

    assert gaps == []


def test_identify_runtime_target(tmp_path):
    source = tmp_path / "calculator.py"

    source.write_text(
        """
def calculate():
    value = 10
    return value
""".strip()
    )

    context = make_context(
        [
            "calculator.py",
            "test_calculator.py",
        ]
    )

    gaps = [
        CoverageGap(
            source_file="calculator.py",
            line_number=3,
            function="calculate",
            category="runtime",
            reason="statement is not covered",
            priority="medium",
        )
    ]

    targets = identify_test_targets(
        tmp_path,
        context,
        gaps,
    )

    assert len(targets) == 1

    target = targets[0]

    assert isinstance(
        target,
        GeneratedTestTarget,
    )

    assert target.source_file == "calculator.py"
    assert target.function == "calculate"
    assert target.category == "runtime"
    assert target.priority == "medium"

    assert target.suggested_test_file == "test_calculator.py"

    assert "calculate" in target.behavior


def test_debug_gap_is_low_priority(tmp_path):
    source = tmp_path / "cli.py"

    source.write_text(
        """
def run(debug=False):
    if debug:
        print("debug")
    return 0
""".strip()
    )

    context = make_context(
        [
            "cli.py",
            "test_cli.py",
        ]
    )

    gaps = analyze_test_gaps(
        tmp_path,
        context,
        make_baseline(
            """
Name                 Stmts   Miss  Cover   Missing
--------------------------------------------------
cli.py                   4      1    75%   3
--------------------------------------------------
TOTAL                    4      1    75%
"""
        ),
    )

    assert len(gaps) == 1
    assert gaps[0].category == "debug"
    assert gaps[0].priority == "low"


def test_error_gap_is_high_priority(tmp_path):
    source = tmp_path / "parser.py"

    source.write_text(
        """
def parse(value):
    try:
        return int(value)
    except ValueError:
        raise ValueError("invalid")
""".strip()
    )

    context = make_context(
        [
            "parser.py",
            "test_parser.py",
        ]
    )

    gaps = analyze_test_gaps(
        tmp_path,
        context,
        make_baseline(
            """
Name                 Stmts   Miss  Cover   Missing
--------------------------------------------------
parser.py                5      1    80%   5
--------------------------------------------------
TOTAL                    5      1    80%
"""
        ),
    )

    assert len(gaps) == 1
    assert gaps[0].category == "error"
    assert gaps[0].priority == "high"


def test_test_files_are_not_turned_into_targets(tmp_path):
    source = tmp_path / "test_example.py"

    source.write_text(
        """
def test_something():
    assert True
""".strip()
    )

    context = make_context(["test_example.py"])

    gaps = [
        CoverageGap(
            source_file="test_example.py",
            line_number=2,
            function="test_something",
            category="test",
            reason="statement is not covered",
            priority="low",
        )
    ]

    targets = identify_test_targets(
        tmp_path,
        context,
        gaps,
    )

    assert targets == []


def test_generated_build_paths_are_not_test_targets(tmp_path):
    build_test = tmp_path / "build" / "lib" / "mypackage" / "test" / "test_core.py"
    build_test.parent.mkdir(parents=True)
    build_test.write_text("")

    source = tmp_path / "mypackage" / "core.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def foo():\n    return 1\n")

    context = RepoContext(
        repo_path=str(tmp_path),
        test_frameworks=["pytest"],
    )

    gaps = [
        CoverageGap(
            source_file=str(source),
            line_number=2,
            function="foo",
            category="runtime",
            reason="uncovered",
            priority="medium",
        )
    ]

    targets = identify_test_targets(
        tmp_path,
        context,
        gaps,
    )

    assert all(
        target.suggested_test_file is None or "build" not in target.suggested_test_file
        for target in targets
    )


def test_multiple_gaps_in_same_function_create_one_target(tmp_path):
    source = tmp_path / "mypackage" / "core.py"
    source.parent.mkdir(parents=True)
    source.write_text("def foo():\n    x = 1\n    y = 2\n    return x + y\n")

    context = RepoContext(
        repo_path=str(tmp_path),
        test_frameworks=["pytest"],
    )

    gaps = [
        CoverageGap(
            source_file=str(source),
            line_number=2,
            function="foo",
            category="runtime",
            reason="uncovered",
            priority="medium",
        ),
        CoverageGap(
            source_file=str(source),
            line_number=3,
            function="foo",
            category="runtime",
            reason="uncovered",
            priority="medium",
        ),
    ]

    targets = identify_test_targets(
        tmp_path,
        context,
        gaps,
    )

    assert len(targets) == 1
    assert targets[0].function == "foo"


def test_enclosing_function_is_detected(tmp_path):
    source = tmp_path / "core.py"

    source.write_text(
        "class Example:\n"
        "    def method(self):\n"
        "        value = 42\n"
        "        return value\n"
    )

    assert (
        _find_enclosing_function(
            str(source),
            3,
        )
        == "method"
    )
