from __future__ import annotations
import os
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from pipeline.task_schema import (
    TaskValidation,
    TaskVerificationResult,
    VerificationRun,
    canonical_json,
)


Runner = Callable[..., subprocess.CompletedProcess]


# Matches pytest's trailing timing summary, e.g.:
#   "1 passed in 0.42s"
#   "5 passed, 1 warning in 0.92s"
#   "===================== 1 passed in 0.05s ======================"
#   "1 passed in 1.23s (0:00:01)"
# The wall-clock duration is inherently non-deterministic run-to-run
# and must not affect the determinism verdict.
_DURATION_LINE_PATTERN = re.compile(
    r"in \d+(?:\.\d+)?s(?:\s*\(\d+:\d{2}:\d{2}\))?"
)


@dataclass(frozen=True)
class VerifierConfig:
    timeout_seconds: int = 120
    deterministic_stdout: bool = True
    deterministic_stderr: bool = True
    deterministic_return_code: bool = True


@dataclass(frozen=True)
class VerificationPaths:
    fail_before: Path
    pass_after: Path
    determinism: Path


class TaskVerifier:
    """
    Safely validates a benchmark task using:

        FAIL-BEFORE
             |
             v
        PASS-AFTER
             |
             v
        DETERMINISM
             |
             v
          ACCEPT

    The original input/solution directories are never modified.
    """

    def __init__(
        self,
        config: Optional[VerifierConfig] = None,
        runner: Optional[Runner] = None,
    ) -> None:
        self.config = config or VerifierConfig()
        self.runner = runner or subprocess.run

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(
        self,
        input_dir: str | Path,
        solution_dir: str | Path,
        command: Sequence[str],
        evidence_dir: str | Path,
        *,
        task_id: str,
        oracle_dir: Optional[str | Path] = None,
        require_assertion_failure: bool = True,
    ) -> TaskVerificationResult:
        """
        oracle_dir, when provided, points at a task-local verification
        oracle (for example, a History task's regression-test files).
        Its contents are overlaid on top of both the input/ and
        solution/ workspaces, at matching relative paths, immediately
        before each execution. This lets a single, fixed test file be
        the thing that's actually run in both states, instead of
        whatever version of a test file happens to already live in
        input/ or solution/.

        require_assertion_failure controls how strict the FAIL-BEFORE
        gate is:

          * True (default) -- fail-before must be a genuine
            assertion-level failure (an AssertionError traceback, in
            either pytest's or a plain interpreter's format). This is
            the right default for synthetic states such as an
            Excision stub, where an uncaught exception (e.g. a
            TypeError from unrelated code touching a stubbed-out
            None) is a synthesis artifact, not evidence of a real
            bug, and must not count.

          * False -- any genuine behavioral failure counts, including
            an uncaught exception (ZeroDivisionError, KeyError, ...).
            This is the right setting for History tasks: input/ is
            real, historical, unmodified code, so an uncaught
            exception there *is* the real bug, not an artifact.
            Infrastructure failures (ImportError, SyntaxError,
            collection errors, a pytest usage/collection exit code)
            are still rejected either way.
        """

        input_path = Path(input_dir).resolve()
        solution_path = Path(solution_dir).resolve()
        evidence_path = Path(evidence_dir).resolve()

        if not input_path.is_dir():
            raise ValueError(
                f"input directory does not exist: {input_path}"
            )

        if not solution_path.is_dir():
            raise ValueError(
                f"solution directory does not exist: {solution_path}"
            )

        if not command:
            raise ValueError(
                "verification command must not be empty"
            )

        oracle_path: Optional[Path] = None

        if oracle_dir is not None:
            oracle_path = Path(oracle_dir).resolve()

            if not oracle_path.is_dir():
                raise ValueError(
                    f"oracle directory does not exist: {oracle_path}"
                )

        evidence_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        # --------------------------------------------------------------
        # 1. FAIL-BEFORE
        # --------------------------------------------------------------

        with tempfile.TemporaryDirectory(
            prefix="task-verifier-input-"
        ) as temporary:
            workspace = Path(temporary)

            self._copy_tree(
                input_path,
                workspace,
            )

            if oracle_path is not None:
                self._overlay_oracle(
                    oracle_path,
                    workspace,
                )

            fail_run = self._execute(
                command,
                workspace,
            )

        fail_reason = self._classify_fail_before(
            fail_run,
            require_assertion_failure=require_assertion_failure,
        )
        fail_before_verified = (
            not fail_run.passed
            and fail_reason is None
        )

        fail_before_evidence = {
            "task_id": task_id,
            "stage": "fail_before",
            "expected": (
                "assertion-level behavioral failure"
                if require_assertion_failure
                else "behavioral failure"
            ),
            "actual": self._run_to_dict(fail_run),
            "verified": fail_before_verified,
            "failure_class": fail_reason or "behavioral_failure",
        }

        self._write_json(
            evidence_path / "fail_before.json",
            fail_before_evidence,
        )

        # --------------------------------------------------------------
        # Fail closed immediately.
        # --------------------------------------------------------------

        if not fail_before_verified:
            reason = (
                f"Fail-before rejected: {fail_reason}."
                if fail_reason
                else "Verifier unexpectedly passed on input state."
            )
            validation = TaskValidation(
                fail_before=fail_run,
                pass_after=self._blocked_run(
                    command,
                    "pass-after skipped because fail-before was not a valid behavioral failure",
                ),
                deterministic_runs=(),
                fail_before_verified=False,
                pass_after_verified=False,
                deterministic_verified=False,
                validation_passed=False,
                reasons=(reason,),
            )

            return self._result(
                task_id,
                validation,
            )

        # --------------------------------------------------------------
        # 2. PASS-AFTER
        # --------------------------------------------------------------

        with tempfile.TemporaryDirectory(
            prefix="task-verifier-solution-"
        ) as temporary:
            workspace = Path(temporary)

            self._copy_tree(
                solution_path,
                workspace,
            )

            if oracle_path is not None:
                self._overlay_oracle(
                    oracle_path,
                    workspace,
                )

            pass_run = self._execute(
                command,
                workspace,
            )
            pass_after_verified = pass_run.passed

            # ----------------------------------------------------------
            # 3. DETERMINISM
            # ----------------------------------------------------------

            if pass_after_verified:
                deterministic_run = self._execute(
                    command,
                    workspace,
                )
                deterministic_verified = self._runs_are_deterministic(
                    pass_run,
                    deterministic_run,
                )
            else:
                deterministic_run = self._blocked_run(
                    command,
                    "Determinism skipped because pass-after failed.",
                )
                deterministic_verified = False

        pass_after_evidence = {
            "task_id": task_id,
            "stage": "pass_after",
            "expected": "success",
            "actual": self._run_to_dict(pass_run),
            "verified": pass_after_verified,
        }

        self._write_json(
            evidence_path / "pass_after.json",
            pass_after_evidence,
        )

        determinism_evidence = {
            "task_id": task_id,
            "stage": "determinism",
            "expected": "identical successful runs",
            "first_run": self._run_to_dict(
                pass_run
            ),
            "second_run": self._run_to_dict(
                deterministic_run
            ),
            "verified": deterministic_verified,
        }

        self._write_json(
            evidence_path / "determinism.json",
            determinism_evidence,
        )

        reasons = []

        if not pass_after_verified:
            reasons.append(
                "Verifier did not pass on the solution state."
            )

        if pass_after_verified and not deterministic_verified:
            reasons.append(
                "Repeated solution verification was not deterministic."
            )

        validation = TaskValidation(
            fail_before=fail_run,
            pass_after=pass_run,
            deterministic_runs=(
                pass_run,
                deterministic_run,
            ),
            fail_before_verified=fail_before_verified,
            pass_after_verified=pass_after_verified,
            deterministic_verified=deterministic_verified,
            validation_passed=(
                fail_before_verified
                and pass_after_verified
                and deterministic_verified
            ),
            reasons=tuple(reasons),
        )

        return self._result(
            task_id,
            validation,
        )

    # ------------------------------------------------------------------
    # Fail-before integrity
    # ------------------------------------------------------------------

    @staticmethod
    def _is_assertion_failure(run: VerificationRun) -> bool:
        """Return True only for a genuine assertion-level failure.

        Infrastructure failures are deliberately excluded: import errors,
        syntax errors, collection failures, pytest usage errors, and arbitrary
        runtime exceptions must never satisfy the fail-before gate.

        Two output shapes are recognized as genuine assertion evidence:

          * pytest's own failure format -- an AssertionError traceback
            plus its "short test summary info" footer.
          * a plain Python traceback ending in AssertionError -- e.g.
            when the verification command isn't pytest itself, or a
            test harness invokes the test function directly.
        """
        if run.passed or run.return_code != 1:
            return False

        combined = f"{run.stdout}\n{run.stderr}"
        lowered = combined.lower()

        infrastructure_markers = (
            "importerror",
            "modulenotfounderror",
            "syntaxerror",
            "error collecting ",
            "errors during collection",
            "interrupted during collection",
            "collection error",
        )
        if any(marker in lowered for marker in infrastructure_markers):
            return False

        has_assertion_error = (
            "assertionerror" in lowered
            or "e       assert " in lowered
        )

        # A pytest assertion failure has an AssertionError traceback and a
        # failed-test summary. Requiring both avoids accepting arbitrary
        # exceptions or malformed pytest output.
        has_pytest_summary = (
            "short test summary info" in lowered
            and " failed" in lowered
        )

        # A plain (non-pytest) traceback ending in AssertionError is
        # equally valid evidence of a genuine assertion-level failure.
        has_plain_traceback = (
            "traceback (most recent call last)" in lowered
        )

        return has_assertion_error and (
            has_pytest_summary
            or has_plain_traceback
        )

    @classmethod
    def _classify_fail_before(
        cls,
        run: VerificationRun,
        *,
        require_assertion_failure: bool = True,
    ) -> Optional[str]:
        """Return a rejection reason for a non-viable fail-before run."""
        if run.passed:
            return "no failure"

        combined = f"{run.stdout}\n{run.stderr}"
        lowered = combined.lower()

        if "importerror" in lowered or "modulenotfounderror" in lowered:
            return "ImportError/ModuleNotFoundError"
        if "syntaxerror" in lowered:
            return "SyntaxError"
        if (
            "error collecting " in lowered
            or "errors during collection" in lowered
            or "interrupted during collection" in lowered
            or "collection error" in lowered
        ):
            return "pytest test collection failure"
        if run.return_code == 2:
            return "pytest collection/usage failure"

        if (
            require_assertion_failure
            and not cls._is_assertion_failure(run)
        ):
            return "non-assertion behavioral failure"

        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute(
        self,
        command: Sequence[str],
        cwd: Path,
    ) -> VerificationRun:
        start = time.monotonic()

        try:
            env = os.environ.copy()

            # Make the isolated candidate source tree importable, and make
            # sure it is what actually gets imported.
            #
            # This is especially important for src-layout repositories such as:
            #
            #   workspace/
            #       src/
            #           requests/
            #       tests/
            #
            # Without this, pytest may import an already-installed package
            # instead of the historical candidate being verified.
            #
            # A flat-layout repository (e.g. glom/ sitting directly at the
            # workspace root) has the same problem when the package also
            # happens to be pip-installed (editable or not) into the
            # environment running this verifier: without `cwd` itself on
            # PYTHONPATH ahead of everything else, Python can resolve
            # `import glom` from site-packages rather than from this
            # isolated, possibly-mutated copy. That silently makes
            # fail-before/pass-after test the wrong code -- an Excision
            # stub or a historical parent-state bug never actually gets
            # exercised, which surfaces as a uniform, suspicious "no
            # failure" verdict across every candidate rather than a
            # genuine behavioral result.
            src_dir = cwd / "src"

            existing_pythonpath = env.get("PYTHONPATH")

            python_paths = [str(cwd)]

            if src_dir.is_dir():
                python_paths.append(str(src_dir))

            if existing_pythonpath:
                python_paths.append(existing_pythonpath)

            env["PYTHONPATH"] = os.pathsep.join(python_paths)

            completed = self.runner(
                list(command),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.timeout_seconds,
                check=False,
                env=env,
                stdin=subprocess.DEVNULL,
            )

            duration = time.monotonic() - start

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""

            return VerificationRun(
                command=tuple(command),
                return_code=completed.returncode,
                passed=completed.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
            )

        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start

            stdout = self._decode_output(
                getattr(exc, "stdout", None)
            )
            stderr = self._decode_output(
                getattr(exc, "stderr", None)
            )

            return VerificationRun(
                command=tuple(command),
                return_code=-1,
                passed=False,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
            )

        except OSError as exc:
            duration = time.monotonic() - start

            return VerificationRun(
                command=tuple(command),
                return_code=-1,
                passed=False,
                stdout="",
                stderr=str(exc),
                duration_seconds=duration,
            )

    # ------------------------------------------------------------------
    # Determinism
    # ------------------------------------------------------------------

    def _runs_are_deterministic(
        self,
        first: VerificationRun,
        second: VerificationRun,
    ) -> bool:
        if (
            self.config.deterministic_return_code
            and first.return_code != second.return_code
        ):
            return False

        if (
            self.config.deterministic_stdout
            and self._normalize_for_determinism(first.stdout)
            != self._normalize_for_determinism(second.stdout)
        ):
            return False

        if (
            self.config.deterministic_stderr
            and self._normalize_for_determinism(first.stderr)
            != self._normalize_for_determinism(second.stderr)
        ):
            return False

        return (
            first.passed
            and second.passed
        )

    @staticmethod
    def _normalize_for_determinism(text: str) -> str:
        """
        Strip volatile pytest timing/duration text before comparing
        two runs for determinism.

        Pytest prints wall-clock execution time in its summary line
        (e.g. "1 passed in 0.42s"). That duration legitimately varies
        between otherwise-identical runs and must not be treated as a
        real behavioral difference.
        """

        if not text:
            return text

        return _DURATION_LINE_PATTERN.sub(
            "in <duration>",
            text,
        )

    # ------------------------------------------------------------------
    # Workspace handling
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_tree(
        source: Path,
        destination: Path,
    ) -> None:
        """
        Copy the candidate tree into an isolated workspace.

        The source tree is never modified.
        """

        excluded_dirs = {
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            "tasks",
        }

        for item in source.iterdir():
            if item.is_dir() and item.name in excluded_dirs:
                continue

            target = destination / item.name

            if item.is_dir():
                shutil.copytree(
                    item,
                    target,
                    dirs_exist_ok=True,
                )
            else:
                shutil.copy2(
                    item,
                    target,
                )

    @staticmethod
    def _overlay_oracle(
        oracle_dir: Path,
        workspace: Path,
    ) -> None:
        """
        Copy every file under oracle_dir on top of workspace, preserving
        relative paths and overwriting anything already there.

        This is what makes the oracle authoritative: whatever version of
        a test file the workspace started with (from input/ or
        solution/) is replaced by the task-local regression-test
        content before the command runs.
        """

        for item in oracle_dir.rglob("*"):
            if item.is_dir():
                continue

            relative = item.relative_to(
                oracle_dir
            )

            target = workspace / relative

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                item,
                target,
            )

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    @staticmethod
    def _run_to_dict(
        run: VerificationRun,
    ) -> dict:
        return run.to_dict()

    @staticmethod
    def _write_json(
        path: Path,
        data: dict,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            canonical_json(data),
            encoding="utf-8",
        )

    @staticmethod
    def _decode_output(
        value,
    ) -> str:
        if value is None:
            return ""

        if isinstance(value, bytes):
            return value.decode(
                "utf-8",
                errors="replace",
            )

        return str(value)

    @staticmethod
    def _blocked_run(
        command: Sequence[str],
        reason: str,
    ) -> VerificationRun:
        return VerificationRun(
            command=tuple(command),
            return_code=-1,
            passed=False,
            stdout="",
            stderr=reason,
            duration_seconds=0.0,
        )

    @staticmethod
    def _result(
        task_id: str,
        validation: TaskValidation,
    ) -> TaskVerificationResult:
        warnings = []

        if not validation.validation_passed:
            warnings.append(
                "Task rejected by verification state machine."
            )

        return TaskVerificationResult(
            task_id=task_id,
            validation=validation,
            accepted=validation.validation_passed,
            warnings=tuple(warnings),
        )


def verify_task(
    input_dir: str | Path,
    solution_dir: str | Path,
    command: Sequence[str],
    evidence_dir: str | Path,
    *,
    task_id: str,
    config: Optional[VerifierConfig] = None,
    oracle_dir: Optional[str | Path] = None,
    require_assertion_failure: bool = True,
) -> TaskVerificationResult:
    """
    Functional convenience wrapper.
    """

    verifier = TaskVerifier(
        config=config,
    )

    return verifier.verify(
        input_dir,
        solution_dir,
        command,
        evidence_dir,
        task_id=task_id,
        oracle_dir=oracle_dir,
        require_assertion_failure=require_assertion_failure,
    )