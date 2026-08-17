import ast
import re

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from collections import defaultdict
from pipeline.baseline import BaselineResult
from pipeline.discover import RepoContext


@dataclass
class CoverageGap:
    source_file: str
    line_number: int

    function: Optional[str]
    category: str

    reason: str
    priority: str


@dataclass
class TestTarget:
    source_file: str
    function: Optional[str]

    behavior: str
    category: str
    priority: str

    suggested_test_file: Optional[str]
    rationale: str


@dataclass
class TestGenerationResult:
    candidates: list[TestTarget]

    generated_files: list[str]
    generated_tests: int

    accepted_tests: int
    rejected_tests: int

    coverage_before: Optional[float]
    coverage_after: Optional[float]
    coverage_improved: Optional[bool]

    baseline_preserved: bool

    passed: bool
    warnings: list[str]


# ---------------------------------------------------------------------------
# Coverage parsing
# ---------------------------------------------------------------------------


_COVERAGE_ROW_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<stmts>\d+)\s+"
    r"(?P<miss>\d+)\s+"
    r"(?P<cover>\d+)%"
    r"(?:\s+(?P<missing>[\d,\-]+))?$"
)

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


def _is_generated_or_environment_path(path):
    parts = Path(path).parts

    return any(part in IGNORED_PATH_PARTS for part in parts)


def _parse_missing_lines(value):
    """
    Parse coverage.py --show-missing output.

    Examples:

        10,12,15
        10-12,18
        57
    """
    if not value:
        return []

    lines = []

    for part in value.split(","):
        part = part.strip()

        if not part:
            continue

        if "-" in part:
            start, end = part.split("-", 1)
            lines.extend(range(int(start), int(end) + 1))
        else:
            lines.append(int(part))

    return lines


def _coverage_text(baseline):
    """
    Extract the textual coverage report from BaselineResult.

    CoverageResult.stdout currently contains the coverage command output.
    """
    if baseline.coverage is None:
        return ""

    return baseline.coverage.stdout or ""


def _parse_coverage_gaps(baseline):
    """
    Return (source_file, line_number) pairs from a coverage.py report.
    """
    text = _coverage_text(baseline)

    gaps = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("Name "):
            continue

        if line.startswith("-" * 3):
            continue

        match = _COVERAGE_ROW_RE.match(line)

        if not match:
            continue

        source_file = match.group("name").strip()
        missing = match.group("missing")

        if not missing:
            continue

        for line_number in _parse_missing_lines(missing):
            gaps.append((source_file, line_number))

    return gaps


# ---------------------------------------------------------------------------
# Source analysis
# ---------------------------------------------------------------------------


def _read_source(repo_path, source_file):
    """
    Read a repository-relative source file safely.
    """
    path = Path(repo_path) / source_file

    if not path.exists() or not path.is_file():
        return None

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _find_enclosing_function(source_file, line_number):
    path = Path(source_file)

    if not path.exists():
        return None

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None

    candidates = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        end_line = getattr(
            node,
            "end_lineno",
            node.lineno,
        )

        if node.lineno <= line_number <= end_line:
            candidates.append(node)

    if not candidates:
        return None

    # The smallest enclosing function is the most specific.
    node = min(
        candidates,
        key=lambda item: (getattr(item, "end_lineno", item.lineno) - item.lineno),
    )

    return node.name

    # The smallest containing function is the most specific.
    candidates.sort(
        key=lambda node: (getattr(node, "end_lineno", node.lineno) - node.lineno)
    )

    return candidates[0].name


# ---------------------------------------------------------------------------
# Gap classification
# ---------------------------------------------------------------------------


def _classify_gap(
    source_file,
    function,
    source,
    line_number,
):
    """
    Classify a coverage gap conservatively.

    This is intentionally heuristic in v1. It should never claim
    that an uncovered line definitely requires a generated test.
    """
    filename = source_file.lower()

    if function:
        function_name = function.lower()
    else:
        function_name = ""

    surrounding = ""

    if source:
        lines = source.splitlines()

        start = max(
            0,
            line_number - 4,
        )
        end = min(
            len(lines),
            line_number + 3,
        )

        surrounding = "\n".join(lines[start:end]).lower()

    debug_terms = (
        "debug",
        "inspect",
        "breakpoint",
        "pdb",
        "post_mortem",
    )

    if any(term in function_name for term in debug_terms) or any(
        term in surrounding for term in debug_terms
    ):
        return "debug", "low"

    error_terms = (
        "except",
        "raise",
    )

    if any(term in surrounding for term in error_terms):
        return "error", "high"

    if filename.startswith("test"):
        return "test", "low"

    if "/test/" in filename or "\\test\\" in filename:
        return "test", "low"

    if filename.endswith(".py"):
        return "runtime", "medium"

    return "unknown", "low"


# ---------------------------------------------------------------------------
# Public analysis API
# ---------------------------------------------------------------------------


def analyze_test_gaps(
    repo_path,
    context: RepoContext,
    baseline: BaselineResult,
):
    """
    Convert baseline coverage information into CoverageGap objects.

    This function performs analysis only.

    It does not modify the repository.
    """
    if baseline is None:
        return []

    if baseline.coverage is None:
        return []

    if not baseline.coverage.available:
        return []

    if not baseline.coverage.passed:
        return []

    raw_gaps = _parse_coverage_gaps(baseline)

    gaps = []

    for source_file, line_number in raw_gaps:
        source = _read_source(
            repo_path,
            source_file,
        )

        full_source_path = Path(repo_path) / source_file
        function = _find_enclosing_function(
            str(full_source_path),
            line_number,
        )

        category, priority = _classify_gap(
            source_file,
            function,
            source,
            line_number,
        )

        gaps.append(
            CoverageGap(
                source_file=source_file,
                line_number=line_number,
                function=function,
                category=category,
                reason=("statement is not covered by the baseline test run"),
                priority=priority,
            )
        )

    return gaps


# ---------------------------------------------------------------------------
# Test target identification
# ---------------------------------------------------------------------------


def _candidate_test_files(
    repo_path,
    context,
):
    """
    Discover existing test files.

    We deliberately use the repository's discovered files rather than
    assuming a particular test directory such as tests/ or test/.
    """
    result = []

    for relative_path in context.discovered_files:
        normalized = relative_path.replace(
            "\\",
            "/",
        )
        if _is_generated_or_environment_path(normalized):
            continue

        name = Path(normalized).name.lower()

        if not name.endswith(
            (
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".jsx",
            )
        ):
            continue

        if (
            name.startswith("test_")
            or name.startswith("test.")
            or name.endswith("_test.py")
            or "/test/" in normalized
            or "/tests/" in normalized
        ):
            result.append(normalized)

    return sorted(set(result))


def _find_related_test_file(
    source_file,
    test_files,
):
    """
    Prefer an existing test file related to the source module.

    This is intentionally conservative.
    """
    source_name = Path(source_file).stem.lower()

    if source_name.startswith("test_"):
        return source_file

    for test_file in test_files:
        test_name = Path(test_file).stem.lower()

        if test_name == f"test_{source_name}" or test_name == f"{source_name}_test":
            return test_file

    return test_files[0] if test_files else None


def _behavior_description(
    gap,
):
    if gap.category == "error":
        return f"exercise error handling in {gap.function or gap.source_file}"

    if gap.category == "debug":
        return (
            f"exercise debug/inspection behavior in {gap.function or gap.source_file}"
        )

    if gap.category == "runtime":
        return (
            f"exercise uncovered runtime behavior in {gap.function or gap.source_file}"
        )

    if gap.category == "optional":
        return f"exercise optional behavior in {gap.function or gap.source_file}"

    return f"exercise uncovered behavior in {gap.function or gap.source_file}"


def identify_test_targets(
    repo_path,
    context: RepoContext,
    gaps,
):
    """
    Convert CoverageGap objects into behavioral TestTarget objects.

    This function does not generate or modify tests.
    """
    test_files = _candidate_test_files(
        repo_path,
        context,
    )

    targets = []

    grouped = defaultdict(list)

    for gap in gaps:
        if gap.category == "test":
            continue

        if _is_generated_or_environment_path(gap.source_file):
            continue

        key = (
            gap.source_file,
            gap.function,
            gap.category,
        )
        grouped[key].append(gap)

    for (source_file, function, category), group in grouped.items():
        # Get the first gap chronologically in the file to use for the rationale
        first_gap = min(group, key=lambda g: g.line_number)

        suggested_test_file = _find_related_test_file(
            source_file,
            test_files,
        )

        behavior = _behavior_description(first_gap)

        rationale = (
            f"Coverage identified uncovered statements starting at "
            f"{source_file}:{first_gap.line_number}. "
        )

        if function:
            rationale += f"The statements belong to {function}."

        if suggested_test_file:
            rationale += f" An existing related test location is {suggested_test_file}."
        else:
            rationale += " No existing related test file was identified."

        targets.append(
            TestTarget(
                source_file=source_file,
                function=function,
                behavior=behavior,
                category=category,
                priority=first_gap.priority,
                suggested_test_file=suggested_test_file,
                rationale=rationale,
            )
        )

    return targets
