import json
from pathlib import Path
import sys
from pipeline.containerization import (
    ContainerizationInfo,
    ContainerProposal,
)
from pipeline.discover import RepoContext


def _container_test_dependencies(context: RepoContext) -> list[str]:
    """Identify test dependencies required inside the container."""
    deps = []

    test_frameworks = getattr(context, "test_frameworks", None) or []
    coverage_tools = getattr(context, "coverage_tools", None) or []

    if "pytest" in test_frameworks:
        deps.append("pytest")

    if "coverage.py" in coverage_tools:
        deps.append("coverage")

    deps.append("PyYAML")
    return deps


def _baseline_test_command(baseline, context):
    """
    Convert the successful host baseline command into a
    container-safe command.
    """

    if (
        baseline is None
        or not baseline.overall_passed
        or baseline.deterministic is not True
        or not baseline.test_runs
    ):
        return None

    command = list(baseline.test_runs[0].command)

    if not command:
        return None

    # The baseline may contain the host virtualenv interpreter.
    # Docker only has `python`.
    command[0] = "python"

    repo_root = Path(context.repo_path).resolve()

    normalized = []

    for part in command:
        part = str(part)
        candidate = Path(part)

        if candidate.is_absolute():
            try:
                relative = candidate.resolve().relative_to(repo_root)
                part = relative.as_posix()

            except ValueError:
                # Absolute path outside repository.
                # Never allow host paths into the container.
                part = candidate.name

        normalized.append(part)

    return normalized


import json


def _default_python_dockerfile(test_command, deps):
    lines = [
        "FROM python:3.10-slim",
        "",
        "RUN apt-get update && apt-get install -y --no-install-recommends git \\",
        "    && rm -rf /var/lib/apt/lists/*",
        "",
        "WORKDIR /app",
        "",
        "COPY . .",
        "",
    ]

    # Install test/runtime tooling before installing the repository.
    if deps:
        lines.append(
            "RUN python -m pip install " + " ".join(deps)
        )

    lines.extend(
        [
            "",
            "RUN python -m pip install -e .",
            "",
        ]
    )

    if test_command:
        lines.append(
            "CMD " + json.dumps(test_command)
        )
    else:
        lines.append(
            'CMD ["python", "-m", "pytest", "-q"]'
        )

    lines.append("")

    return "\n".join(lines)


def _preserve_existing(info):
    """
    Preserve the highest-priority discovered convention.
    """
    if not info.configs:
        return None

    config = info.configs[0]

    return ContainerProposal(
        action="preserve_existing",
        kind=config.kind,
        base_image=None,
        files=[config.source],
        command=config.build_command,
        reason=(
            f"Existing {config.kind} configuration detected at "
            f"{config.source}; no new container configuration is "
            "proposed."
        ),
        confidence=config.confidence,
        changes=[],
        dockerfile_content=None,
        dockerignore_content=None,  
        test_command=None,
    )


def propose_containerization(
    info: ContainerizationInfo,
    context: RepoContext,
    baseline,
):
    """
    Convert containerization discovery evidence into a safe proposal.

    This function is read-only.

    It:
      - never executes Docker
      - never creates files
      - never modifies the repository
      - preserves existing container conventions
      - proposes a default only when no convention exists
      - requires a successful deterministic baseline
    """

    # ------------------------------------------------------------
    # Existing convention
    # ------------------------------------------------------------

    if info.existing_conventions:
        proposal = _preserve_existing(info)

        if proposal is not None:
            return proposal

    # ------------------------------------------------------------
    # No proposal required
    # ------------------------------------------------------------

    if not info.default_standard_proposed:
        return ContainerProposal(
            action="none",
            kind="none",
            base_image=None,
            files=[],
            command=None,
            reason=(
                "No containerization proposal is required based "
                "on the discovered repository configuration."
            ),
            confidence="high",
            changes=[],
            dockerfile_content=None,
            dockerignore_content=None,  
        test_command=None,
        )

    # ------------------------------------------------------------
    # Ecosystem support
    # ------------------------------------------------------------

    if context.ecosystem != "python":
        return ContainerProposal(
            action="none",
            kind="unsupported",
            base_image=None,
            files=[],
            command=None,
            reason=(
                "No existing containerization convention was detected, "
                "but the repository ecosystem is not currently supported "
                "by the default container proposal."
            ),
            confidence="low",
            changes=[],
            dockerfile_content=None,
            dockerignore_content=None,
            test_command=None,
        )

    # ------------------------------------------------------------
    # Baseline gate
    # ------------------------------------------------------------

    if baseline is None or not baseline.overall_passed:
        return ContainerProposal(
            action="blocked",
            kind="dockerfile",
            base_image="python:3.10-slim",
            files=[],
            command=None,
            reason=(
                "A default container cannot be proposed safely because "
                "the repository does not have a successful baseline."
            ),
            confidence="high",
            changes=[],
            dockerfile_content=None,
            dockerignore_content=None, 
            test_command=None,
        )

    if baseline.deterministic is not True:
        return ContainerProposal(
            action="blocked",
            kind="dockerfile",
            base_image="python:3.10-slim",
            files=[],
            command=None,
            reason=(
                "A default container cannot be proposed safely because "
                "the repository baseline is not deterministic."
            ),
            confidence="high",
            changes=[],
            dockerfile_content=None,
            dockerignore_content=None,  
            test_command=None,
        )

    # ------------------------------------------------------------
    # Build default proposal
    # ------------------------------------------------------------

    test_command = _baseline_test_command(
        baseline,
        context,
    )

    deps = _container_test_dependencies(context)

    dockerfile_content = _default_python_dockerfile(
        test_command,
        deps,
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
        reason=(
            "No existing containerization convention was detected. "
            "A minimal Python Dockerfile is proposed using the "
            "successful deterministic baseline test command."
        ),
        confidence="medium",
        changes=[
            "Create Dockerfile",
            "Install the repository inside the container",
            "Install required test dependencies",
            "Run the discovered baseline test command",
        ],
        # ...
        dockerfile_content=dockerfile_content,
        test_command=test_command,
    
    )