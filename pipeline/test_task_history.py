from __future__ import annotations
import sys
import subprocess
from pathlib import Path

from pipeline.task_history import (
    HistoryMinerConfig,
    mine_history_candidates,
)
from pipeline.task_synthesis import synthesize_history_task
from pipeline.task_verifier import TaskVerifier


def git(
    repo: Path,
    *args: str,
) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    return result.stdout


def make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    git(
        repo,
        "init",
    )

    git(
        repo,
        "config",
        "user.email",
        "benchmark@example.com",
    )

    git(
        repo,
        "config",
        "user.name",
        "Benchmark",
    )

    return repo


def commit_all(
    repo: Path,
    message: str,
) -> str:
    git(
        repo,
        "add",
        ".",
    )

    git(
        repo,
        "commit",
        "-m",
        message,
    )

    return git(
        repo,
        "rev-parse",
        "HEAD",
    ).strip()


def test_behavioral_commit_with_source_and_test_is_detected(
    tmp_path,
):
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert calculate(1) == 1\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix calculation bug",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate.subject == (
        "fix calculation bug"
    )

    assert candidate.source_files == (
        "module.py",
    )

    assert candidate.test_files == (
        "test_module.py",
    )

    assert candidate.score > 0


def test_readme_only_commit_is_ignored(
    tmp_path,
):
    repo = make_git_repo(tmp_path)

    (repo / "README.md").write_text(
        "# Example\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix documentation wording",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert candidates == []


def test_source_only_commit_is_ignored(
    tmp_path,
):
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x + 1\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix calculation",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert candidates == []


def test_test_only_commit_is_ignored(
    tmp_path,
):
    repo = make_git_repo(tmp_path)

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix test coverage",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert candidates == []


def test_non_behavioral_source_and_test_commit_is_ignored(
    tmp_path,
):
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_value():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "refactor internal naming",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert candidates == []


def test_multiple_behavioral_commits_are_ranked_deterministically(
    tmp_path,
):
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix calculation bug",
    )

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x * 2\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert calculate(2) == 4\n",
        encoding="utf-8",
    )

    second = commit_all(
        repo,
        "support calculation regression fix",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert len(candidates) == 2

    assert candidates[0].commit == second

    scores = [
        candidate.score
        for candidate in candidates
    ]

    assert scores == sorted(
        scores,
        reverse=True,
    )


def test_regression_test_is_extracted_from_fixing_commit(
    tmp_path,
):
    """
    The candidate's regression_tests must carry the *fixing* commit's
    content of the changed test file, not the parent's (pre-fix)
    version. This is the task-local oracle the rest of the pipeline
    relies on.
    """
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    parent_test_content = (
        "def test_calculate():\n"
        "    assert calculate(1) == 1\n"
    )

    (repo / "test_module.py").write_text(
        parent_test_content,
        encoding="utf-8",
    )

    commit_all(
        repo,
        "initial implementation",
    )

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    if x < 0:\n"
        "        return 0\n"
        "    return x\n",
        encoding="utf-8",
    )

    fixing_test_content = (
        "def test_calculate():\n"
        "    assert calculate(1) == 1\n"
        "    assert calculate(-1) == 0\n"
    )

    (repo / "test_module.py").write_text(
        fixing_test_content,
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix negative regression",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert len(candidates) == 1

    candidate = candidates[0]

    assert len(candidate.regression_tests) == 1

    regression_test = candidate.regression_tests[0]

    assert regression_test.path == "test_module.py"

    # It must be the fixing-commit content ...
    assert regression_test.content == fixing_test_content

    # ... and specifically NOT the stale parent content, which is
    # exactly the bug this feature fixes: the parent's own version of
    # the test file has no regression assertion, so running it as-is
    # would wrongly appear to pass against the buggy source.
    assert regression_test.content != parent_test_content


def test_commit_without_extractable_test_content_is_ignored(
    tmp_path,
):
    """
    If a changed 'test' file can't actually be read at the fixing
    commit (for example it was renamed away in a way git can't resolve
    for our purposes), the commit must not become a candidate at all --
    fail closed rather than proceeding without an oracle.
    """
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "initial implementation",
    )

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x + 1\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix calculation bug",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert len(candidates) == 1
    assert len(candidates[0].regression_tests) == 1


def test_end_to_end_mining_synthesis_and_oracle_verification(
    tmp_path,
):
    """
    Full reproduction of the reported pipeline bug and its fix:

      1. Mine a real behavioral commit.
      2. Synthesize input/ (parent) + solution/ (fix) + verifier/
         (regression-test oracle materialized from the fixing commit).
      3. Verify using the task-local oracle -> FAIL / PASS / PASS,
         exactly as the intended fix describes, even though the
         parent's OWN version of the test file would (wrongly) pass.
    """
    repo = make_git_repo(tmp_path)

    (repo / "calc.py").write_text(
        "def calculate(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    (repo / "test_calc.py").write_text(
        "from calc import calculate\n\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "initial implementation",
    )

    (repo / "calc.py").write_text(
        "def calculate(value):\n"
        "    if value < 0:\n"
        "        return 0\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    (repo / "test_calc.py").write_text(
        "from calc import calculate\n\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n"
        "    assert calculate(-5) == 0\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix negative values",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert len(candidates) == 1

    candidate = candidates[0]

    task_dir = tmp_path / "task"

    synthesis = synthesize_history_task(
        repo,
        candidate,
        task_dir,
    )

    def runner(command, **kwargs):
        script = (
            "import sys; sys.path.insert(0, '.'); "
            "import test_calc as m; m.test_calculate(); "
            "print('ok')"
        )

        return subprocess.run(
            [
                sys.executable,
                "-c",
                script,
            ],
            cwd=kwargs["cwd"],
            capture_output=True,
            text=True,
            timeout=kwargs.get("timeout"),
        )

    verifier = TaskVerifier(
        runner=runner,
    )

    result = verifier.verify(
        synthesis.input_dir,
        synthesis.solution_dir,
        ["python3", "-m", "pytest", "-q", "test_calc.py"],
        task_dir / "evidence",
        task_id="history-e2e-001",
        oracle_dir=synthesis.verifier_dir,
    )

    assert result.validation.fail_before_verified is True
    assert result.validation.pass_after_verified is True
    assert result.validation.deterministic_verified is True
    assert result.accepted is True


def test_regression_node_ids_pinpoint_only_the_changed_function(
    tmp_path,
):
    """
    Reproduces the log-reported failure mode directly: a test file with
    multiple test functions, where ONE is unrelated and permanently
    broken (e.g. a Python 2/3 compatibility issue unrelated to the
    fix), and only ONE function actually encodes the regression the
    commit fixes.

    regression_node_ids must contain only the changed function --
    never the unrelated, permanently-broken one -- so verification
    later targets exactly the right pytest node ID instead of the
    whole file.
    """
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_unrelated_broken():\n"
        "    raise NameError('name unicode is not defined')\n"
        "\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 1\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "initial implementation",
    )

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    if x < 0:\n"
        "        return 0\n"
        "    return x\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_unrelated_broken():\n"
        "    raise NameError('name unicode is not defined')\n"
        "\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 1\n"
        "    assert calculate(-1) == 0\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix negative regression",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate.regression_node_ids == (
        "test_module.py::test_calculate",
    )

    # The permanently-broken, unrelated function must never be
    # targeted -- it would pollute both fail-before and pass-after
    # with an unrelated failure.
    assert (
        "test_module.py::test_unrelated_broken"
        not in candidate.regression_node_ids
    )


def test_commit_with_no_pinpointed_function_is_ignored(
    tmp_path,
):
    """
    If the fixing commit's test file content is identical to the
    parent's (byte for byte the same test functions, e.g. only
    whitespace/comment churn outside any function body), there is no
    function-level regression to target. The commit must not become a
    candidate -- fail closed rather than fall back to a whole-file run.
    """
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert calculate(1) == 1\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "initial implementation",
    )

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x + 1\n",
        encoding="utf-8",
    )

    # Test file content is untouched -- only a comment is added
    # above the (identical) test function, so the function body
    # itself is unchanged.
    (repo / "test_module.py").write_text(
        "# fix calculation bug\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 1\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix calculation bug",
    )

    candidates = mine_history_candidates(
        repo,
    )

    assert candidates == []


def test_candidate_output_is_deterministic(
    tmp_path,
):
    repo = make_git_repo(tmp_path)

    (repo / "module.py").write_text(
        "def calculate(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    (repo / "test_module.py").write_text(
        "def test_calculate():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    commit_all(
        repo,
        "fix calculation bug",
    )

    first = mine_history_candidates(
        repo,
    )

    second = mine_history_candidates(
        repo,
    )

    assert first == second