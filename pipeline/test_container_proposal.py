from pathlib import Path

from pipeline.containerization import (
    ContainerConfig,
    ContainerizationInfo,
    ContainerProposal,
)
from pipeline.container_proposal import (
    propose_containerization,
)
from pipeline.discover import RepoContext
from pipeline.baseline import (
    BaselineResult,
    TestResult as BaselineTestResult,
)

BaselineTestResult.__test__ = False

def make_context(tmp_path):
    return RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )

def make_python_context():
    return RepoContext(
        repo_path=".",
        ecosystem="python",
        test_frameworks=["pytest"],
        coverage_tools=["coverage.py"],
    )

def make_unconfigured_info():
    return ContainerizationInfo(
        configs=[],
        dockerfiles=[],
        compose_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[],
    )

def make_baseline(
    command=None,
    passed=True,
    deterministic=True,
):
    if command is None:
        command = [
            "C:\\temp\\venv\\Scripts\\python.exe",
            "-m",
            "pytest",
            "-q",
            "--doctest-modules",
            "mypackage",
        ]

    test_result = BaselineTestResult(
        framework="pytest",
        command=command,
        passed=passed,
        return_code=0 if passed else 1,
        tests_run=10,
        tests_passed=10 if passed else 9,
        tests_failed=None if passed else 1,
        tests_skipped=0,
        duration_seconds=1.0,
        stdout="10 passed",
        stderr="",
        interpreter=command[0],
        cwd=".",
    )

    return BaselineResult(
        install=None,
        test_runs=[test_result],
        coverage=None,
        deterministic=deterministic,
        warnings=[],
        overall_passed=passed,
    )


def test_existing_dockerfile_is_preserved(tmp_path):
    info = ContainerizationInfo(
        configs=[
            ContainerConfig(
                kind="dockerfile",
                source="Dockerfile",
                dockerfile="Dockerfile",
                compose_file=None,
                build_command=[
                    "docker",
                    "build",
                    "-t",
                    "repo-baseline",
                    ".",
                ],
                test_command=None,
                confidence="explicit",
            )
        ],
        dockerfiles=["Dockerfile"],
        compose_files=[],
        existing_conventions=True,
        default_standard_proposed=False,
        warnings=[],
    )

    baseline = make_baseline()

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    assert proposal.action == "preserve_existing"
    assert proposal.kind == "dockerfile"
    assert proposal.confidence == "explicit"

    assert proposal.files == ["Dockerfile"]
    assert proposal.changes == []


def test_unconfigured_python_repo_proposes_default(tmp_path):
    info = ContainerizationInfo(
        configs=[],
        dockerfiles=[],
        compose_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[
            "No existing containerization convention was detected."
        ],
    )

    baseline = make_baseline()

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    assert proposal.action == "introduce_default"
    assert proposal.kind == "dockerfile"

    assert proposal.base_image == "python:3.10-slim"

    assert proposal.files == [
        "Dockerfile",
    ]

    assert proposal.command == [
        "docker",
        "build",
        "-t",
        "repo-baseline",
        ".",
    ]

    assert proposal.confidence == "medium"

    assert "Dockerfile" in proposal.changes[0]


def test_default_proposal_reuses_baseline_test_command(tmp_path):
    info = ContainerizationInfo(
        configs=[],
        dockerfiles=[],
        compose_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[],
    )

    baseline_command = [
        "C:\\temp\\repo-venv\\Scripts\\python.exe",
        "-m",
        "pytest",
        "-q",
        "--doctest-modules",
        "mypackage",
    ]

    baseline = make_baseline(
        command=baseline_command,
    )

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    assert proposal.action == "introduce_default"

    # The proposal itself exposes the Docker build command.
    assert proposal.command == [
        "docker",
        "build",
        "-t",
        "repo-baseline",
        ".",
    ]

    # The generated change description must indicate that the
    # discovered baseline command is reused.
    assert any(
        "baseline test command" in change
        for change in proposal.changes
    )


def test_failed_baseline_blocks_default_container(tmp_path):
    info = ContainerizationInfo(
        configs=[],
        dockerfiles=[],
        compose_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[],
    )

    baseline = make_baseline(
        passed=False,
    )

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    assert proposal.action == "blocked"
    assert proposal.kind == "dockerfile"
    assert proposal.command is None
    assert proposal.files == []


def test_non_deterministic_baseline_blocks_default_container(tmp_path):
    info = ContainerizationInfo(
        configs=[],
        dockerfiles=[],
        compose_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[],
    )

    baseline = make_baseline(
        deterministic=False,
    )

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    assert proposal.action == "blocked"
    assert proposal.kind == "dockerfile"
    assert proposal.command is None
    assert proposal.files == []


def test_existing_compose_is_preserved(tmp_path):
    info = ContainerizationInfo(
        configs=[
            ContainerConfig(
                kind="compose",
                source="docker-compose.yml",
                dockerfile=None,
                compose_file="docker-compose.yml",
                build_command=[
                    "docker",
                    "compose",
                    "-f",
                    "docker-compose.yml",
                    "build",
                ],
                test_command=None,
                confidence="explicit",
            )
        ],
        dockerfiles=[],
        compose_files=["docker-compose.yml"],
        existing_conventions=True,
        default_standard_proposed=False,
        warnings=[],
    )

    baseline = make_baseline()

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    assert proposal.action == "preserve_existing"
    assert proposal.kind == "compose"
    assert proposal.files == [
        "docker-compose.yml"
    ]
    assert proposal.changes == []


def test_proposal_does_not_create_files(tmp_path):
    info = ContainerizationInfo(
        configs=[],
        dockerfiles=[],
        compose_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[],
    )

    baseline = make_baseline()

    before = sorted(
        path.relative_to(tmp_path)
        for path in tmp_path.rglob("*")
    )

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    after = sorted(
        path.relative_to(tmp_path)
        for path in tmp_path.rglob("*")
    )

    assert proposal.action == "introduce_default"
    assert before == after
    assert not (tmp_path / "Dockerfile").exists()


def test_proposal_does_not_execute_docker(tmp_path, monkeypatch):
    info = ContainerizationInfo(
        configs=[],
        dockerfiles=[],
        compose_files=[],
        existing_conventions=False,
        default_standard_proposed=True,
        warnings=[],
    )

    baseline = make_baseline()

    executed = []

    def fake_run(*args, **kwargs):
        executed.append((args, kwargs))
        raise AssertionError(
            "Docker must never execute during proposal generation"
        )

    monkeypatch.setattr(
        "subprocess.run",
        fake_run,
    )

    proposal = propose_containerization(
        info,
        make_context(tmp_path),
        baseline,
    )

    assert proposal.action == "introduce_default"
    assert executed == []

def test_default_python_container_installs_pytest(tmp_path):
    context = make_python_context()

    baseline = make_baseline(
        passed=True,
        deterministic=True,
    )

    info = make_unconfigured_info()

    proposal = propose_containerization(
        info,
        context,
        baseline,
    )

    assert proposal.action == "introduce_default"

    # Adapt this assertion to wherever your generated Dockerfile
    # content is represented.
    # Extract the Dockerfile string from the changes dictionary:
    dockerfile = proposal.dockerfile_content

    # Then assert against `dockerfile`:
    assert "pytest" in dockerfile
    assert "pip install pytest" in dockerfile


def test_default_container_does_not_embed_host_paths(tmp_path):
    context = make_python_context()

    baseline = make_baseline(
        passed=True,
        deterministic=True,
    )

    info = make_unconfigured_info()

    proposal = propose_containerization(
        info,
        context,
        baseline,
    )

    dockerfile = proposal.dockerfile_content

    assert "C:\\" not in dockerfile
    assert "C:/projects" not in dockerfile
    assert "pytest" in dockerfile


def test_default_container_uses_json_cmd(tmp_path):
    context = make_python_context()

    baseline = make_baseline(
        passed=True,
        deterministic=True,
    )

    info = make_unconfigured_info()

    proposal = propose_containerization(
        info,
        context,
        baseline,
    )

    dockerfile = proposal.dockerfile_content

    assert 'CMD ["python", "-m", "pytest", "-q", "--doctest-modules", "mypackage"]' in dockerfile