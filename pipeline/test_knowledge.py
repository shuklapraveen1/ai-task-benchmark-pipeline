# test_knowledge.py
import json
from pathlib import Path

from pipeline.knowledge import (
    CallEdge,
    ImportEdge,
    InheritanceEdge,
    ModuleNode,
    SymbolNode,
    emit_okf,
    parse_python_source_tree,
)



def test_python_files_are_parsed_into_modules_and_symbols(tmp_path):
    package = tmp_path / "example"
    package.mkdir()

    (package / "__init__.py").write_text(
        "from .core import public_function\n",
        encoding="utf-8",
    )

    (package / "core.py").write_text(
        """
CONSTANT = 42

def public_function(value):
    return value + 1

def _private_function():
    return 0

class PublicClass:
    def method(self):
        return 1

class _PrivateClass:
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    module_ids = {
        module.id
        for module in result.modules
    }

    assert "module:example" in module_ids
    assert "module:example.core" in module_ids

    symbol_ids = {
        symbol.id
        for symbol in result.symbols
    }

    assert (
        "function:example.core.public_function"
        in symbol_ids
    )

    assert (
        "function:example.core._private_function"
        in symbol_ids
    )

    assert (
        "class:example.core.PublicClass"
        in symbol_ids
    )

    assert (
        "class:example.core._PrivateClass"
        in symbol_ids
    )

    assert (
        "constant:example.core.CONSTANT"
        in symbol_ids
    )


def test_public_and_private_symbols_are_classified_correctly(
    tmp_path,
):
    source = tmp_path / "example.py"

    source.write_text(
        """
public_function = 1
_private_function = 2
__dunder__ = 3

class PublicClass:
    pass

class _PrivateClass:
    pass

def public_function_two():
    pass

def _private_function_two():
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    symbols = {
        symbol.name: symbol
        for symbol in result.symbols
    }

    assert (
        symbols["public_function"].visibility
        == "public"
    )

    assert (
        symbols["_private_function"].visibility
        == "private"
    )

    assert (
        symbols["__dunder__"].visibility
        == "dunder"
    )

    assert (
        symbols["PublicClass"].visibility
        == "public"
    )

    assert (
        symbols["_PrivateClass"].visibility
        == "private"
    )

    assert (
        symbols["public_function_two"].visibility
        == "public"
    )

    assert (
        symbols["_private_function_two"].visibility
        == "private"
    )


def test_parse_failure_becomes_diagnostic_without_crashing(
    tmp_path,
):
    valid = tmp_path / "valid.py"
    invalid = tmp_path / "invalid.py"

    valid.write_text(
        """
def valid_function():
    return 1
""",
        encoding="utf-8",
    )

    invalid.write_text(
        """
def broken_function(
    return 1
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.warnings

    assert len(result.diagnostics) == 1

    diagnostic = result.diagnostics[0]

    assert diagnostic.path == "invalid.py"
    assert diagnostic.line is not None
    assert diagnostic.error

    module_ids = {
        module.id
        for module in result.modules
    }

    assert "module:valid" in module_ids
    assert "module:invalid" not in module_ids

    symbol_ids = {
        symbol.id
        for symbol in result.symbols
    }

    assert (
        "function:valid.valid_function"
        in symbol_ids
    )


def test_parser_does_not_execute_repository_code(
    tmp_path,
):
    source = tmp_path / "danger.py"

    marker = tmp_path / "executed.txt"

    source.write_text(
        f"""
from pathlib import Path

Path({str(marker)!r}).write_text("executed")

def hello():
    return 1
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    assert not marker.exists()


def test_generated_directories_are_ignored(
    tmp_path,
):
    source = tmp_path / "real.py"
    source.write_text(
        "def real():\n    return 1\n",
        encoding="utf-8",
    )

    build = tmp_path / "build"
    build.mkdir()

    (build / "generated.py").write_text(
        "def generated():\n    return 1\n",
        encoding="utf-8",
    )

    dist = tmp_path / "dist"
    dist.mkdir()

    (dist / "artifact.py").write_text(
        "def artifact():\n    return 1\n",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    module_paths = {
        module.path
        for module in result.modules
    }

    assert "real.py" in module_paths
    assert "build/generated.py" not in module_paths
    assert "dist/artifact.py" not in module_paths


def test_pipeline_internal_directories_are_ignored(tmp_path):
    real = tmp_path / "real.py"
    real.write_text(
        "def real():\n    return 1\n",
        encoding="utf-8",
    )

    probe = tmp_path / ".pipeline_history_probe"
    snapshot = probe / "abc123" / "input"
    snapshot.mkdir(parents=True)

    (snapshot / "generated.py").write_text(
        "def generated():\n    return 1\n",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    module_paths = {
        module.path
        for module in result.modules
    }

    assert "real.py" in module_paths
    assert (
        ".pipeline_history_probe/abc123/input/generated.py"
        not in module_paths
    )



def test_graph_input_is_strictly_deterministic(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "from .alpha import Alpha\n",
        encoding="utf-8",
    )

    (package / "alpha.py").write_text(
        """
class Alpha:
    def run(self, value):
        return value

def public_function():
    return 1

def _private_function():
    return 2
""",
        encoding="utf-8",
    )

    first = parse_python_source_tree(tmp_path)
    second = parse_python_source_tree(tmp_path)

    def canonical(result):
        return json.dumps(
            {
                "schema_version": result.schema_version,
                "modules": [
                    vars(module)
                    for module in result.modules
                ],
                "symbols": [
                    vars(symbol)
                    for symbol in result.symbols
                ],
                "diagnostics": [
                    vars(diagnostic)
                    for diagnostic in result.diagnostics
                ],
                "warnings": result.warnings,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    assert canonical(first) == canonical(second)


def test_module_metadata_is_normalized(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()

    source = package / "__init__.py"

    source.write_text(
        """
import os
import sys

VALUE = 1

def public_api():
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert len(result.modules) == 1

    module = result.modules[0]

    assert module.id == "module:pkg"
    assert module.path == "pkg/__init__.py"
    assert module.module_name == "pkg"
    assert module.package == "pkg"
    assert module.is_package is True
    assert module.is_test is False

    assert module.imports == ["os", "sys"]

    assert (
        "pkg.public_api"
        in module.public_symbols
    )

    assert (
        "pkg.VALUE"
        in module.public_symbols
    )

# ---------------------------------------------------------------------------
# Synthetic Batch 2 Tests
# ---------------------------------------------------------------------------

def test_absolute_import_is_resolved(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "base.py").write_text(
        """
class Base:
    pass
""",
        encoding="utf-8",
    )

    (package / "child.py").write_text(
        """
from pkg.base import Base

class Child(Base):
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    assert len(result.imports) == 1

    edge = result.imports[0]

    assert edge.source == "module:pkg.child"
    assert edge.target == "module:pkg.base"
    assert edge.kind == "import"
    assert edge.resolved is True

    assert len(result.inheritance) == 1

    inheritance = result.inheritance[0]

    assert (
        inheritance.source
        == "class:pkg.child.Child"
    )

    assert (
        inheritance.target
        == "class:pkg.base.Base"
    )

    assert inheritance.resolved is True
    assert inheritance.confidence == "high"


def test_single_dot_relative_import_is_resolved(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "core.py").write_text(
        """
class Core:
    pass
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
from .core import Core

class Consumer(Core):
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    assert len(result.imports) == 1

    edge = result.imports[0]

    assert edge.source == "module:pkg.consumer"
    assert edge.target == "module:pkg.core"
    assert edge.kind == "import"
    assert edge.resolved is True

    assert len(result.inheritance) == 1

    inheritance = result.inheritance[0]

    assert (
        inheritance.source
        == "class:pkg.consumer.Consumer"
    )

    assert (
        inheritance.target
        == "class:pkg.core.Core"
    )


def test_parent_relative_import_is_resolved(
    tmp_path,
):
    pkg = tmp_path / "pkg"
    sub = pkg / "sub"

    sub.mkdir(parents=True)

    (pkg / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (sub / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (pkg / "utils.py").write_text(
        """
class Utility:
    pass
""",
        encoding="utf-8",
    )

    (sub / "consumer.py").write_text(
        """
from ..utils import Utility

class Consumer(Utility):
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    assert len(result.imports) == 1

    edge = result.imports[0]

    assert edge.source == "module:pkg.sub.consumer"
    assert edge.target == "module:pkg.utils"
    assert edge.kind == "import"
    assert edge.resolved is True

    assert len(result.inheritance) == 1

    inheritance = result.inheritance[0]

    assert (
        inheritance.source
        == "class:pkg.sub.consumer.Consumer"
    )

    assert (
        inheritance.target
        == "class:pkg.utils.Utility"
    )


def test_module_import_resolves_to_module_node(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "utils.py").write_text(
        """
VALUE = 1
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
import pkg.utils
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert len(result.imports) == 1

    edge = result.imports[0]

    assert edge.source == "module:pkg.consumer"
    assert edge.target == "module:pkg.utils"
    assert edge.resolved is True


def test_aliased_module_import_is_resolved(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "utils.py").write_text(
        """
class Utility:
    pass
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
import pkg.utils as utils

class Consumer(utils.Utility):
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    inheritance = result.inheritance

    assert len(inheritance) == 1

    edge = inheritance[0]

    assert (
        edge.source
        == "class:pkg.consumer.Consumer"
    )

    assert (
        edge.target
        == "class:pkg.utils.Utility"
    )

    assert edge.resolved is True


def test_same_module_inheritance_is_resolved(
    tmp_path,
):
    source = tmp_path / "models.py"

    source.write_text(
        """
class Base:
    pass

class Child(Base):
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    assert len(result.inheritance) == 1

    edge = result.inheritance[0]

    assert (
        edge.source
        == "class:models.Child"
    )

    assert (
        edge.target
        == "class:models.Base"
    )

    assert edge.resolved is True
    assert edge.confidence == "high"


def test_external_inheritance_is_not_fatal(
    tmp_path,
):
    source = tmp_path / "models.py"

    source.write_text(
        """
class Local:
    pass

class Child(ExternalLibraryBase):
    pass
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics
    assert result.inheritance == []


def test_relationships_are_deterministically_ordered(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "a.py").write_text(
        """
class A:
    pass
""",
        encoding="utf-8",
    )

    (package / "b.py").write_text(
        """
class B:
    pass
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
from .b import B
from .a import A

class ConsumerA(A):
    pass

class ConsumerB(B):
    pass
""",
        encoding="utf-8",
    )

    first = parse_python_source_tree(tmp_path)
    second = parse_python_source_tree(tmp_path)

    first_imports = [
        (
            edge.source,
            edge.target,
            edge.kind,
            edge.imported_names,
        )
        for edge in first.imports
    ]

    second_imports = [
        (
            edge.source,
            edge.target,
            edge.kind,
            edge.imported_names,
        )
        for edge in second.imports
    ]

    assert first_imports == second_imports

    first_inheritance = [
        (
            edge.source,
            edge.target,
        )
        for edge in first.inheritance
    ]

    second_inheritance = [
        (
            edge.source,
            edge.target,
        )
        for edge in second.inheritance
    ]

    assert first_inheritance == second_inheritance

# ---------------------------------------------------------------------------
# Synthetic Batch 3 Tests
# ---------------------------------------------------------------------------


def test_direct_same_module_call_is_resolved(tmp_path):
    source = tmp_path / "example.py"

    source.write_text(
        """
def helper():
    return 1


def main():
    return helper()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics
    assert len(result.calls) == 1

    edge = result.calls[0]

    assert edge.source == "function:example.main"
    assert edge.target == "function:example.helper"
    assert edge.resolved is True
    assert edge.confidence == "high"
    assert edge.resolution == "same_module"
    assert edge.line > 0


def test_imported_function_call_is_resolved(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "utils.py").write_text(
        """
def helper():
    return 1
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
from pkg.utils import helper


def main():
    return helper()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics
    assert len(result.calls) == 1

    edge = result.calls[0]

    assert edge.source == "function:pkg.consumer.main"
    assert edge.target == "function:pkg.utils.helper"
    assert edge.resolved is True
    assert edge.confidence == "high"
    assert edge.resolution == "import"


def test_aliased_imported_function_call_is_resolved(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "utils.py").write_text(
        """
def helper():
    return 1
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
from pkg.utils import helper as h


def main():
    return h()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics
    assert len(result.calls) == 1

    edge = result.calls[0]

    assert edge.source == "function:pkg.consumer.main"
    assert edge.target == "function:pkg.utils.helper"
    assert edge.resolved is True
    assert edge.confidence == "high"
    assert edge.resolution == "import"


def test_imported_module_function_call_is_resolved(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "utils.py").write_text(
        """
def helper():
    return 1
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
import pkg.utils as utils


def main():
    return utils.helper()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics
    assert len(result.calls) == 1

    edge = result.calls[0]

    assert edge.source == "function:pkg.consumer.main"
    assert edge.target == "function:pkg.utils.helper"
    assert edge.resolved is True
    assert edge.resolution == "imported_module"

def test_same_class_method_call_is_resolved(tmp_path):
    source = tmp_path / "models.py"

    source.write_text(
        """
class Service:

    def helper(self):
        return 1

    def run(self):
        return self.helper()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics
    assert len(result.calls) == 1

    edge = result.calls[0]

    assert edge.source == "method:models.Service.run"
    assert edge.target == "method:models.Service.helper"
    assert edge.resolved is True
    assert edge.confidence == "medium"
    assert edge.resolution == "same_class_method"

def test_dynamic_call_is_not_fabricated(tmp_path):
    source = tmp_path / "dynamic.py"

    source.write_text(
        """
def main(factory):
    obj = factory()
    return obj.run()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    assert not result.diagnostics

    assert len(result.calls) == 2

    dynamic_edges = [
        edge
        for edge in result.calls
        if not edge.resolved
    ]

    assert dynamic_edges

    for edge in dynamic_edges:
        assert edge.resolved is False
        assert edge.confidence == "low"
        assert edge.target is None

def test_call_graph_is_strictly_deterministic(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "utils.py").write_text(
        """
def alpha():
    return 1


def beta():
    return 2
""",
        encoding="utf-8",
    )

    (package / "consumer.py").write_text(
        """
from pkg.utils import alpha as a
from pkg.utils import beta as b


def main():
    a()
    b()
""",
        encoding="utf-8",
    )

    first = parse_python_source_tree(tmp_path)
    second = parse_python_source_tree(tmp_path)

    first_calls = [
        (
            edge.source,
            edge.target,
            edge.resolved,
            edge.confidence,
            edge.resolution,
            edge.line,
        )
        for edge in first.calls
    ]

    second_calls = [
        (
            edge.source,
            edge.target,
            edge.resolved,
            edge.confidence,
            edge.resolution,
            edge.line,
        )
        for edge in second.calls
    ]

    assert first_calls == second_calls

def _read_okf_files(okf_dir):
    return {
        path.name: path.read_bytes()
        for path in sorted(okf_dir.glob("*.json"))
    }


def test_okf_files_are_emitted(tmp_path):
    (tmp_path / "example.py").write_text(
        """
def helper():
    return 1

def main():
    return helper()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    okf_dir = emit_okf(result, tmp_path)

    expected = {
        "manifest.json",
        "project.json",
        "modules.json",
        "symbols.json",
        "relationships.json",
        "repo_graph.json",
    }

    assert {
        path.name
        for path in okf_dir.glob("*.json")
    } == expected


def test_okf_files_are_valid_json(tmp_path):
    (tmp_path / "example.py").write_text(
        """
VALUE = 42

def helper():
    return VALUE
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)
    okf_dir = emit_okf(result, tmp_path)

    for path in okf_dir.glob("*.json"):
        data = json.loads(
            path.read_text(encoding="utf-8")
        )

        assert isinstance(data, dict)
        assert "schema_version" in data


def test_repo_graph_contains_modules_symbols_and_relationships(tmp_path):
    (tmp_path / "utils.py").write_text(
        """
def helper():
    return 1
""",
        encoding="utf-8",
    )

    (tmp_path / "main.py").write_text(
        """
from utils import helper

def main():
    return helper()
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)
    okf_dir = emit_okf(result, tmp_path)

    graph = json.loads(
        (okf_dir / "repo_graph.json").read_text(
            encoding="utf-8"
        )
    )

    assert graph["schema_version"] == "1.0"

    nodes = graph["graph"]["nodes"]
    edges = graph["graph"]["edges"]

    node_ids = {
        node["id"]
        for node in nodes
    }

    assert "module:main" in node_ids
    assert "module:utils" in node_ids
    assert "function:main.main" in node_ids
    assert "function:utils.helper" in node_ids

    assert any(
        edge["type"] == "call"
        and edge["source"] == "function:main.main"
        and edge["target"] == "function:utils.helper"
        and edge["resolved"] is True
        for edge in edges
    )


def test_okf_paths_use_forward_slashes(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()

    (package / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (package / "module.py").write_text(
        """
def hello():
    return "hello"
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)
    okf_dir = emit_okf(result, tmp_path)

    modules = json.loads(
        (okf_dir / "modules.json").read_text(
            encoding="utf-8"
        )
    )

    for module in modules["modules"]:
        assert "\\" not in module["path"]


def test_okf_contains_no_absolute_paths_or_timestamps(tmp_path):
    (tmp_path / "example.py").write_text(
        """
def hello():
    return 1
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)
    okf_dir = emit_okf(result, tmp_path)

    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(okf_dir.glob("*.json"))
    )

    assert str(tmp_path.resolve()) not in serialized
    assert str(tmp_path) not in serialized
    assert "timestamp" not in serialized.lower()
    assert "created_at" not in serialized.lower()
    assert "generated_at" not in serialized.lower()


def test_okf_emission_is_byte_for_byte_deterministic(tmp_path):
    (tmp_path / "utils.py").write_text(
        """
class Base:
    pass

def helper():
    return 1
""",
        encoding="utf-8",
    )

    (tmp_path / "main.py").write_text(
        """
from utils import helper, Base

class Child(Base):
    pass

def main():
    return helper()
""",
        encoding="utf-8",
    )

    result1 = parse_python_source_tree(tmp_path)

    output1 = tmp_path / "output1"
    output2 = tmp_path / "output2"

    okf1 = emit_okf(result1, output1)

    result2 = parse_python_source_tree(tmp_path)
    okf2 = emit_okf(result2, output2)

    files1 = _read_okf_files(okf1)
    files2 = _read_okf_files(okf2)

    assert files1.keys() == files2.keys()

    for filename in files1:
        assert files1[filename] == files2[filename]


def test_repo_graph_relationships_are_deterministically_ordered(tmp_path):
    (tmp_path / "a.py").write_text(
        """
def first():
    return second()

def second():
    return third()

def third():
    return 3
""",
        encoding="utf-8",
    )

    result = parse_python_source_tree(tmp_path)

    okf_dir = emit_okf(result, tmp_path)

    graph = json.loads(
        (okf_dir / "repo_graph.json").read_text(
            encoding="utf-8"
        )
    )

    edges = graph["graph"]["edges"]

    assert edges == sorted(
        edges,
        key=lambda edge: (
            edge["source"],
            edge["type"],
            edge["target"] or "",
            edge.get("line", 0),
        ),
    )


def test_emission_does_not_modify_source_files(tmp_path):
    source = tmp_path / "example.py"

    source.write_text(
        """
def hello():
    return 1
""",
        encoding="utf-8",
    )

    before = source.read_bytes()

    result = parse_python_source_tree(tmp_path)
    emit_okf(result, tmp_path)

    after = source.read_bytes()

    assert after == before