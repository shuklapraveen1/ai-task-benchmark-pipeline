from pathlib import Path

from pipeline.discover import discover_repo


def write_file(root, relative_path, content=""):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_python_repository_detection(tmp_path):
    write_file(
        tmp_path,
        "setup.py",
        """
from setuptools import setup

setup(
    name="example",
    install_requires=["pytest"],
)
""",
    )

    write_file(
        tmp_path,
        "pytest.ini",
        """
[pytest]
testpaths = tests
""",
    )

    write_file(
        tmp_path,
        "tests/test_example.py",
        """
def test_example():
    assert 1 + 1 == 2
""",
    )

    context = discover_repo(tmp_path)

    assert context.ecosystem == "python"
    assert "setup.py" in context.package_files
    assert "pytest.ini" in context.test_config_files
    assert "pytest" in context.test_frameworks


def test_doctest_detection(tmp_path):
    write_file(
        tmp_path,
        "pytest.ini",
        """
[pytest]
doctest_optionflags = NORMALIZE_WHITESPACE
""",
    )

    context = discover_repo(tmp_path)

    assert "pytest" in context.test_frameworks
    assert "doctest" in context.test_frameworks


def test_generated_files_are_ignored(tmp_path):
    write_file(
        tmp_path,
        "setup.py",
        "from setuptools import setup\nsetup(name='example')",
    )

    write_file(
        tmp_path,
        ".coverage",
        "generated coverage data",
    )

    write_file(
        tmp_path,
        ".pytest_cache/CACHEDIR.TAG",
        "generated pytest data",
    )

    write_file(
        tmp_path,
        "example.egg-info/PKG-INFO",
        "generated package metadata",
    )

    context = discover_repo(tmp_path)

    assert ".coverage" not in context.discovered_files

    assert not any(
        path.startswith(".pytest_cache/") for path in context.discovered_files
    )

    assert not any(".egg-info/" in path for path in context.discovered_files)


def test_unittest_repository_is_not_called_pytest(tmp_path):
    write_file(
        tmp_path,
        "setup.py",
        """
from setuptools import setup

setup(
    name="example",
)
""",
    )

    write_file(
        tmp_path,
        "tests/test_example.py",
        """
import unittest


class TestExample(unittest.TestCase):
    def test_example(self):
        self.assertEqual(1 + 1, 2)
""",
    )

    context = discover_repo(tmp_path)

    assert "pytest" not in context.test_frameworks


def test_git_information_is_optional(tmp_path):
    write_file(
        tmp_path,
        "setup.py",
        "from setuptools import setup\nsetup(name='example')",
    )

    context = discover_repo(tmp_path)

    assert context.git_commit is None or isinstance(
        context.git_commit,
        str,
    )
