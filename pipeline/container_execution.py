import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from pipeline.containerization import (
    ContainerChange,
    ContainerExecution,
    ContainerProposal,
    ContainerResult,
    ContainerValidation,
)



def _run_command(command, cwd, timeout=600):
    """
    Small execution wrapper used only by the container layer.

    Returns a dictionary so this module remains independent from the
    baseline CommandResult implementation.
    """

    start = time.monotonic()

    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",    
            errors="replace",
            timeout=timeout,
        )

        return {
            "return_code": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "duration_seconds": time.monotonic() - start,
            "timed_out": False,
        }

    except subprocess.TimeoutExpired as exc:
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

        return {
            "return_code": -1,
            "stdout": stdout,
            "stderr": stderr,
            "duration_seconds": time.monotonic() - start,
            "timed_out": True,
        }

    except FileNotFoundError as exc:
        return {
            "return_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "duration_seconds": time.monotonic() - start,
            "timed_out": False,
        }


def _copy_repository(repo_path):
    """
    Create an isolated copy of the repository.

    The original repository is never used as the Docker build context
    when a proposed Dockerfile must be created.
    """

    source = Path(repo_path).resolve()

    workspace = Path(
        tempfile.mkdtemp(
            prefix="container-baseline-"
        )
    )

    destination = workspace / source.name

    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "build",
            "dist",
        ),
    )

    return workspace, destination

def _write_default_dockerfile(
    workspace_repo,
    proposal,
    baseline,
):
    """
    Materialize a proposed Dockerfile inside the isolated workspace.
    """
    dockerfile_path = workspace_repo / "Dockerfile"
    
    # Strictly trust the proposal. Do not regenerate the file!
    if proposal.dockerfile_content:
        dockerfile_path.write_text(proposal.dockerfile_content, encoding="utf-8")
        
    return dockerfile_path

# def _write_default_dockerfile(
#     workspace_repo,
#     proposal,
#     baseline,
# ):
#     """
#     Materialize a proposed Dockerfile inside the isolated workspace.
#     """

#     test_command = None

#     if baseline.test_runs:
#         test_command = list(
#             baseline.test_runs[0].command
#         )

#         if test_command:
#             test_command[0] = "python"

#     if test_command:
#         command_json = ", ".join(
#             repr(str(part))
#             for part in test_command
#         )

#         dockerfile = "\n".join(
#             [
#                 "FROM python:3.10-slim",
#                 "",
#                 "WORKDIR /app",
#                 "",
#                 "COPY . .",
#                 "",
#                 "RUN python -m pip install --upgrade pip",
#                 "RUN python -m pip install .",
#                 "",
#                 f"CMD [{command_json}]",
#                 "",
#             ]
#         )
#     else:
#         dockerfile = "\n".join(
#             [
#                 "FROM python:3.10-slim",
#                 "",
#                 "WORKDIR /app",
#                 "",
#                 "COPY . .",
#                 "",
#                 "RUN python -m pip install --upgrade pip",
#                 "RUN python -m pip install .",
#                 "",
#                 'CMD ["python", "-m", "pytest", "-q"]',
#                 "",
#             ]
#         )

#     dockerfile_path = (
#         workspace_repo / "Dockerfile"
#     )

#     dockerfile_path.write_text(
#         dockerfile,
#         encoding="utf-8",
#     )

#     return dockerfile_path


def _make_change(
    proposal,
    baseline,
):
    """
    Never regenerate the Dockerfile here. 
    Strictly trust the proposal as the single source of truth.
    """
    test_command = proposal.test_command or ["python", "-m", "pytest", "-q"]

    return ContainerChange(
        action=proposal.action,
        kind=proposal.kind,
        files=list(proposal.files),
        dockerfile_content=proposal.dockerfile_content,
        dockerignore_content=proposal.dockerignore_content,
        build_command=list(proposal.command or []),
        test_command=test_command,
        reason=proposal.reason,
        confidence=proposal.confidence,
        mutates_files=(proposal.action == "introduce_default"),
    )

# def _make_change(
#     proposal,
#     baseline,
# ):
#     dockerfile_content = None

#     if proposal.action == "introduce_default":
#         if baseline.test_runs:
#             test_command = list(
#                 baseline.test_runs[0].command
#             )

#             if test_command:
#                 test_command[0] = "python"

#             command_json = ", ".join(
#                 repr(str(part))
#                 for part in test_command
#             )

#             dockerfile_content = "\n".join(
#                 [
#                     "FROM python:3.10-slim",
#                     "",
#                     "WORKDIR /app",
#                     "",
#                     "COPY . .",
#                     "",
#                     "RUN python -m pip install --upgrade pip",
#                     "RUN python -m pip install .",
#                     "",
#                     f"CMD [{command_json}]",
#                     "",
#                 ]
#             )

#     return ContainerChange(
#         action=proposal.action,
#         kind=proposal.kind,
#         files=list(proposal.files),
#         dockerfile_content=dockerfile_content,
#         dockerignore_content=None,
#         build_command=list(
#             proposal.command or []
#         ),
#         test_command=(
#             [
#                 "python",
#                 "-m",
#                 "pytest",
#                 "-q",
#             ]
#         ),
#         reason=proposal.reason,
#         confidence=proposal.confidence,
#         mutates_files=(
#             proposal.action == "introduce_default"
#         ),
#     )


def _parse_test_counts(output):
    """
    Parse the common pytest summary:

        266 passed, 2 skipped, 1 warning
    """

    import re

    passed_match = re.search(
        r"(\d+)\s+passed",
        output,
    )

    failed_match = re.search(
        r"(\d+)\s+failed",
        output,
    )

    skipped_match = re.search(
        r"(\d+)\s+skipped",
        output,
    )

    passed = (
        int(passed_match.group(1))
        if passed_match
        else None
    )

    failed = (
        int(failed_match.group(1))
        if failed_match
        else None
    )

    skipped = (
        int(skipped_match.group(1))
        if skipped_match
        else None
    )

    values = [
        value
        for value in (
            passed,
            failed,
            skipped,
        )
        if value is not None
    ]

    tests_run = (
        sum(values)
        if values
        else None
    )

    return (
        tests_run,
        passed,
        failed,
        skipped,
    )


def _validate(
    baseline,
    execution,
    test_output,
):
    reasons = []

    baseline_passed = (
        baseline is not None
        and baseline.overall_passed
    )

    baseline_deterministic = (
        baseline is not None
        and baseline.deterministic is True
    )

    container_build_passed = (
        execution.build_return_code == 0
    )

    container_tests_passed = (
        execution.test_return_code == 0
    )
    

    tests_in_container = None
    passed_in_container = None
    failed_in_container = None
    skipped_in_container = None

    if test_output:
        (
            tests_in_container,
            passed_in_container,
            failed_in_container,
            skipped_in_container,
        ) = _parse_test_counts(
            test_output
        )

    tests_before = None
    passed_before = None
    failed_before = None
    skipped_before = None

    if baseline and baseline.test_runs:
        test = baseline.test_runs[0]

        tests_before = test.tests_run
        passed_before = test.tests_passed
        failed_before = test.tests_failed
        skipped_before = test.tests_skipped

    regression_detected = False

    if not baseline_passed:
        reasons.append(
            "The repository baseline did not pass."
        )

    if not baseline_deterministic:
        reasons.append(
            "The repository baseline is not deterministic."
        )

    if not container_build_passed:
        reasons.append(
            "The Docker image build failed."
        )

    if not container_tests_passed:
        reasons.append(
            "Tests failed inside the container."
        )

    if (
        passed_before is not None
        and passed_in_container is not None
        and passed_in_container < passed_before
    ):
        regression_detected = True
        reasons.append(
            "The number of passing tests decreased."
        )

    if (
        tests_before is not None
        and tests_in_container is not None
        and tests_in_container < tests_before
    ):
        regression_detected = True
        reasons.append(
            "The number of executed tests decreased."
        )

    validation_passed = (
        baseline_passed
        and baseline_deterministic
        and container_build_passed
        and container_tests_passed
        and not regression_detected
    )

    return ContainerValidation(
        baseline_passed=baseline_passed,
        container_build_passed=container_build_passed,
        container_tests_passed=container_tests_passed,
        baseline_deterministic=baseline_deterministic,
        tests_before=tests_before,
        tests_in_container=tests_in_container,
        passed_before=passed_before,
        passed_in_container=passed_in_container,
        failed_before=failed_before,
        failed_in_container=failed_in_container,
        skipped_before=skipped_before,
        skipped_in_container=skipped_in_container,
        regression_detected=regression_detected,
        validation_passed=validation_passed,
        reasons=reasons,
    )


def apply_container_proposal(
    repo_path,
    proposal,
    baseline,
    timeout=600,
):
    """
    Safely execute a containerization proposal.

    Golden Safety Rule:

        The original repository is never mutated.

    A proposal is accepted only when:

      1. baseline passes
      2. baseline is deterministic
      3. Docker build succeeds
      4. tests execute successfully in the container
      5. test counts do not regress

    Docker is invoked only from the isolated workspace.
    """

    change = _make_change(
        proposal,
        baseline,
    )

    # Hard safety gate before Docker is touched.
        # Hard safety gate before Docker is touched.
    if (
        baseline is None
        or not baseline.overall_passed
        or baseline.deterministic is not True
    ):
        execution = ContainerExecution(
            change=change,
            build_command=change.build_command,
            test_command=change.test_command,
            build_return_code=None,
            test_return_code=None,
            build_stdout="",
            build_stderr="",
            test_stdout="",
            test_stderr="",
            build_duration_seconds=0.0,
            test_duration_seconds=0.0,
            image_built=False,
            tests_executed=False,
            timed_out=False,
            changed_files=[],
            applied=False,
        )

        validation = _validate(
            baseline,
            execution,
            "",
        )

        return ContainerResult(
            proposal=proposal,
            change=change,
            execution=execution,
            validation=validation,
            accepted=False,
            rolled_back=False,
            rollback_successful=None,
            original_repo_untouched=True,
            warnings=[
                "Container execution blocked by baseline safety gate."
            ],
        )

    workspace = None

    try:
        workspace, isolated_repo = _copy_repository(
            repo_path
        )

        changed_files = []

        if proposal.action == "introduce_default":
            dockerfile = _write_default_dockerfile(
                isolated_repo,
                proposal,
                baseline,
            )

            changed_files.append(
                str(
                    dockerfile.relative_to(
                        isolated_repo
                    )
                )
            )

        # Docker availability/build gate.
        build_command = list(
            change.build_command
        )

        build_result = _run_command(
            build_command,
            cwd=isolated_repo,
            timeout=timeout,
        )

        if build_result["timed_out"]:
            test_result = {
                "return_code": -1,
                "stdout": "",
                "stderr": "Container build timed out.",
                "duration_seconds": 0.0,
                "timed_out": True,
            }
        elif build_result["return_code"] != 0:
            test_result = {
                "return_code": -1,
                "stdout": "",
                "stderr": "Container tests were not executed.",
                "duration_seconds": 0.0,
                "timed_out": False,
            }
        else:
            # The image name is fixed by the proposal.
            image_name = "repo-baseline"

            test_command = [
                "docker",
                "run",
                "--rm",
                image_name,
            ]

            test_command.extend(
                change.test_command
            )

            test_result = _run_command(
                test_command,
                cwd=isolated_repo,
                timeout=timeout,
            )

        test_output = (
            test_result["stdout"]
            + "\n"
            + test_result["stderr"]
        )

        execution = ContainerExecution(
            change=change,
            build_command=build_command,
            test_command=
                [
                    "docker",
                    "run",
                    "--rm",
                    "repo-baseline",
                ],
            build_return_code=build_result[
                "return_code"
            ],
            test_return_code=test_result[
                "return_code"
            ],
            build_stdout=build_result[
                "stdout"
            ],
            build_stderr=build_result[
                "stderr"
            ],
            test_stdout=test_result[
                "stdout"
            ],
            test_stderr=test_result[
                "stderr"
            ],
            build_duration_seconds=build_result[
                "duration_seconds"
            ],
            test_duration_seconds=test_result[
                "duration_seconds"
            ],
            image_built=(
                build_result["return_code"] == 0
            ),
            tests_executed=(
                build_result["return_code"] == 0
                and not test_result["timed_out"]
            ),
            timed_out=(
                build_result["timed_out"]
                or test_result["timed_out"]
            ),
            changed_files=changed_files,
            applied=(
                build_result["return_code"] == 0
            ),
        )

        validation = _validate(
            baseline,
            execution,
            test_output,
        )

        return ContainerResult(
            proposal=proposal,
            change=change,
            execution=execution,
            validation=validation,
            accepted=validation.validation_passed,
            rolled_back=False,
            rollback_successful=None,
            original_repo_untouched=True,
            warnings=[],
        )

    finally:
        if workspace is not None:
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )