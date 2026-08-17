from pathlib import Path

from pipeline.baseline import (
    BaselineResult,
    TestResult,
)
from pipeline.container_execution import (
    apply_container_proposal,
)
from pipeline.containerization import (
    ContainerProposal,
)

TestResult.__test__ = False

def make_baseline(
    passed=True,
    deterministic=True,
    tests_run=10,
    tests_passed=10,
):
    test = TestResult(
        framework="pytest",
        command=[
            "C:\\temp\\venv\\Scripts\\python.exe",
            "-m",
            "pytest",
            "-q",
            "mypackage",
        ],
        passed=passed,
        return_code=0 if passed else 1,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=(
            tests_run - tests_passed
            if tests_run is not None
            and tests_passed is not None
            else None
        ),
        tests_skipped=0,
        duration_seconds=1.0,
        stdout=(
            f"{tests_passed} passed"
            if tests_passed is not None
            else ""
        ),
        stderr="",
        interpreter="python",
        cwd=".",
    )

    return BaselineResult(
        install=None,
        test_runs=[test],
        coverage=None,
        deterministic=deterministic,
        warnings=[],
        overall_passed=passed,
    )


def make_proposal(dockerfile_content=None):
    if dockerfile_content is None:
        dockerfile_content = (
            "FROM python:3.10-slim\n"
            "RUN python -m pip install pytest\n"
            'CMD ["python", "-m", "pytest", "-q"]\n'
        )

    return ContainerProposal(
        action="introduce_default",
        kind="dockerfile",
        base_image="python:3.10-slim",
        files=["Dockerfile"],
        command=[
            "docker",
            "build",
            "-t",
            "repo-baseline",
            ".",
        ],
        reason="Synthetic default container proposal.",
        confidence="medium",
        changes=[
            "Create Dockerfile",
            "Install repository",
            "Run baseline test command",
        ],
        dockerfile_content=dockerfile_content,
        dockerignore_content=None,
        test_command=["python", "-m", "pytest", "-q"],
    )


def test_successful_container_preserves_baseline(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "package.py").write_text(
        "value = 1\n"
    )

    baseline = make_baseline()

    calls = []

    def fake_run(
        command,
        cwd,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    ):
        calls.append(command)

        if command[:2] == [
            "docker",
            "build",
        ]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "Successfully built image\n",
                    "stderr": "",
                },
            )()

        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "10 passed\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is True
    assert result.validation.validation_passed is True
    assert result.validation.regression_detected is False

    assert result.execution.image_built is True
    assert result.execution.tests_executed is True

    assert result.original_repo_untouched is True

    assert any(
        command[:2] == [
            "docker",
            "build",
        ]
        for command in calls
    )

    assert any(
        command[:2] == [
            "docker",
            "run",
        ]
        for command in calls
    )


def test_container_test_failure_is_rejected(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "package.py").write_text(
        "value = 1\n"
    )

    baseline = make_baseline()

    def fake_run(
        command,
        cwd,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    ):
        if command[:2] == [
            "docker",
            "build",
        ]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "built\n",
                    "stderr": "",
                },
            )()

        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "9 passed, 1 failed\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is False
    assert result.validation.container_tests_passed is False
    assert result.validation.validation_passed is False


def test_test_count_regression_is_rejected(
    tmp_path,
    monkeypatch,
):
    baseline = make_baseline(
        tests_run=10,
        tests_passed=10,
    )

    def fake_run(
        command,
        cwd,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    ):
        if command[:2] == [
            "docker",
            "build",
        ]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "built\n",
                    "stderr": "",
                },
            )()

        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "8 passed\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is False
    assert result.validation.regression_detected is True
    assert (
        result.validation.tests_in_container
        == 8
    )


def test_non_deterministic_baseline_is_rejected_before_docker(
    tmp_path,
    monkeypatch,
):
    baseline = make_baseline(
        deterministic=False,
    )

    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError(
            "Docker must not execute when the baseline "
            "is non-deterministic."
        )

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is False
    assert result.original_repo_untouched is True
    assert calls == []

    assert any(
        "baseline" in reason.lower()
        for reason in result.validation.reasons
    )


def test_failed_baseline_is_rejected_before_docker(
    tmp_path,
    monkeypatch,
):
    baseline = make_baseline(
        passed=False,
    )

    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError(
            "Docker must not execute when the baseline fails."
        )

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is False
    assert calls == []
    assert result.original_repo_untouched is True


def test_docker_unavailable_is_handled_gracefully(
    tmp_path,
    monkeypatch,
):
    baseline = make_baseline()

    def fake_run(
        command,
        cwd,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    ):
        raise FileNotFoundError(
            "docker was not found"
        )

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is False
    assert result.original_repo_untouched is True

    assert result.execution.image_built is False
    assert result.validation.validation_passed is False


def test_build_failure_is_rejected(
    tmp_path,
    monkeypatch,
):
    baseline = make_baseline()

    def fake_run(
        command,
        cwd,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    ):
        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "docker build failed",
            },
        )()

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is False
    assert result.execution.image_built is False
    assert result.execution.tests_executed is False


def test_original_repository_is_untouched(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.py"
    source.write_text(
        "original = True\n"
    )

    before = source.read_text()

    baseline = make_baseline()

    def fake_run(
        command,
        cwd,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    ):
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "10 passed\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.original_repo_untouched is True
    assert source.read_text() == before

    # The generated Dockerfile must not appear in the real repository.
    assert not (
        tmp_path / "Dockerfile"
    ).exists()


def test_build_timeout_is_rejected(
    tmp_path,
    monkeypatch,
):
    baseline = make_baseline()

    def fake_run(
        command,
        cwd,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    ):
        from subprocess import TimeoutExpired

        raise TimeoutExpired(
            command,
            timeout,
            output=b"",
            stderr=b"timed out",
        )

    monkeypatch.setattr(
        "pipeline.container_execution.subprocess.run",
        fake_run,
    )

    result = apply_container_proposal(
        tmp_path,
        make_proposal(),
        baseline,
    )

    assert result.accepted is False
    assert result.execution.timed_out is True
    assert result.validation.validation_passed is False

def test_execution_uses_proposal_dockerfile_verbatim(tmp_path, monkeypatch):
    proposal = make_proposal()
    baseline = make_baseline()
    written_dockerfile = None

    def fake_run(command, cwd, **kwargs):
        nonlocal written_dockerfile
        if command[:2] == ["docker", "build"]:
            written_dockerfile = (Path(cwd) / "Dockerfile").read_text(encoding="utf-8")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "10 passed\n", "stderr": ""})()

    monkeypatch.setattr("pipeline.container_execution.subprocess.run", fake_run)
    apply_container_proposal(tmp_path, proposal, baseline)

    assert written_dockerfile == proposal.dockerfile_content


def test_execution_dockerfile_contains_no_host_paths(tmp_path, monkeypatch):
    proposal = make_proposal(
        dockerfile_content=(
            "FROM python:3.10-slim\n"
            'CMD ["python", "-m", "pytest", "-q", "glom"]\n'
        )
    )
    baseline = make_baseline()
    written_dockerfile = ""

    def fake_run(command, cwd, **kwargs):
        nonlocal written_dockerfile
        if command[:2] == ["docker", "build"]:
            written_dockerfile = (Path(cwd) / "Dockerfile").read_text(encoding="utf-8")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "10 passed\n", "stderr": ""})()

    monkeypatch.setattr("pipeline.container_execution.subprocess.run", fake_run)
    apply_container_proposal(tmp_path, proposal, baseline)

    assert "C:\\projects\\" not in written_dockerfile
    assert "C:/projects/" not in written_dockerfile


def test_execution_preserves_test_dependencies(tmp_path, monkeypatch):
    proposal = make_proposal(
        dockerfile_content=(
            "FROM python:3.10-slim\n"
            "RUN python -m pip install pytest coverage\n"
        )
    )
    baseline = make_baseline()
    written_dockerfile = ""

    def fake_run(command, cwd, **kwargs):
        nonlocal written_dockerfile
        if command[:2] == ["docker", "build"]:
            written_dockerfile = (Path(cwd) / "Dockerfile").read_text(encoding="utf-8")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "10 passed\n", "stderr": ""})()

    monkeypatch.setattr("pipeline.container_execution.subprocess.run", fake_run)
    apply_container_proposal(tmp_path, proposal, baseline)

    assert "pip install pytest" in written_dockerfile