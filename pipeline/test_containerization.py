from pathlib import Path

from pipeline.containerization import discover_containerization
from pipeline.discover import RepoContext


def make_context(tmp_path):
    return RepoContext(
        repo_path=str(tmp_path),
        ecosystem="python",
    )


def test_existing_dockerfile_is_detected(tmp_path):
    dockerfile = tmp_path / "Dockerfile"

    dockerfile.write_text(
        "FROM python:3.10-slim\n"
        "CMD [\"pytest\"]\n"
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    assert info.existing_conventions is True
    assert info.default_standard_proposed is False

    assert info.dockerfiles == ["Dockerfile"]
    assert info.compose_files == []

    assert len(info.configs) == 1

    config = info.configs[0]

    assert config.kind == "dockerfile"
    assert config.source == "Dockerfile"
    assert config.dockerfile == "Dockerfile"
    assert config.compose_file is None
    assert config.confidence == "explicit"

    assert config.build_command == [
        "docker",
        "build",
        "-t",
        "repo-baseline",
        ".",
    ]


def test_existing_docker_compose_is_detected(tmp_path):
    compose = tmp_path / "docker-compose.yml"

    compose.write_text(
        """
services:
  app:
    build: .
"""
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    assert info.existing_conventions is True
    assert info.default_standard_proposed is False

    assert info.dockerfiles == []
    assert info.compose_files == [
        "docker-compose.yml"
    ]

    assert len(info.configs) == 1

    config = info.configs[0]

    assert config.kind == "compose"
    assert config.source == "docker-compose.yml"
    assert config.compose_file == "docker-compose.yml"
    assert config.dockerfile is None
    assert config.confidence == "explicit"

    assert config.build_command == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "build",
    ]


def test_unconfigured_repository_proposes_default(tmp_path):
    package = tmp_path / "mypackage"
    package.mkdir()

    (package / "__init__.py").write_text(
        '"""Example package."""\n'
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    assert info.configs == []
    assert info.dockerfiles == []
    assert info.compose_files == []

    assert info.existing_conventions is False
    assert info.default_standard_proposed is True

    assert any(
        "No existing containerization convention"
        in warning
        for warning in info.warnings
    )


def test_generated_build_dist_directories_are_ignored(tmp_path):
    build = tmp_path / "build"
    dist = tmp_path / "dist"

    build.mkdir()
    dist.mkdir()

    (build / "Dockerfile").write_text(
        "FROM python:3.10\n"
    )

    (dist / "docker-compose.yml").write_text(
        """
services:
  generated:
    build: .
"""
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    assert info.configs == []
    assert info.dockerfiles == []
    assert info.compose_files == []

    assert info.existing_conventions is False
    assert info.default_standard_proposed is True


def test_nested_real_dockerfile_is_detected(tmp_path):
    deployment = tmp_path / "deployment"
    deployment.mkdir()

    dockerfile = deployment / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.10-slim\n"
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    assert info.existing_conventions is True
    assert info.dockerfiles == [
        "deployment/Dockerfile"
    ]

    config = info.configs[0]

    assert config.source == "deployment/Dockerfile"
    assert config.dockerfile == "deployment/Dockerfile"


def test_compose_yaml_is_detected(tmp_path):
    compose = tmp_path / "compose.yaml"

    compose.write_text(
        """
services:
  app:
    image: python:3.10
"""
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    assert info.existing_conventions is True
    assert info.compose_files == ["compose.yaml"]

    config = info.configs[0]

    assert config.kind == "compose"
    assert config.confidence == "explicit"


def test_multiple_container_conventions_are_preserved(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    compose = tmp_path / "docker-compose.yml"

    dockerfile.write_text(
        "FROM python:3.10-slim\n"
    )

    compose.write_text(
        """
services:
  app:
    build: .
"""
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    assert info.existing_conventions is True
    assert info.default_standard_proposed is False

    assert set(info.dockerfiles) == {"Dockerfile"}
    assert set(info.compose_files) == {
        "docker-compose.yml"
    }

    assert len(info.configs) == 2

    kinds = {
        config.kind
        for config in info.configs
    }

    assert kinds == {
        "dockerfile",
        "compose",
    }


def test_discovery_does_not_modify_repository(tmp_path):
    dockerfile = tmp_path / "Dockerfile"

    original = (
        "FROM python:3.10-slim\n"
    )

    dockerfile.write_text(original)

    before_files = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
        if path.is_file()
    )

    info = discover_containerization(
        tmp_path,
        make_context(tmp_path),
    )

    after_files = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
        if path.is_file()
    )

    assert info.existing_conventions is True
    assert before_files == after_files
    assert dockerfile.read_text() == original