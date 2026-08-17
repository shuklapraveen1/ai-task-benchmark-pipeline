from pipeline.dependencies import (
    discover_dependencies,
    normalize_package_name,
)
from pipeline.discover import discover_repo


def write_file(root, relative_path, content=""):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_dependency(info, name, source):
    matches = [
        dependency
        for dependency in info.dependencies
        if (dependency.name.lower() == name.lower() and dependency.source == source)
    ]

    assert len(matches) == 1

    return matches[0]


def test_setup_py_runtime_dependencies(tmp_path):
    write_file(
        tmp_path,
        "setup.py",
        """
from setuptools import setup

setup(
    name="example",
    install_requires=[
        "attrs>=19.2.0",
        "boltons==24.1.0",
        "face",
    ],
)
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    attrs = get_dependency(
        info,
        "attrs",
        "setup.py",
    )

    boltons = get_dependency(
        info,
        "boltons",
        "setup.py",
    )

    face = get_dependency(
        info,
        "face",
        "setup.py",
    )

    assert attrs.scope == "runtime"
    assert attrs.constraint == ">=19.2.0"
    assert attrs.pinned is False

    assert boltons.scope == "runtime"
    assert boltons.constraint == "==24.1.0"
    assert boltons.pinned is True

    assert face.scope == "runtime"
    assert face.constraint is None
    assert face.pinned is False


def test_setup_py_optional_dependencies(tmp_path):
    write_file(
        tmp_path,
        "setup.py",
        """
from setuptools import setup

setup(
    name="example",
    install_requires=[
        "attrs>=19.2.0",
    ],
    extras_require={
        "yaml": [
            "PyYAML==6.0.1",
        ],
        "test": [
            "pytest>=7.0",
        ],
    },
)
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    pyyaml = get_dependency(
        info,
        "PyYAML",
        "setup.py",
    )

    pytest_dependency = get_dependency(
        info,
        "pytest",
        "setup.py",
    )

    assert pyyaml.scope == "optional"
    assert pyyaml.constraint == "==6.0.1"
    assert pyyaml.pinned is True

    assert pytest_dependency.scope == "optional"
    assert pytest_dependency.constraint == ">=7.0"
    assert pytest_dependency.pinned is False


def test_requirements_in_is_development_and_unpinned(tmp_path):
    write_file(
        tmp_path,
        "requirements.in",
        """
attrs>=19.2.0
boltons>=20.2.0
coverage<=7.2.7
pytest>=6.2.5
PyYAML>=6.0.1
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    assert len(info.dependencies) == 5

    for dependency in info.dependencies:
        assert dependency.scope == "development"
        assert dependency.source == "requirements.in"
        assert dependency.pinned is False
        pyyaml = get_dependency(
            info,
            "PyYAML",
            "requirements.in",
        )
        assert pyyaml.name == "PyYAML"
        assert pyyaml.normalized_name == "pyyaml"

    assert info.has_pinned_environment is False
    assert info.pinned_sources == []


def test_requirements_txt_exact_pins(tmp_path):
    write_file(
        tmp_path,
        "requirements.txt",
        """
attrs==24.2.0
boltons==24.1.0
coverage==7.2.7
pytest==7.4.4
PyYAML==6.0.1
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    assert len(info.dependencies) == 5
    pyyaml = get_dependency(
        info,
        "pyyaml",
        "requirements.txt",
    )

    assert pyyaml.name == "PyYAML"
    assert pyyaml.normalized_name == "pyyaml"
    assert pyyaml.pinned is True

    for dependency in info.dependencies:
        assert dependency.scope == "development"
        assert dependency.source == "requirements.txt"
        assert dependency.pinned is True

    assert info.has_pinned_environment is True
    assert info.pinned_sources == ["requirements.txt"]


def test_requirements_txt_mixed_pins_are_not_fully_pinned(tmp_path):
    write_file(
        tmp_path,
        "requirements.txt",
        """
attrs==24.2.0
pytest>=7.0
coverage==7.2.7
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    attrs = get_dependency(
        info,
        "attrs",
        "requirements.txt",
    )

    pytest_dependency = get_dependency(
        info,
        "pytest",
        "requirements.txt",
    )

    assert attrs.pinned is True
    assert pytest_dependency.pinned is False

    assert info.has_pinned_environment is False
    assert info.pinned_sources == []


def test_comments_and_pip_options_are_ignored(tmp_path):
    write_file(
        tmp_path,
        "requirements.txt",
        """
# comment

-r base.txt

attrs==24.2.0
pytest==7.4.4  # exact pytest version
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    assert len(info.dependencies) == 2

    attrs = get_dependency(
        info,
        "attrs",
        "requirements.txt",
    )

    pytest_dependency = get_dependency(
        info,
        "pytest",
        "requirements.txt",
    )

    assert attrs.pinned is True
    assert pytest_dependency.pinned is True

    assert any("included requirements file" in warning for warning in info.warnings)


def test_environment_markers_do_not_destroy_pin_status(tmp_path):
    write_file(
        tmp_path,
        "requirements.txt",
        """
tomli==2.0.1; python_version < "3.11"
typing-extensions>=4.7.0; python_version < "3.12"
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    tomli = get_dependency(
        info,
        "tomli",
        "requirements.txt",
    )

    typing_extensions = get_dependency(
        info,
        "typing-extensions",
        "requirements.txt",
    )

    assert tomli.pinned is True
    assert tomli.constraint == "==2.0.1"

    assert typing_extensions.pinned is False
    assert typing_extensions.constraint == ">=4.7.0"


def test_package_name_normalization():
    assert normalize_package_name("PyYAML") == "pyyaml"
    assert normalize_package_name("typing_extensions") == "typing-extensions"
    assert normalize_package_name("My.Package") == "my-package"
    assert normalize_package_name("my-package") == "my-package"
    assert normalize_package_name("MY_PACKAGE") == "my-package"


def test_dependency_normalization(tmp_path):
    # Setup files with differently cased package names
    write_file(tmp_path, "requirements.in", "PyYAML>=6.0.1")
    write_file(tmp_path, "requirements.txt", "pyyaml==6.0.1")

    # Run discovery to generate the info object
    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    # requirements.in test
    pyyaml_in = get_dependency(info, "PyYAML", "requirements.in")
    assert pyyaml_in.normalized_name == "pyyaml"

    # requirements.txt test
    pyyaml_txt = get_dependency(info, "pyyaml", "requirements.txt")
    assert pyyaml_txt.normalized_name == "pyyaml"


def test_different_package_spellings_have_same_normalized_name(tmp_path):
    write_file(
        tmp_path,
        "requirements.in",
        """
PyYAML>=6.0.1
""",
    )

    write_file(
        tmp_path,
        "requirements.txt",
        """
pyyaml==6.0.1
""",
    )

    context = discover_repo(tmp_path)
    info = discover_dependencies(tmp_path, context)

    input_dependency = get_dependency(
        info,
        "PyYAML",
        "requirements.in",
    )

    pinned_dependency = get_dependency(
        info,
        "pyyaml",
        "requirements.txt",
    )

    assert input_dependency.normalized_name == "pyyaml"
    assert pinned_dependency.normalized_name == "pyyaml"

    assert input_dependency.pinned is False
    assert pinned_dependency.pinned is True
