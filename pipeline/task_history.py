from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class RegressionTest:
    """
    The content of a single test file as it existed in the *fixing*
    commit.

    This is the task-local oracle: the regression assertion(s) the
    original author added or changed to prove the bug was fixed. It is
    captured verbatim (via ``git show <commit>:<path>``) so it can later
    be materialized into a task's ``verifier/`` directory and run
    against both the buggy (parent) and fixed (commit) source states.
    """

    path: str
    content: str
    # pytest node-id suffixes (e.g. "test_foo" or "TestX::test_bar")
    # for test functions that are new in this commit, or whose source
    # body differs from the parent commit's version. Verification is
    # targeted at exactly these functions rather than the whole file,
    # so unrelated pre-existing breakage elsewhere in a large test file
    # can't pollute the fail-before/pass-after verdict.
    changed_functions: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoryChange:
    commit: str
    parent: Optional[str]
    subject: str
    files: tuple[str, ...]
    source_files: tuple[str, ...]
    test_files: tuple[str, ...]
    modules: tuple[str, ...]
    score: float
    rationale: str
    # Task-local regression-test oracle, captured from the fixing
    # commit. Defaults to an empty tuple for backward compatibility
    # with callers that construct HistoryChange directly.
    regression_tests: tuple[RegressionTest, ...] = ()
    # Flat "path::function" pytest node IDs for the specific test
    # function(s) that changed in the fixing commit, across all
    # regression_tests. Verification targets exactly these node IDs
    # instead of whole test files.
    regression_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoryMinerConfig:
    max_commits: int = 300
    max_candidates: int = 50


_BEHAVIORAL_TERMS = (
    "fix",
    "fixed",
    "fixes",
    "bug",
    "bugfix",
    "support",
    "handle",
    "handling",
    "correct",
    "corrected",
    "regression",
    "prevent",
    "resolve",
    "resolved",
    "issue",
    "error",
    "broken",
    "compat",
    "compatibility",
)

_TEST_MARKERS = (
    "test",
    "tests",
    "testing",
)

_SOURCE_SUFFIXES = (
    ".py",
)

# Top-level / packaging files that are never real implementation code,
# even though they end in ".py". These are build/packaging metadata,
# not application behavior.
_NON_IMPLEMENTATION_FILENAMES = (
    "setup.py",
    "conftest.py",
    "noxfile.py",
    "manage.py",
)

# Path segments that mark a file as documentation, tooling, or CI
# configuration rather than real implementation source, regardless of
# its suffix.
_NON_IMPLEMENTATION_PATH_MARKERS = (
    "docs/",
    "doc/",
    "documentation/",
    "scripts/",
    ".github/",
    ".circleci/",
    ".gitlab/",
    "ci/",
)


def _run_git(
    repo_path: Path,
    args: Sequence[str],
) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout


def _is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    name = Path(normalized).name

    return (
        "test" in name
        or "/test/" in normalized
        or "/tests/" in normalized
        or name.startswith("conftest.")
    )


def _is_source_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()

    if not normalized.endswith(_SOURCE_SUFFIXES):
        return False

    if _is_test_file(normalized):
        return False

    name = Path(normalized).name

    if name in _NON_IMPLEMENTATION_FILENAMES:
        return False

    if any(
        marker in normalized
        for marker in _NON_IMPLEMENTATION_PATH_MARKERS
    ):
        return False

    return True


def _behavioral_score(subject: str) -> float:
    text = subject.lower()

    matches = sum(
        1
        for term in _BEHAVIORAL_TERMS
        if re.search(
            rf"\b{re.escape(term)}\b",
            text,
        )
    )

    if matches == 0:
        return 0.0

    return min(
        1.0,
        0.45 + (matches * 0.10),
    )


def _module_from_path(path: str) -> Optional[str]:
    normalized = path.replace("\\", "/")

    if not normalized.endswith(".py"):
        return None

    if normalized.startswith("test/"):
        return None

    if normalized.startswith("tests/"):
        return None

    value = normalized[:-3]

    if value.endswith("/__init__"):
        value = value[:-9]

    value = value.replace("/", ".")

    if not value:
        return None

    return value


def _commit_records(
    repo_path: Path,
    max_commits: int,
) -> Iterable[tuple[str, str, Optional[str]]]:
    output = _run_git(
        repo_path,
        [
            "log",
            f"-n{max_commits}",
            "--format=%H%x00%P%x00%s%x00",
        ],
    )

    for record in output.split("\n"):
        record = record.strip("\x00")

        if not record:
            continue

        parts = record.split("\x00")

        if len(parts) < 3:
            continue

        commit = parts[0]
        parents = parts[1].split()
        subject = parts[2]

        parent = (
            parents[0]
            if parents
            else None
        )

        yield commit, subject, parent


def _extract_test_functions(source: str) -> dict[str, str]:
    """
    Map each test function's pytest node-id suffix (e.g. "test_foo",
    or "TestX::test_bar" for a method on a Test* class) to its exact
    source text, via AST parsing.

    Returns an empty mapping for unparsable source rather than raising,
    since a syntax error in one historical revision of a file should
    not crash mining -- it should just yield no pinpointed functions
    for that revision.
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}

    functions: dict[str, str] = {}

    def visit(
        body: Sequence[ast.stmt],
        prefix: str,
    ) -> None:
        for child in body:
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                if not child.name.startswith("test"):
                    continue

                node_id = (
                    child.name
                    if not prefix
                    else f"{prefix}::{child.name}"
                )

                segment = ast.get_source_segment(
                    source,
                    child,
                )

                if segment is not None:
                    functions[node_id] = segment

            elif isinstance(child, ast.ClassDef):
                if not child.name.startswith("Test"):
                    continue

                nested_prefix = (
                    child.name
                    if not prefix
                    else f"{prefix}::{child.name}"
                )

                visit(
                    child.body,
                    nested_prefix,
                )

    visit(tree.body, "")

    return functions


def _changed_test_node_ids(
    parent_content: Optional[str],
    fixing_content: str,
) -> tuple[str, ...]:
    """
    Return the pytest node-id suffixes of test functions that are new
    in fixing_content, or whose exact source differs from
    parent_content.

    A function present in the parent with identical source is *not*
    considered changed, even if the surrounding file changed --
    verification should target only what the fixing commit actually
    touched.
    """

    fixing_functions = _extract_test_functions(fixing_content)

    parent_functions = (
        _extract_test_functions(parent_content)
        if parent_content is not None
        else {}
    )

    changed = tuple(
        sorted(
            name
            for name, source in fixing_functions.items()
            if parent_functions.get(name) != source
        )
    )

    return changed


def _show_file_at_commit(
    repo_path: Path,
    commit: str,
    path: str,
) -> Optional[str]:
    """
    Return the exact content of ``path`` as it existed at ``commit``,
    or None when the file cannot be read at that revision (for example
    if it was deleted, renamed, or is otherwise unavailable).

    This is what lets us recover the *fixing* version of a regression
    test, independent of whatever version happens to be present in the
    parent commit's working tree.
    """

    try:
        return _run_git(
            repo_path,
            [
                "show",
                f"{commit}:{path}",
            ],
        )
    except subprocess.CalledProcessError:
        return None


def _extract_regression_tests(
    repo_path: Path,
    commit: str,
    parent: Optional[str],
    test_files: Sequence[str],
) -> tuple[RegressionTest, ...]:
    """
    Capture the fixing-commit content of every changed test file, plus
    the specific test function(s) within it that are new or changed
    relative to the parent commit.

    This becomes the task-local verification oracle: it is the specific
    regression assertion(s) the fix introduced, not the whole test
    suite, and not whatever stale version of the file happens to sit in
    the parent commit. Scoping to individual functions (rather than the
    whole file) also means unrelated, pre-existing breakage elsewhere
    in a large test file can't pollute the fail-before/pass-after
    verdict.
    """

    tests = []

    for path in test_files:
        content = _show_file_at_commit(
            repo_path,
            commit,
            path,
        )

        if content is None:
            continue

        parent_content = (
            _show_file_at_commit(
                repo_path,
                parent,
                path,
            )
            if parent is not None
            else None
        )

        changed_functions = _changed_test_node_ids(
            parent_content,
            content,
        )

        tests.append(
            RegressionTest(
                path=path,
                content=content,
                changed_functions=changed_functions,
            )
        )

    return tuple(
        sorted(
            tests,
            key=lambda test: test.path,
        )
    )


def _changed_files(
    repo_path: Path,
    commit: str,
) -> tuple[str, ...]:
    output = _run_git(
        repo_path,
        [
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "--root",
            commit,
        ],
    )

    return tuple(
        sorted(
            {
                line.strip()
                for line in output.splitlines()
                if line.strip()
            }
        )
    )


def mine_history_candidates(
    repo_path: str | Path,
    config: Optional[HistoryMinerConfig] = None,
) -> list[HistoryChange]:
    """
    Mine behavioral Git commits.

    A commit is eligible only when:

      1. Its message contains behavioral-change language.
      2. At least one real Python implementation file changed
         (excluding setup.py, conftest.py, docs, scripts, and CI
         configuration).
      3. At least one test file changed.

    README-only, packaging-only, and CI/documentation-only commits
    therefore never become History-derived candidates.
    """

    config = config or HistoryMinerConfig()
    root = Path(repo_path).resolve()

    if not (root / ".git").exists():
        return []

    candidates: list[HistoryChange] = []

    for commit, subject, parent in _commit_records(
        root,
        config.max_commits,
    ):
        behavioral = _behavioral_score(subject)

        if behavioral <= 0:
            continue

        files = _changed_files(
            root,
            commit,
        )

        source_files = tuple(
            sorted(
                path
                for path in files
                if _is_source_file(path)
            )
        )

        test_files = tuple(
            sorted(
                path
                for path in files
                if _is_test_file(path)
            )
        )

        if not source_files or not test_files:
            continue

        regression_tests = _extract_regression_tests(
            root,
            commit,
            parent,
            test_files,
        )

        # Without an extractable, fixing-commit version of at least one
        # test file, we cannot build a task-local oracle. Fail closed
        # rather than falling back to the whole-suite-at-parent
        # comparison that silently accepts stale, already-passing
        # tests.
        if not regression_tests:
            continue

        regression_node_ids = tuple(
            sorted(
                f"{test.path}::{function_name}"
                for test in regression_tests
                for function_name in test.changed_functions
            )
        )

        # Without a pinpointed test function, verification would fall
        # back to whole-file runs, which can be polluted by unrelated
        # pre-existing breakage elsewhere in the file. Fail closed
        # rather than accept an imprecise oracle.
        if not regression_node_ids:
            continue

        modules = tuple(
            sorted(
                {
                    module
                    for module in (
                        _module_from_path(path)
                        for path in source_files
                    )
                    if module
                }
            )
        )

        # Additional evidence increases confidence.
        score = behavioral

        if len(source_files) > 1:
            score += 0.10

        if len(test_files) > 1:
            score += 0.10

        if modules:
            score += 0.10

        score = min(
            1.0,
            round(score, 3),
        )

        rationale = (
            "Behavioral commit modifies both implementation and tests."
        )

        candidates.append(
            HistoryChange(
                commit=commit,
                parent=parent,
                subject=subject,
                files=files,
                source_files=source_files,
                test_files=test_files,
                modules=modules,
                score=score,
                rationale=rationale,
                regression_tests=regression_tests,
                regression_node_ids=regression_node_ids,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            -candidate.score,
            candidate.commit,
        )
    )

    return candidates[
        : config.max_candidates
    ]


def mine_history_candidates_from_git(
    repo_path: str | Path,
    config: Optional[HistoryMinerConfig] = None,
) -> list[HistoryChange]:
    return mine_history_candidates(
        repo_path,
        config=config,
    )