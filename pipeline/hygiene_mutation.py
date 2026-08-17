import os
import shutil
import subprocess
import tempfile
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class HygieneChange:
    tool: str
    action: str
    command: list[str]

    files: list[str]

    reason: str
    confidence: str

    mutates_files: bool = True


@dataclass
class HygieneExecution:
    change: HygieneChange

    command: list[str]

    return_code: int

    stdout: str
    stderr: str

    duration_seconds: float

    timed_out: bool

    changed_files: list[str]

    applied: bool


@dataclass
class HygieneValidation:
    baseline_passed: bool
    post_change_passed: bool

    baseline_deterministic: bool
    post_change_deterministic: bool

    tests_before: Optional[int]
    tests_after: Optional[int]

    passed_before: Optional[int]
    passed_after: Optional[int]

    failed_before: Optional[int]
    failed_after: Optional[int]

    coverage_before: Optional[float]
    coverage_after: Optional[float]

    regression_detected: bool

    validation_passed: bool

    reasons: list[str] = field(default_factory=list)


@dataclass
class HygieneResult:
    change: HygieneChange

    execution: HygieneExecution

    validation: HygieneValidation

    accepted: bool

    rolled_back: bool

    rollback_successful: Optional[bool]

    original_repo_untouched: bool

    warnings: list[str] = field(default_factory=list)


@dataclass
class _FileSnapshot:
    files: dict[str, bytes]


def _snapshot_repository(repo_path):
    """
    Capture regular repository files.

    Generated/cache directories are intentionally ignored because
    the hygiene mutation should only reason about source/config changes.
    """

    repo_path = Path(repo_path)

    ignored_parts = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
    }

    snapshot = {}

    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(repo_path)

        if any(
            part in ignored_parts
            or part.endswith(".egg-info")
            for part in relative.parts
        ):
            continue

        try:
            snapshot[str(relative)] = path.read_bytes()
        except OSError:
            continue


    return _FileSnapshot(files=snapshot)


def _changed_files(before, after):
    """
    Return files that were created, deleted, or modified.
    """

    before_files = before.files
    after_files = after.files

    paths = sorted(set(before_files) | set(after_files))

    changed = []

    for path in paths:
        if before_files.get(path) != after_files.get(path):
            changed.append(path)

    return changed


def _copy_repository(source, destination):
    """
    Copy a repository while excluding generated/runtime directories.
    """

    source = Path(source)
    destination = Path(destination)

    # ".git" is excluded from the copy itself (we don't want a full
    # history copy in every isolated hygiene workspace), but symlinks
    # that git stores as mode 120000 entries (e.g. tests/certs/valid/ca
    # on Windows checkouts with core.symlinks=false) still need to be
    # correctly materialized in `destination`. _restore_git_symlinks()
    # handles that separately by reading git metadata from `source`
    # (which still has .git) below, so downstream code (e.g.
    # run_baseline on this workspace) sees real files/dirs instead of
    # git's raw placeholder text and doesn't report false regressions.
    ignored_names = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
    }

    # Use a custom ignore callable or append pattern matching to handle suffixes like .egg-info
    def _ignore_patterns(dir, files):
        ignored = set()
        for f in files:
            if f in ignored_names or f.endswith(".egg-info"):
                ignored.add(f)
        return ignored

    shutil.copytree(
        source,
        destination,
        ignore=_ignore_patterns,
    )

    _restore_git_symlinks(source, destination)


def _restore_git_symlinks(source, destination):
    """
    Restore git-stored symlinks (mode 120000 index entries) into a
    destination copy that does not itself contain .git.

    This mirrors pipeline.baseline._prepare_repository_workspace's
    symlink restoration, but reads git metadata from `source` (which
    still has .git) and writes the materialized symlinks into
    `destination` (which intentionally does not carry .git along, to
    avoid copying full repository history into every isolated hygiene
    workspace). Without this, a repository checked out on a platform
    where core.symlinks is disabled (common on Windows) leaves plain
    placeholder text files in `destination` instead of working
    symlinks/directories, which can make an unrelated test fail and be
    misread as a regression caused by the hygiene change itself.
    """

    source = Path(source)
    destination = Path(destination)

    result = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "ls-files",
            "-s",
            "-z",
        ],
        capture_output=True,
        text=False,
        check=False,
        stdin=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        return

    entries = result.stdout.split(b"\0")

    for raw_entry in entries:
        if not raw_entry:
            continue

        try:
            metadata, relative_bytes = raw_entry.split(b"\t", 1)
            mode, object_id, _stage = metadata.split()

            if mode != b"120000":
                continue

            relative_path = Path(
                os.fsdecode(relative_bytes)
            )

            destination_path = destination / relative_path

            target_result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "cat-file",
                    "-p",
                    object_id.decode("ascii"),
                ],
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )

            if target_result.returncode != 0:
                continue

            target = target_result.stdout.rstrip("\r\n")

            if not target:
                continue

            # Resolve the symlink target relative to the symlink's
            # parent directory inside the destination copy.
            target_path = (
                destination_path.parent / target
            ).resolve()

            try:
                target_path.relative_to(destination)
            except ValueError:
                # Never allow a repository symlink to materialize
                # content outside the isolated destination copy.
                continue

            # Remove the placeholder (a regular file containing the
            # symlink target, or a stray directory) before replacing it.
            if destination_path.exists() or destination_path.is_symlink():
                if destination_path.is_dir() and not destination_path.is_symlink():
                    shutil.rmtree(destination_path)
                else:
                    destination_path.unlink()

            destination_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            try:
                os.symlink(
                    target,
                    destination_path,
                    target_is_directory=target_path.is_dir(),
                )

            except (OSError, NotImplementedError):
                # Fall back to materializing the target when the host
                # platform does not permit symlink creation.
                if target_path.is_dir():
                    shutil.copytree(
                        target_path,
                        destination_path,
                        dirs_exist_ok=True,
                    )

                elif target_path.is_file():
                    shutil.copy2(
                        target_path,
                        destination_path,
                    )

        except (ValueError, UnicodeError, OSError):
            continue


def _run_mutation_command(
    change,
    workspace,
    timeout=600,
):
    """
    Execute exactly one hygiene command.
    """

    start = time.monotonic()

    try:
        result = subprocess.run(
            change.command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        duration = time.monotonic() - start

        return HygieneExecution(
            change=change,
            command=list(change.command),
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            timed_out=False,
            changed_files=[],
            applied=result.returncode == 0,
        )

    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start

        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(stderr, bytes):
            stderr = stderr.decode(
                "utf-8",
                errors="replace",
            )

        return HygieneExecution(
            change=change,
            command=list(change.command),
            return_code=-1,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            timed_out=True,
            changed_files=[],
            applied=False,
        )


def _extract_baseline_metrics(baseline):
    """
    Extract the metrics needed for regression comparison.
    """

    test_runs = getattr(
        baseline,
        "test_runs",
        [],
    )

    if test_runs:
        test = test_runs[0]

        return {
            "tests_run": getattr(
                test,
                "tests_run",
                None,
            ),
            "passed": getattr(
                test,
                "tests_passed",
                None,
            ),
            "failed": getattr(
                test,
                "tests_failed",
                None,
            ),
        }

    return {
        "tests_run": None,
        "passed": None,
        "failed": None,
    }


def _extract_coverage(baseline):
    coverage = getattr(
        baseline,
        "coverage",
        None,
    )

    if coverage is None:
        return None

    return getattr(
        coverage,
        "coverage_percent",
        None,
    )


def _validate_baseline(
    before,
    after,
):
    """
    Compare baseline results before and after mutation.
    """

    before_metrics = _extract_baseline_metrics(before)
    after_metrics = _extract_baseline_metrics(after)

    before_passed = before_metrics["passed"]
    after_passed = after_metrics["passed"]

    before_failed = before_metrics["failed"]
    after_failed = after_metrics["failed"]

    reasons = []

    regression = False

    if not getattr(after, "overall_passed", False):
        regression = True
        reasons.append("Post-change baseline did not pass.")

    if getattr(after, "deterministic", None) is not True:
        regression = True
        reasons.append("Post-change baseline is not deterministic.")

    if (
        before_passed is not None
        and after_passed is not None
        and after_passed < before_passed
    ):
        regression = True
        reasons.append("Number of passed tests decreased.")

    if (
        before_failed is not None
        and after_failed is not None
        and after_failed > before_failed
    ):
        regression = True
        reasons.append("Number of failed tests increased.")

    before_tests = before_metrics["tests_run"]
    after_tests = after_metrics["tests_run"]

    if (
        before_tests is not None
        and after_tests is not None
        and after_tests < before_tests
    ):
        regression = True
        reasons.append("Total number of tests decreased.")

    validation_passed = not regression

    return HygieneValidation(
        baseline_passed=getattr(
            before,
            "overall_passed",
            False,
        ),
        post_change_passed=getattr(
            after,
            "overall_passed",
            False,
        ),
        baseline_deterministic=(getattr(before, "deterministic", None) is True),
        post_change_deterministic=(getattr(after, "deterministic", None) is True),
        tests_before=before_tests,
        tests_after=after_tests,
        passed_before=before_passed,
        passed_after=after_passed,
        failed_before=before_failed,
        failed_after=after_failed,
        coverage_before=_extract_coverage(before),
        coverage_after=_extract_coverage(after),
        regression_detected=regression,
        validation_passed=validation_passed,
        reasons=reasons,
    )


def _promote_workspace(
    workspace,
    repo_path,
):
    """
    Promote the validated workspace into the original repository.

    This is only called after all validation gates pass.
    """

    workspace = Path(workspace)
    repo_path = Path(repo_path)

    before = _snapshot_repository(repo_path)
    after = _snapshot_repository(workspace)

    changed_files = _changed_files(
        before,
        after,
    )

    for relative in changed_files:
        source = workspace / relative
        destination = repo_path / relative

        if source.exists():
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                source,
                destination,
            )

        elif destination.exists():
            destination.unlink()

    return changed_files


def apply_hygiene_change(
    repo_path,
    context,
    dependency_info,
    baseline,
    change,
    baseline_runner: Optional[Callable] = None,
    timeout=600,
):
    """
    Safely apply one HygieneChange.

    Contract
    --------
    1. Starting baseline must pass.
    2. Starting baseline must be deterministic.
    3. Mutation occurs only inside an isolated workspace.
    4. Exactly one HygieneChange is executed.
    5. A fresh baseline is run after mutation.
    6. Any regression rejects the mutation.
    7. Rejected mutations are discarded.
    8. Accepted mutations remain isolated and are never promoted
       automatically to the original repository.
    9. `execution.changed_files` reports the files changed inside
       the isolated workspace.
    10. `original_repo_untouched` is always True.

    `baseline_runner` is injectable for synthetic testing.

    Production usage should leave it as None, in which case the
    existing pipeline.baseline.run_baseline implementation is used.
    """

    repo_path = Path(repo_path)

    # ---------------------------------------------------------
    # Gate 1: starting baseline must already be healthy.
    # ---------------------------------------------------------

    if not getattr(
        baseline,
        "overall_passed",
        False,
    ):
        validation = HygieneValidation(
            baseline_passed=False,
            post_change_passed=False,
            baseline_deterministic=False,
            post_change_deterministic=False,
            tests_before=None,
            tests_after=None,
            passed_before=None,
            passed_after=None,
            failed_before=None,
            failed_after=None,
            coverage_before=None,
            coverage_after=None,
            regression_detected=True,
            validation_passed=False,
            reasons=["Cannot mutate a repository whose baseline is failing."],
        )

        execution = HygieneExecution(
            change=change,
            command=list(change.command),
            return_code=-1,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            timed_out=False,
            changed_files=[],
            applied=False,
        )

        return HygieneResult(
            change=change,
            execution=execution,
            validation=validation,
            accepted=False,
            rolled_back=False,
            rollback_successful=None,
            original_repo_untouched=True,
            warnings=[],
        )

    # ---------------------------------------------------------
    # Gate 2: baseline must be deterministic.
    # ---------------------------------------------------------

    if (
        getattr(
            baseline,
            "deterministic",
            None,
        )
        is not True
    ):
        validation = HygieneValidation(
            baseline_passed=True,
            post_change_passed=False,
            baseline_deterministic=False,
            post_change_deterministic=False,
            tests_before=None,
            tests_after=None,
            passed_before=None,
            passed_after=None,
            failed_before=None,
            failed_after=None,
            coverage_before=None,
            coverage_after=None,
            regression_detected=True,
            validation_passed=False,
            reasons=["Cannot mutate a non-deterministic repository."],
        )

        execution = HygieneExecution(
            change=change,
            command=list(change.command),
            return_code=-1,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            timed_out=False,
            changed_files=[],
            applied=False,
        )

        return HygieneResult(
            change=change,
            execution=execution,
            validation=validation,
            accepted=False,
            rolled_back=False,
            rollback_successful=None,
            original_repo_untouched=True,
            warnings=[],
        )

    # ---------------------------------------------------------
    # Create isolated workspace.
    # ---------------------------------------------------------

    temp_root = Path(tempfile.mkdtemp(prefix="hygiene-"))

    workspace = temp_root / "repo"

    try:
        _copy_repository(
            repo_path,
            workspace,
        )

        before_snapshot = _snapshot_repository(workspace)

        # -----------------------------------------------------
        # Apply exactly one mutation.
        # -----------------------------------------------------

        execution = _run_mutation_command(
            change,
            workspace,
            timeout=timeout,
        )

        after_snapshot = _snapshot_repository(workspace)

        execution.changed_files = _changed_files(
            before_snapshot,
            after_snapshot,
        )

        if not execution.applied:
            validation = HygieneValidation(
                baseline_passed=True,
                post_change_passed=False,
                baseline_deterministic=True,
                post_change_deterministic=False,
                tests_before=None,
                tests_after=None,
                passed_before=None,
                passed_after=None,
                failed_before=None,
                failed_after=None,
                coverage_before=_extract_coverage(baseline),
                coverage_after=None,
                regression_detected=True,
                validation_passed=False,
                reasons=["Hygiene command failed or timed out."],
            )

            return HygieneResult(
                change=change,
                execution=execution,
                validation=validation,
                accepted=False,
                rolled_back=True,
                rollback_successful=True,
                original_repo_untouched=True,
                warnings=[],
            )

        # -----------------------------------------------------
        # Run the baseline against the isolated workspace.
        # -----------------------------------------------------

        if baseline_runner is None:
            from pipeline.baseline import run_baseline

            post_baseline = run_baseline(
                str(workspace),
                context,
                dependency_info,
            )
        else:
            post_baseline = baseline_runner(
                str(workspace),
                context,
                dependency_info,
            )

        validation = _validate_baseline(
            baseline,
            post_baseline,
        )

        # -----------------------------------------------------
        # Reject if validation fails.
        # -----------------------------------------------------

        if not validation.validation_passed:
            return HygieneResult(
                change=change,
                execution=execution,
                validation=validation,
                accepted=False,
                rolled_back=True,
                rollback_successful=True,
                original_repo_untouched=True,
                warnings=validation.reasons,
            )


        # -----------------------------------------------------
        # Everything passed.
        #
        # IMPORTANT:
        # Never promote the isolated workspace into the original
        # repository here. The hygiene execution layer is strictly
        # non-destructive.
        #
        # An accepted result means:
        #   - the mutation succeeded in isolation
        #   - the post-change baseline passed
        #   - determinism was preserved
        #   - no regression was detected
        #
        # The caller can inspect execution.changed_files and decide
        # separately whether to apply/commit those changes.
        # -----------------------------------------------------

        return HygieneResult(
            change=change,
            execution=execution,
            validation=validation,
            accepted=True,
            rolled_back=False,
            rollback_successful=None,
            original_repo_untouched=True,
            warnings=[],
        )

    finally:
        shutil.rmtree(
            temp_root,
            ignore_errors=True,
        )