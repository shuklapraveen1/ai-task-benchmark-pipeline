import re
import subprocess
import sys
import time
import venv
import os
import tempfile
import shutil
import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from pipeline.dependencies import DependencyInfo
from pipeline.discover import RepoContext

FRAMEWORK_PACKAGES = {
    "pytest": "pytest",
    "coverage.py": "coverage",
    "tox": "tox",
    "doctest": None,
    "unittest": None,
}

FRAMEWORK_IMPORTS = {
    "pytest": "pytest",
    "coverage.py": "coverage",
    "tox": "tox",
}

@dataclass
class CommandResult:
    command: list
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    cwd: Optional[str] = None
    timed_out: bool = False


@dataclass
class TestResult:
    framework: str
    command: list
    passed: bool
    return_code: int

    tests_run: Optional[int]
    tests_passed: Optional[int]
    tests_failed: Optional[int]
    tests_skipped: Optional[int]

    duration_seconds: float

    stdout: str
    stderr: str

    interpreter: Optional[str] = None
    cwd: Optional[str] = None


@dataclass
class CoverageResult:
    tool: str
    command: list

    available: bool
    passed: bool

    total_statements: Optional[int]
    covered_statements: Optional[int]
    coverage_percent: Optional[float]
    missing_statements: Optional[int]

    stdout: str
    stderr: str


@dataclass
class BaselineResult:
    install: Optional[CommandResult]

    test_runs: list = field(default_factory=list)

    coverage: Optional[CoverageResult] = None

    deterministic: Optional[bool] = None

    warnings: list = field(default_factory=list)

    overall_passed: bool = False


def _run_command(
    command,
    cwd,
    timeout=600,
    env=None,
):
    """
    Run a command and capture stdout/stderr.

    The repository is never modified by this helper directly.

    stdin is explicitly closed (DEVNULL) so a child process that tries
    to prompt interactively (e.g. pip resolving a VCS dependency that
    triggers a git credential prompt) fails fast instead of blocking
    on a terminal that this pipeline never intends to feed.
    """

    start = time.monotonic()

    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
        )

        duration = time.monotonic() - start

        return CommandResult(
            command=list(command),
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            cwd=str(cwd),
            timed_out=False,
        )

    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start

        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")

        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        return CommandResult(
            command=list(command),
            return_code=-1,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            cwd=str(cwd),
            timed_out=True,
        )


def _venv_python(venv_path):
    """
    Return the Python executable inside a virtual environment.
    """

    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"

    return venv_path / "bin" / "python"

def _prepare_repository_workspace(repo_path):
    """
    Create an isolated filesystem copy of the repository.

    Git symlinks are restored from the Git index so repositories checked out
    on platforms where core.symlinks is disabled still retain their intended
    filesystem semantics.

    Returns:
        Path: temporary repository workspace.
    """
    repo_path = Path(repo_path).resolve()

    temp_dir = Path(
        tempfile.mkdtemp(prefix="repo-baseline-workspace-")
    )
    workspace = temp_dir / repo_path.name

    shutil.copytree(
        repo_path,
        workspace,
        symlinks=True,
    )

    # Git stores symlinks as mode 120000 entries whose blob contains the
    # symlink target. On Windows with core.symlinks=false, the checkout may
    # instead contain a normal text file containing that target.
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
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
        return workspace

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

            workspace_path = workspace / relative_path

            target_result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_path),
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

            # Resolve the Git symlink target relative to the symlink's
            # parent directory inside the temporary workspace.
            target_path = (
                workspace_path.parent / target
            ).resolve()

            try:
                target_path.relative_to(workspace)
            except ValueError:
                # Never allow a repository symlink to materialize content
                # outside the isolated workspace.
                continue

            # Remove the Windows checkout placeholder (which may be a
            # regular text file containing the symlink target).
            if workspace_path.exists() or workspace_path.is_symlink():
                if workspace_path.is_dir() and not workspace_path.is_symlink():
                    shutil.rmtree(workspace_path)
                else:
                    workspace_path.unlink()

            workspace_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            try:
                os.symlink(
                    target,
                    workspace_path,
                    target_is_directory=target_path.is_dir(),
                )

            except (OSError, NotImplementedError):
                # Fall back to materializing the target when the host
                # platform does not permit symlink creation.
                if target_path.is_dir():
                    shutil.copytree(
                        target_path,
                        workspace_path,
                        dirs_exist_ok=True,
                    )

                elif target_path.is_file():
                    shutil.copy2(
                        target_path,
                        workspace_path,
                    )

        except (ValueError, UnicodeError, OSError):
            continue

    return workspace


def _create_virtualenv(repo_path):
    """
    Create a temporary virtual environment outside the repository.
    """

    import tempfile

    temp_dir = tempfile.mkdtemp(prefix="repo-baseline-")
    venv_path = Path(temp_dir) / "venv"

    builder = venv.EnvBuilder(
        with_pip=True,
        clear=True,
    )

    builder.create(str(venv_path))

    return venv_path


def _install_dependencies(
    repo_path,
    dependency_info,
    python_executable,
):
    """
    Install the repository's discovered dependency environment.

    strategy:
    1. Prefer a discovered requirements.txt source.
    2. Install the local package.
    """

    repo_path = Path(repo_path)

    # First install the discovered development/test environment.
    requirements_file = None

    for source in dependency_info.sources:
        if source.path == "requirements.txt" and source.scope == "development":
            candidate = repo_path / source.path
            if candidate.exists():
                requirements_file = candidate
                break

    if requirements_file is not None:
        result = _run_command(
            [
                str(python_executable),
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements_file),
            ],
            cwd=repo_path,
        )

        if result.return_code != 0:
            return result

    # Finally install the repository itself.
    return _run_command(
        [
            str(python_executable),
            "-m",
            "pip",
            "install",
            ".",
        ],
        cwd=repo_path,
    )

_TEST_REQUIREMENT_FILES = (
    "requirements-dev.txt",
    "requirements-test.txt",
    "test-requirements.txt",
    "dev-requirements.txt",
    "tests/requirements.txt",
)

_TEST_EXTRAS = (
    "test",
    "tests",
    "testing",
    "dev",
)


def _install_test_dependencies(
    repo_path,
    python_executable,
):
    """
    Install repository test/development dependencies into the isolated
    baseline environment.

    This is intentionally repository-agnostic:
      1. Install common test/development requirements files when present.
      2. If the repository has packaging metadata, try common test extras.
         Undefined extras are ignored so they do not make the baseline fail.

    Returns None when all required-file installs succeed. Returns the failed
    CommandResult for a real requirements-file installation failure.
    """
    repo_path = Path(repo_path)

    # -------------------------------------------------------------
    # 1. Common test/development requirement files
    # -------------------------------------------------------------
    for relative_path in _TEST_REQUIREMENT_FILES:
        req_file = repo_path / relative_path

        if not req_file.is_file():
            continue

        print(f"  installing test/development requirements: {relative_path}")

        result = _run_command(
            [
                str(python_executable),
                "-m",
                "pip",
                "install",
                "-r",
                str(req_file),
            ],
            cwd=repo_path,
        )

        if result.return_code != 0:
            return result

    # -------------------------------------------------------------
    # 2. Common packaging extras
    # -------------------------------------------------------------
    packaging_files = (
        "setup.py",
        "setup.cfg",
        "pyproject.toml",
    )

    if not any((repo_path / filename).is_file() for filename in packaging_files):
        return None

    for extra in _TEST_EXTRAS:
        # An undefined extra is deliberately non-fatal.  This is a
        # best-effort fallback for repositories that expose their test
        # environment through setuptools/PEP 621 extras.
        print(f"  attempting test extra: [{extra}]")

        result = _run_command(
            [
                str(python_executable),
                "-m",
                "pip",
                "install",
                "-q",
                f".[{extra}]",
            ],
            cwd=repo_path,
        )

        if result.return_code != 0:
            print(
                f"  test extra [{extra}] unavailable or failed; "
                "continuing"
            )

    return None


def _ensure_test_frameworks(
    repo_path,
    context,
    python_executable,
):
    """
    Ensure all externally installed test/coverage frameworks detected by
    repository discovery are available in the isolated environment.

    Built-in frameworks such as unittest and doctest require no installation.
    Returns None when everything is available, otherwise returns the failed
    installation CommandResult.
    """
    repo_path = Path(repo_path)

    frameworks = list(
        dict.fromkeys(
            list(context.test_frameworks)
            + list(context.coverage_tools)
        )
    )

    for framework in frameworks:
        package = FRAMEWORK_PACKAGES.get(framework)

        # Built-in framework or unknown framework.
        if package is None:
            continue

        import_name = FRAMEWORK_IMPORTS.get(
            framework,
            framework,
        )

        check_result = _run_command(
            [
                str(python_executable),
                "-c",
                (
                    "import importlib.util; "
                    f"raise SystemExit("
                    f"0 if importlib.util.find_spec({import_name!r}) "
                    "is not None else 1)"
                ),
            ],
            cwd=repo_path,
        )

        if check_result.return_code == 0:
            continue

        print(
            f"  installing missing test framework: "
            f"{framework} ({package})"
        )

        install_result = _run_command(
            [
                str(python_executable),
                "-m",
                "pip",
                "install",
                package,
            ],
            cwd=repo_path,
        )

        if install_result.return_code != 0:
            return install_result

    return None

def _has_explicit_pytest_config(repo_path):
    """
    Return True when the repository explicitly configures pytest test
    discovery through a supported configuration file.

    Supported locations:
      - pytest.ini
      - .pytest.ini
      - setup.cfg [tool:pytest]
      - pyproject.toml [tool.pytest.ini_options]

    The repository's own pytest configuration is authoritative.
    """
    repo_path = Path(repo_path)

    # -------------------------------------------------------------
    # pytest.ini / .pytest.ini
    # -------------------------------------------------------------
    for filename in ("pytest.ini", ".pytest.ini"):
        config_path = repo_path / filename

        if config_path.is_file():
            parser = configparser.ConfigParser()

            try:
                parser.read(config_path, encoding="utf-8")
            except (OSError, configparser.Error):
                continue

            if parser.has_section("pytest"):
                return True

    # -------------------------------------------------------------
    # setup.cfg
    # -------------------------------------------------------------
    setup_cfg = repo_path / "setup.cfg"

    if setup_cfg.is_file():
        parser = configparser.ConfigParser()

        try:
            parser.read(setup_cfg, encoding="utf-8")
        except (OSError, configparser.Error):
            parser = None

        if parser is not None and parser.has_section("tool:pytest"):
            return True

    # -------------------------------------------------------------
    # pyproject.toml
    #
    # Python 3.10 does not have tomllib, so avoid introducing a
    # dependency just for this small discovery operation.
    # -------------------------------------------------------------
    pyproject = repo_path / "pyproject.toml"

    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            text = ""

        if re.search(
            r"(?m)^\s*\[tool\.pytest\.ini_options\]\s*$",
            text,
        ):
            return True

    return False


def _select_test_command(
    repo_path,
    context,
    python_executable,
):
    """
    Select a safe test command for the discovered repository.

    Repository-declared pytest configuration is authoritative. If pytest
    configuration exists, pytest itself is allowed to resolve testpaths.

    Only when no explicit pytest configuration exists do we fall back to
    the package-directory heuristic used for doctest repositories.
    """

    repo_path = Path(repo_path)

    frameworks = set(context.test_frameworks)

    if "pytest" in frameworks:
        command = [
            str(python_executable),
            "-m",
            "pytest",
            "-q",
        ]

        has_pytest_config = _has_explicit_pytest_config(repo_path)

        # ---------------------------------------------------------
        # Explicit pytest configuration
        # ---------------------------------------------------------
        #
        # Let the repository's own pytest configuration determine
        # testpaths. Do NOT append an automatically selected package.
        #
        # Example:
        #
        #   [tool.pytest.ini_options]
        #   testpaths = ["toolz"]
        #
        # pytest will correctly discover toolz/tests/... itself.
        #
        if has_pytest_config:
            if "doctest" in frameworks:
                command.append("--doctest-modules")

            return command, "pytest"

        # ---------------------------------------------------------
        # No explicit pytest configuration
        # ---------------------------------------------------------
        #
        # For doctest repositories, target a likely Python package
        # rather than recursively collecting the entire repository.
        #
        if "doctest" in frameworks:
            command.append("--doctest-modules")

            package_dir = None

            for candidate in sorted(repo_path.iterdir()):
                if not candidate.is_dir():
                    continue

                if not (candidate / "__init__.py").exists():
                    continue

                # This is our pipeline, not the target repository.
                if candidate.name == "pipeline":
                    continue

                package_dir = candidate
                break

            if package_dir is not None:
                command.append(str(package_dir))

        return command, "pytest"

    if "unittest" in frameworks:
        return [
            str(python_executable),
            "-m",
            "unittest",
            "discover",
        ], "unittest"

    return None, None


def _parse_pytest_counts(output):
    """
    Extract common pytest summary counts.

    Example:

        100 passed, 2 skipped, 1 failed in 4.21s
    """

    text = output

    passed_match = re.search(
        r"(\d+)\s+passed",
        text,
    )

    failed_match = re.search(
        r"(\d+)\s+failed",
        text,
    )

    skipped_match = re.search(
        r"(\d+)\s+skipped",
        text,
    )

    passed = int(passed_match.group(1)) if passed_match else None

    failed = int(failed_match.group(1)) if failed_match else None

    skipped = int(skipped_match.group(1)) if skipped_match else None

    counts = [value for value in (passed, failed, skipped) if value is not None]

    tests_run = sum(counts) if counts else None

    return (
        tests_run,
        passed,
        failed,
        skipped,
    )


def _run_tests(
    context,
    repo_path,
    python_executable,
):
    command, framework = _select_test_command(
        repo_path,
        context,
        python_executable,
    )

    if command is None:
        return None

    result = _run_command(
        command,
        cwd=repo_path,
    )

    combined_output = result.stdout + "\n" + result.stderr

    if framework == "pytest":
        (
            tests_run,
            tests_passed,
            tests_failed,
            tests_skipped,
        ) = _parse_pytest_counts(combined_output)

    else:
        tests_run = None
        tests_passed = None
        tests_failed = None
        tests_skipped = None

    return TestResult(
        framework=framework,
        command=command,
        passed=result.return_code == 0,
        return_code=result.return_code,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        tests_skipped=tests_skipped,
        duration_seconds=result.duration_seconds,
        stdout=result.stdout,
        stderr=result.stderr,
        interpreter=str(python_executable),
        cwd=str(repo_path),
    )


def _run_coverage(
    context,
    repo_path,
    python_executable,
):
    if "coverage.py" not in context.coverage_tools:
        return None

    repo_path = Path(repo_path)

    selected = _select_test_command(
        repo_path,
        context,
        python_executable,
    )

    if selected is None:
        return None

    test_command, framework = selected

    # Coverage support is currently implemented for pytest.
    if framework != "pytest":
        return None

    # The selected command is normally:
    #
    #   python -m pytest -q ...
    #
    # Transform it into:
    #
    #   python -m coverage run -m pytest -q ...
    #
    if len(test_command) < 3 or test_command[1] != "-m" or test_command[2] != "pytest":
        return None

    command = [
        str(python_executable),
        "-m",
        "coverage",
        "run",
        "-m",
    ]

    command.extend(test_command[2:])

    coverage_file = Path(tempfile.mkdtemp(prefix="coverage-")) / ".coverage"

    env = os.environ.copy()
    env["COVERAGE_FILE"] = str(coverage_file)

    run_result = _run_command(
        command,
        cwd=repo_path,
        env=env,
    )

    if run_result.return_code != 0:
        return CoverageResult(
            tool="coverage.py",
            command=command,
            available=True,
            passed=False,
            total_statements=None,
            covered_statements=None,
            coverage_percent=None,
            missing_statements=None,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
        )

    report_command = [
        str(python_executable),
        "-m",
        "coverage",
        "report",
        "--ignore-errors",
        "--show-missing",
        "--include",
        "glom/*",
    ]

    # The final argument of the selected pytest command is the
    # package directory discovered by _select_test_command().
    package_target = None

    for argument in reversed(test_command):
        candidate = Path(argument)

        if not candidate.is_absolute():
            candidate = repo_path / candidate

        if candidate.is_dir() and (candidate / "__init__.py").exists():
            try:
                relative_package = candidate.relative_to(repo_path)
            except ValueError:
                continue

            package_target = relative_package
            break

    if package_target is not None:
        report_command.extend(
            [
                "--include",
                f"{package_target.as_posix()}/*",
            ]
        )

    report_result = _run_command(
        report_command,
        cwd=repo_path,
        env=env,
    )

    combined_output = (
        run_result.stdout + "\n" + report_result.stdout + "\n" + report_result.stderr
    )

    total_statements = None
    covered_statements = None
    missing_statements = None
    coverage_percent = None

    match = re.search(
        r"TOTAL\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)%",
        combined_output,
    )

    if match:
        total_statements = int(match.group(1))
        missing_statements = int(match.group(2))
        coverage_percent = float(match.group(3))
        covered_statements = total_statements - missing_statements

    return CoverageResult(
        tool="coverage.py",
        command=report_command,
        available=True,
        passed=(report_result.return_code == 0 and coverage_percent is not None),
        total_statements=total_statements,
        covered_statements=covered_statements,
        coverage_percent=coverage_percent,
        missing_statements=missing_statements,
        stdout=(run_result.stdout + "\n" + report_result.stdout),
        stderr=(run_result.stderr + "\n" + report_result.stderr),
    )


def _results_are_deterministic(test_runs):
    if len(test_runs) < 2:
        return None

    first = test_runs[0]

    for current in test_runs[1:]:
        if current.passed != first.passed:
            return False

        if current.return_code != first.return_code:
            return False

        if current.tests_run != first.tests_run:
            return False

        if current.tests_passed != first.tests_passed:
            return False

        if current.tests_failed != first.tests_failed:
            return False

        if current.tests_skipped != first.tests_skipped:
            return False

    return True


def run_baseline(
    repo_path: Union[str, Path],
    context: RepoContext,
    dependency_info: DependencyInfo,
    *,
    repeat_count: int = 2,
) -> BaselineResult:
    repo_path = Path(repo_path).resolve()

    baseline = BaselineResult(
        install=None,
    )
    workspace = _prepare_repository_workspace(repo_path)

    if repeat_count < 1:
        raise ValueError("repeat_count must be at least 1")

    # ---------------------------------------------------------
    # Temporary environment
    # ---------------------------------------------------------

    venv_path = _create_virtualenv(workspace)

    python_executable = _venv_python(venv_path)

    # ---------------------------------------------------------
    # Upgrade pip
    # ---------------------------------------------------------

    pip_result = _run_command(
        [
            str(python_executable),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
        ],
        cwd=repo_path,
    )

    if pip_result.return_code != 0:
        baseline.install = pip_result

        baseline.warnings.append("Could not upgrade pip in the temporary environment.")

        baseline.overall_passed = False

        return baseline

        # ---------------------------------------------------------
    # Install repository dependencies/package
    # ---------------------------------------------------------

    install_result = _install_dependencies(
        workspace,
        dependency_info,
        python_executable,
    )

    baseline.install = install_result

    if install_result.return_code != 0:
        baseline.overall_passed = False

        baseline.warnings.append(
            "Repository installation failed."
        )

        return baseline

    # ---------------------------------------------------------
    # Install repository test/development dependencies
    # ---------------------------------------------------------

    test_dependency_result = _install_test_dependencies(
        workspace,
        python_executable,
    )

    if test_dependency_result is not None:
        baseline.overall_passed = False
        baseline.warnings.append(
            "Test/development dependency installation failed."
        )
        baseline.install = test_dependency_result
        return baseline

    # ---------------------------------------------------------
    # Ensure detected test/coverage frameworks
    # ---------------------------------------------------------

    framework_install_result = _ensure_test_frameworks(
        workspace,
        context,
        python_executable,
    )

    if framework_install_result is not None:
        baseline.overall_passed = False

        baseline.warnings.append(
            "Required test framework installation failed."
        )

        baseline.install = framework_install_result
        return baseline

    # ---------------------------------------------------------
    # Test runs
    # ---------------------------------------------------------

    for _ in range(repeat_count):
        test_result = _run_tests(
            context,
            workspace,
            python_executable,
        )

        if test_result is None:
            baseline.warnings.append(
                "No supported test framework was detected."
            )
            break

        baseline.test_runs.append(test_result)

    # ---------------------------------------------------------
    # Determinism
    # ---------------------------------------------------------

    baseline.deterministic = _results_are_deterministic(baseline.test_runs)

    # ---------------------------------------------------------
    # Coverage
    # ---------------------------------------------------------

    if baseline.test_runs and all(result.passed for result in baseline.test_runs):
        baseline.coverage = _run_coverage(
            context,
            workspace,
            python_executable,
        )

    # ---------------------------------------------------------
    # Overall result
    # ---------------------------------------------------------

    tests_passed = bool(baseline.test_runs) and all(
        result.passed for result in baseline.test_runs
    )

    coverage_ok = baseline.coverage is None or baseline.coverage.passed

    baseline.overall_passed = (
        baseline.install is not None
        and baseline.install.return_code == 0
        and tests_passed
        and baseline.deterministic is True
        and coverage_ok
    )

    return baseline