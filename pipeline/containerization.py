from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ContainerConfig:
    kind: str
    source: str
    dockerfile: Optional[str]
    compose_file: Optional[str]
    build_command: Optional[list]
    test_command: Optional[list]
    confidence: str


@dataclass
class ContainerizationInfo:
    configs: list[ContainerConfig]

    dockerfiles: list[str]
    compose_files: list[str]

    existing_conventions: bool
    default_standard_proposed: bool

    warnings: list[str]


@dataclass
class ContainerProposal:
    action: str
    kind: str
    base_image: Optional[str]

    files: list[str]
    command: Optional[list]

    reason: str
    confidence: str

    changes: list[str]
    dockerfile_content: Optional[str] = None
    dockerignore_content: Optional[str] = None
    test_command: Optional[list[str]] = None


@dataclass
class ContainerChange:
    action: str
    kind: str

    files: list[str]

    dockerfile_content: Optional[str]
    dockerignore_content: Optional[str]

    build_command: list
    test_command: list

    reason: str
    confidence: str

    mutates_files: bool


@dataclass
class ContainerExecution:
    change: ContainerChange

    build_command: list
    test_command: list

    build_return_code: Optional[int]
    test_return_code: Optional[int]

    build_stdout: str
    build_stderr: str

    test_stdout: str
    test_stderr: str

    build_duration_seconds: float
    test_duration_seconds: float

    image_built: bool
    tests_executed: bool

    timed_out: bool

    changed_files: list[str]

    applied: bool


@dataclass
class ContainerValidation:
    baseline_passed: bool
    container_build_passed: bool
    container_tests_passed: bool

    baseline_deterministic: bool

    tests_before: Optional[int]
    tests_in_container: Optional[int]

    passed_before: Optional[int]
    passed_in_container: Optional[int]

    failed_before: Optional[int]
    failed_in_container: Optional[int]

    skipped_before: Optional[int]
    skipped_in_container: Optional[int]

    regression_detected: bool

    validation_passed: bool

    reasons: list[str]


@dataclass
class ContainerResult:
    proposal: ContainerProposal
    change: ContainerChange
    execution: ContainerExecution
    validation: ContainerValidation

    accepted: bool

    rolled_back: bool
    rollback_successful: Optional[bool]

    original_repo_untouched: bool

    warnings: list[str]


_DOCKERFILE_NAMES = {
    "Dockerfile",
    "dockerfile",
}

_COMPOSE_NAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}

_GENERATED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".nox",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def _is_generated_path(path: Path, repo_path: Path) -> bool:
    """
    Return True when a discovered file lives inside a generated/
    environment/build directory.

    Discovery must never treat generated artifacts as repository
    conventions.
    """
    try:
        relative = path.relative_to(repo_path)
    except ValueError:
        return True

    return any(
        part in _GENERATED_DIRS
        for part in relative.parts[:-1]
    )


def _relative_path(path: Path, repo_path: Path) -> str:
    return path.relative_to(repo_path).as_posix()


def _find_dockerfiles(repo_path: Path) -> list[Path]:
    results = []

    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue

        if _is_generated_path(path, repo_path):
            continue

        if path.name in _DOCKERFILE_NAMES:
            results.append(path)

    return sorted(results)


def _find_compose_files(repo_path: Path) -> list[Path]:
    results = []

    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue

        if _is_generated_path(path, repo_path):
            continue

        if path.name.lower() in _COMPOSE_NAMES:
            results.append(path)

    return sorted(results)


def _dockerfile_config(
    path: Path,
    repo_path: Path,
) -> ContainerConfig:
    relative = _relative_path(path, repo_path)

    return ContainerConfig(
        kind="dockerfile",
        source=relative,
        dockerfile=relative,
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


def _compose_config(
    path: Path,
    repo_path: Path,
) -> ContainerConfig:
    relative = _relative_path(path, repo_path)

    return ContainerConfig(
        kind="compose",
        source=relative,
        dockerfile=None,
        compose_file=relative,
        build_command=[
            "docker",
            "compose",
            "-f",
            relative,
            "build",
        ],
        test_command=None,
        confidence="explicit",
    )


def discover_containerization(
    repo_path,
    context,
):
    """
    Discover existing containerization conventions.

    This function is intentionally read-only.

    It:
      - detects Dockerfiles
      - detects Docker Compose files
      - ignores generated/build/environment directories
      - does not create or modify files
      - does not execute Docker
      - proposes a default only when no convention exists

    The returned ContainerizationInfo is evidence only. It does not
    represent an approved mutation.
    """

    repo_path = Path(repo_path).resolve()

    dockerfiles = _find_dockerfiles(repo_path)
    compose_files = _find_compose_files(repo_path)

    configs = []

    for path in dockerfiles:
        configs.append(
            _dockerfile_config(
                path,
                repo_path,
            )
        )

    for path in compose_files:
        configs.append(
            _compose_config(
                path,
                repo_path,
            )
        )

    configs.sort(key=lambda item: item.source)

    existing_conventions = bool(configs)
    default_standard_proposed = not existing_conventions

    warnings = []

    if not existing_conventions:
        warnings.append(
            "No existing containerization convention was detected."
        )

    return ContainerizationInfo(
        configs=configs,
        dockerfiles=[
            _relative_path(path, repo_path)
            for path in dockerfiles
        ],
        compose_files=[
            _relative_path(path, repo_path)
            for path in compose_files
        ],
        existing_conventions=existing_conventions,
        default_standard_proposed=default_standard_proposed,
        warnings=warnings,
    )