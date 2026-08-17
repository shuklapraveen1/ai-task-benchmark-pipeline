# Knowledge.py

from __future__ import annotations
import json
from dataclasses import asdict

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParseDiagnostic:
    path: str
    error: str
    line: Optional[int] = None
    column: Optional[int] = None


# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------


@dataclass
class ProjectMetadata:
    name: Optional[str]
    version: Optional[str]
    description: Optional[str]

    ecosystem: str
    root: str

    package_roots: list[str] = field(default_factory=list)
    python_versions: list[str] = field(default_factory=list)

    entry_points: dict[str, str] = field(default_factory=dict)

    runtime_dependencies: list[str] = field(default_factory=list)
    optional_dependencies: dict[str, list[str]] = field(
        default_factory=dict
    )

    source_files: int = 0
    test_files: int = 0

    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module / symbol nodes
# ---------------------------------------------------------------------------


@dataclass
class ModuleNode:
    id: str
    path: str
    module_name: str

    package: Optional[str]
    is_package: bool
    is_test: bool

    line_count: int

    imports: list[str] = field(default_factory=list)
    import_bindings: dict[str, str] = field(     
        default_factory=dict                    
    )

    public_symbols: list[str] = field(default_factory=list)

    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)


@dataclass
class SymbolNode:
    id: str

    module_id: str
    name: str
    qualified_name: str

    kind: str
    visibility: str

    line_start: int
    line_end: int

    signature: Optional[str] = None

    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)

    docstring: Optional[str] = None


@dataclass
class ImportEdge:
    source: str
    target: str

    kind: str
    imported_names: list[str] = field(default_factory=list)

    line: int = 0
    resolved: bool = False


@dataclass
class InheritanceEdge:
    source: str
    target: str

    resolved: bool = False
    confidence: str = "low"

    line: int = 0

@dataclass
class CallEdge:
    source: str
    target: Optional[str] = None

    resolved: bool = False
    confidence: str = "low"
    resolution: str = "unknown"

    line: int = 0

# ---------------------------------------------------------------------------
# Parsed repository
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeParseResult:
    schema_version: str

    modules: list[ModuleNode] = field(default_factory=list)
    symbols: list[SymbolNode] = field(default_factory=list)
    imports: list[ImportEdge] = field(default_factory=list)
    inheritance: list[InheritanceEdge] = field(default_factory=list)
    calls: list[CallEdge] = field(default_factory=list)

    diagnostics: list[ParseDiagnostic] = field(
        default_factory=list
    )

    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "build",
    "dist",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
    ".pipeline_history_probe",
    "node_modules",
}


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return True

    return any(
        part in _IGNORED_DIRECTORIES
        for part in relative_parts
    )


def _normalise_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_test_file(path: Path) -> bool:
    name = path.name.lower()

    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "test" in path.parts
    )


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root)

    parts = list(relative.parts)

    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem

    return ".".join(parts)


def _package_name(module_name: str) -> Optional[str]:
    if "." not in module_name:
        return module_name or None

    return module_name.rsplit(".", 1)[0]


def _visibility(name: str) -> str:
    if name.startswith("__") and name.endswith("__"):
        return "dunder"

    if name.startswith("_"):
        return "private"

    return "public"


def _qualified_name(module_name: str, name: str) -> str:
    if module_name:
        return f"{module_name}.{name}"

    return name


def _symbol_id(kind: str, qualified_name: str) -> str:
    return f"{kind}:{qualified_name}"


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parts = []

        current: ast.expr | None = node

        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.append(current.id)

        return ".".join(reversed(parts))

    try:
        return ast.unparse(node)
    except Exception:
        return "<unknown>"


def _base_name(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unknown>"


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """
    Produce a stable source-level signature.

    We intentionally use ast.unparse rather than inspect.signature because
    inspect would require importing/executing repository code.
    """
    try:
        arguments = ast.unparse(node.args)

        if node.returns is not None:
            returns = ast.unparse(node.returns)
            return f"{node.name}({arguments}) -> {returns}"

        return f"{node.name}({arguments})"

    except Exception:
        return node.name


def _docstring(node: ast.AST) -> Optional[str]:
    return ast.get_docstring(node, clean=False)


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class _KnowledgeVisitor(ast.NodeVisitor):
    """
    Extract module-level and nested symbols without executing code.
    """

    def __init__(
        self,
        module_name: str,
        module_id: str,
    ) -> None:
        self.module_name = module_name
        self.module_id = module_id

        self.symbols: list[SymbolNode] = []

        self.imports: list[str] = []
        self.import_bindings: dict[str, str] = {}
        self.functions: list[str] = []
        self.classes: list[str] = []
        self.constants: list[str] = []
        self.calls: list[tuple[str, ast.Call]] = []

        self._scope: list[str] = []
        self._symbol_scope: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        """
        Record calls together with the containing symbol ID.

        Resolution is deferred to CallGraphResolver.
        """

        if self._symbol_scope:
            caller = self._symbol_scope[-1]
        else:
            # Module-level calls have the module as their caller.
            caller = self.module_id

        self.calls.append((caller, node))

        self.generic_visit(node)

    def _qualified(self, name: str) -> str:
        parts = [self.module_name]

        if self._scope:
            parts.extend(self._scope)

        parts.append(name)

        return ".".join(
            part for part in parts if part
        )
    

    def _add_symbol(
        self,
        *,
        name: str,
        kind: str,
        node: ast.AST,
        signature: Optional[str] = None,
        decorators: Optional[list[str]] = None,
        bases: Optional[list[str]] = None,
    ) -> SymbolNode:
        qualified = self._qualified(name)

        line_start = getattr(node, "lineno", 1)
        line_end = getattr(
            node,
            "end_lineno",
            line_start,
        )
        def _docstring(node: ast.AST) -> Optional[str]:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                return None
            return ast.get_docstring(node, clean=False)

        symbol = SymbolNode(
            id=_symbol_id(kind, qualified),
            module_id=self.module_id,
            name=name,
            qualified_name=qualified,
            kind=kind,
            visibility=_visibility(name),
            line_start=line_start,
            line_end=line_end,
            signature=signature,
            decorators=decorators or [],
            bases=bases or [],
            docstring=_docstring(node),
        )

        self.symbols.append(symbol)
        
        return symbol

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------
    

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
            binding_name = alias.asname or alias.name.split(".")[0]
            self.import_bindings[binding_name] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""

        if node.level:
            prefix = "." * node.level
            import_name = prefix + module
        else:
            import_name = module

        self.imports.append(import_name)

        for alias in node.names:
            if alias.name == "*":
                continue

            binding_name = alias.asname or alias.name

            if module:
                target = f"{import_name}.{alias.name}"
            else:
                target = f"{import_name}{alias.name}"

            self.import_bindings[binding_name] = target

    # ------------------------------------------------------------------
    # Functions
    # ------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        qualified = self._qualified(node.name)

        symbol = self._add_symbol(
            name=node.name,
            kind="method" if self._scope else "function",
            node=node,
            signature=_function_signature(node),
            decorators=[
                _decorator_name(d)
                for d in node.decorator_list
            ],
        )

        if not self._scope:
            self.functions.append(qualified)

        self._scope.append(node.name)
        self._symbol_scope.append(symbol.id) 
        
        self.generic_visit(node)
        
        self._symbol_scope.pop()  
        self._scope.pop()

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        qualified = self._qualified(node.name)

        symbol = self._add_symbol(
            name=node.name,
            kind="method" if self._scope else "function",
            node=node,
            signature=_function_signature(node),
            decorators=[
                _decorator_name(d)
                for d in node.decorator_list
            ],
        )

        if not self._scope:
            self.functions.append(qualified)

        self._scope.append(node.name)
        self._symbol_scope.append(symbol.id)

        self.generic_visit(node)

        self._symbol_scope.pop()
        self._scope.pop()

    # ------------------------------------------------------------------
    # Classes
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = self._qualified(node.name)

        self._add_symbol(
            name=node.name,
            kind="class",
            node=node,
            decorators=[
                _decorator_name(d)
                for d in node.decorator_list
            ],
            bases=[
                _base_name(base)
                for base in node.bases
            ],
        )

        if not self._scope:
            self.classes.append(qualified)

        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    # ------------------------------------------------------------------
    # Constants / assignments
    # ------------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._scope:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    qualified = self._qualified(target.id)
                    kind = "constant" if target.id.isupper() else "variable"

                    self._add_symbol(
                        name=target.id,
                        kind=kind,
                        node=node,
                    )
                    if kind == "constant":
                        self.constants.append(qualified)

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if not self._scope and isinstance(node.target, ast.Name):
            qualified = self._qualified(node.target.id)
            kind = "constant" if node.target.id.isupper() else "variable"

            self._add_symbol(
                name=node.target.id,
                kind=kind,
                node=node,
            )
            if kind == "constant":
                self.constants.append(qualified)

        self.generic_visit(node)


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------


def _parse_python_file(
    path: Path,
    root: Path,
) -> tuple[
    Optional[ModuleNode],
    list[SymbolNode],
    list[tuple[str, ast.Call]],
    Optional[ParseDiagnostic],
]:
    relative_path = _normalise_path(path, root)
    module_name = _module_name(path, root)

    module_id = f"module:{module_name}"

    try:
        source = path.read_text(
            encoding="utf-8",
        )
    except UnicodeDecodeError as exc:
        return (
            None,
            [],
            [],
            ParseDiagnostic(
                path=relative_path,
                error=f"UTF-8 decoding failed: {exc}",
            ),
        )
    except OSError as exc:
        return (
            None,
            [],
            [],
            ParseDiagnostic(
                path=relative_path,
                error=f"Unable to read file: {exc}",
            ),
        )

    try:
        tree = ast.parse(
            source,
            filename=str(path),
        )
    except SyntaxError as exc:
        return (
            None,
            [],
            [],
            ParseDiagnostic(
                path=relative_path,
                error=str(exc),
                line=exc.lineno,
                column=exc.offset,
            ),
        )

    visitor = _KnowledgeVisitor(
        module_name=module_name,
        module_id=module_id,
    )

    visitor.visit(tree)

    public_symbols = sorted(
        symbol.qualified_name
        for symbol in visitor.symbols
        if symbol.visibility == "public"
        and symbol.kind != "method"
    )

    module = ModuleNode(
        id=module_id,
        path=relative_path,
        module_name=module_name,
        package=_package_name(module_name),
        is_package=path.name == "__init__.py",
        is_test=_is_test_file(path),
        line_count=len(source.splitlines()),
        imports=sorted(set(visitor.imports)),
        import_bindings=dict(sorted(visitor.import_bindings.items())),                                     
        public_symbols=public_symbols,
        functions=sorted(set(visitor.functions)),
        classes=sorted(set(visitor.classes)),
        constants=sorted(set(visitor.constants)),
    )

    return (module,visitor.symbols,visitor.calls,None,)

# ---------------------------------------------------------------------------
# Module Resolver
# ---------------------------------------------------------------------------


class ModuleResolver:
    def __init__(self, modules: list[ModuleNode], symbols: list[SymbolNode]) -> None:
        self.modules = modules
        self.symbols = symbols
        self.module_by_id = {m.id: m for m in modules}
        self.module_by_name = {m.module_name: m for m in modules}
        self.symbol_by_qualified_name = {s.qualified_name: s for s in symbols}
        self.symbol_by_id = {s.id: s for s in symbols}

    def resolve_binding(self, source_module: ModuleNode, binding_name: str) -> Optional[str]:
        target = source_module.import_bindings.get(binding_name)
        if not target:
            return None
        
        if target.startswith("."):
            dots = len(target) - len(target.lstrip("."))
            remainder = target[dots:]
            
            parts = source_module.module_name.split(".")
            # Pop current module/package levels based on relative dots
            if dots == 1:
                parts = parts[:-1]
            else:
                parts = parts[:-(dots)]
            
            if remainder:
                parts.append(remainder)
            resolved_name = ".".join(p for p in parts if p)
            
            # Check if it points directly to a symbol
            if resolved_name in self.symbol_by_qualified_name:
                return resolved_name
            return f"module:{resolved_name}"
        
        if f"module:{target}" in self.module_by_id or target in self.module_by_name:
            return f"module:{target}"
            
        return target

    def _resolve_base(
        self,
        source_module: ModuleNode,
        base: str,
    ) -> Optional[str]:
        # Direct class in the same module.
        local = f"{source_module.module_name}.{base}"

        if local in self.symbol_by_qualified_name:
            symbol = self.symbol_by_qualified_name[local]
            if symbol.kind == "class":
                return symbol.id

        # Imported class / module.
        parts = base.split(".")
        first = parts[0]

        binding_target = self.resolve_binding(
            source_module,
            first,
        )

        if binding_target is not None:
            suffix = parts[1:]

            base_target = binding_target
            if base_target.startswith("module:"):
                base_target = base_target[len("module:") :]

            resolved_name = ".".join([base_target] + suffix)
            symbol = self.symbol_by_qualified_name.get(resolved_name)

            if symbol and symbol.kind == "class":
                return symbol.id

            module_name = binding_target
            if binding_target.startswith("module:"):
                module_name = binding_target[len("module:") :]

            resolved_name = ".".join([module_name] + suffix)
            symbol = self.symbol_by_qualified_name.get(resolved_name)

            if symbol and symbol.kind == "class":
                return symbol.id

        # Fully qualified class reference.
        symbol = self.symbol_by_qualified_name.get(base)
        if symbol and symbol.kind == "class":
            return symbol.id

        return None

    def resolve_imports(self) -> list[ImportEdge]:
        edges = []
        for mod in self.modules:
            for imp in mod.imports:
                target_name = imp
                if target_name.startswith("."):
                    dots = len(target_name) - len(target_name.lstrip("."))
                    remainder = target_name[dots:]
                    
                    parts = mod.module_name.split(".")
                    # For relative imports, drop the current module name first, then pop parent packages based on dots > 1
                    parts = parts[:-1]
                    if dots > 1:
                        parts = parts[:-(dots - 1)]
                        
                    if remainder:
                        parts.append(remainder)
                    target_name = ".".join(p for p in parts if p)
                
                target_id = f"module:{target_name}"
                resolved = target_id in self.module_by_id
                
                edges.append(
                    ImportEdge(
                        source=mod.id,
                        target=target_id,
                        kind="import",
                        resolved=resolved,
                    )
                )
        return edges

    def resolve_inheritance(self) -> list[InheritanceEdge]:
        edges = []
        for symbol in self.symbols:
            if symbol.kind != "class":
                continue
            mod = self.module_by_id.get(symbol.module_id)
            if not mod:
                continue
            for base in symbol.bases:
                resolved_target = self._resolve_base(mod, base)
                if resolved_target is not None:
                    edges.append(
                        InheritanceEdge(
                            source=symbol.id,
                            target=resolved_target or base,
                            resolved=resolved_target is not None,
                            confidence="high" if resolved_target else "low",
                            line=symbol.line_start,
                        )
                    )
        return edges

class CallGraphResolver:
    """
    Resolve statically identifiable AST call targets.

    This resolver never imports or executes repository code.

    Resolution levels:

        high
            Direct same-module function or directly imported function.

        medium
            Statically resolvable module/member or class method call.

        low
            Dynamic or uncertain call. No fabricated target is emitted.
    """

    def __init__(
        self,
        modules: list[ModuleNode],
        symbols: list[SymbolNode],
    ) -> None:
        self.modules = modules
        self.symbols = symbols

        self.module_by_id = {
            module.id: module
            for module in modules
        }

        self.module_by_name = {
            module.module_name: module
            for module in modules
        }

        self.symbol_by_qualified_name = {
            symbol.qualified_name: symbol
            for symbol in symbols
        }

        self.symbol_by_id = {
            symbol.id: symbol
            for symbol in symbols
        }

        self.symbols_by_module = {}

        for symbol in symbols:
            self.symbols_by_module.setdefault(
                symbol.module_id,
                [],
            ).append(symbol)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _module_for_caller(
        self,
        caller_id: str,
    ) -> Optional[ModuleNode]:
        symbol = self.symbol_by_id.get(caller_id)

        if symbol is None:
            if caller_id.startswith("module:"):
                return self.module_by_id.get(caller_id)

            return None

        return self.module_by_id.get(symbol.module_id)

    def _function_target(
        self,
        qualified_name: str,
    ) -> Optional[str]:
        symbol = self.symbol_by_qualified_name.get(
            qualified_name
        )

        if symbol is None:
            return None

        if symbol.kind not in {"function", "method"}:
            return None

        return symbol.id

    def _class_target(
        self,
        qualified_name: str,
    ) -> Optional[str]:
        symbol = self.symbol_by_qualified_name.get(
            qualified_name
        )

        if symbol is None:
            return None

        if symbol.kind != "class":
            return None

        return symbol.id

    # ------------------------------------------------------------------
    # Name calls
    # ------------------------------------------------------------------

    def _resolve_name_call(
        self,
        module: ModuleNode,
        name: str,
    ) -> tuple[Optional[str], str, str]:
        """
        Resolve:

            foo()

        using same-module definitions and import bindings.
        """

        # --------------------------------------------------------------
        # 1. Same-module function
        # --------------------------------------------------------------

        local_name = (
            f"{module.module_name}.{name}"
        )

        target = self._function_target(local_name)

        if target is not None:
            return (
                target,
                "high",
                "same_module",
            )

        # --------------------------------------------------------------
        # 2. Imported binding
        # --------------------------------------------------------------

        binding = module.import_bindings.get(name)

        if binding is None:
            return (
                None,
                "low",
                "unknown",
            )

        # Direct imported function:
        #
        # from pkg.utils import helper
        #
        # import binding:
        #
        # helper -> pkg.utils.helper

        if binding.startswith("."):
            binding = self._normalise_relative_binding(
                module,
                binding,
            )

        target = self._function_target(binding)

        if target is not None:
            return (
                target,
                "high",
                "import",
            )

        # Imported class constructor is also a statically known call.
        target = self._class_target(binding)

        if target is not None:
            return (
                target,
                "high",
                "imported_class",
            )

        # Module import:
        #
        # import pkg.utils
        # utils.foo()
        #
        # The name itself may correspond to a module binding.

        if (
            binding in self.module_by_name
            or f"module:{binding}" in self.module_by_id
        ):
            return (
                None,
                "medium",
                "module_binding",
            )

        return (
            None,
            "low",
            "unknown",
        )

    # ------------------------------------------------------------------
    # Attribute calls
    # ------------------------------------------------------------------

    def _resolve_attribute_call(
        self,
        module: ModuleNode,
        node: ast.Attribute,
    ) -> tuple[Optional[str], str, str]:

        chain = self._attribute_chain(node)

        if not chain:
            return (
                None,
                "low",
                "dynamic",
            )

        first = chain[0]
        suffix = chain[1:]

        # --------------------------------------------------------------
        # module.function()
        # --------------------------------------------------------------

        binding = module.import_bindings.get(first)

        if binding is not None:
            if binding.startswith("."):
                binding = self._normalise_relative_binding(
                    module,
                    binding,
                )

            module_name = binding

            if module_name.startswith("module:"):
                module_name = module_name[len("module:"):]

            qualified = ".".join(
                [module_name] + suffix
            )

            target = self._function_target(
                qualified
            )

            if target is not None:
                return (
                    target,
                    "high",
                    "imported_module",
                )

            target = self._function_target(
                qualified
            )

            if target is not None:
                return (
                    target,
                    "medium",
                    "attribute",
                )

        # --------------------------------------------------------------
        # Class.method()
        # --------------------------------------------------------------

        qualified = ".".join(chain)

        target = self._function_target(
            qualified
        )

        if target is not None:
            return (
                target,
                "medium",
                "qualified_attribute",
            )

        # --------------------------------------------------------------
        # self.method()
        #
        # We can resolve the method only when the method belongs to
        # the caller's enclosing class.
        # --------------------------------------------------------------

        if first == "self" and suffix:
            caller = self.symbol_by_id.get(
                self._current_caller
            )

            if caller is not None:
                class_name = self._enclosing_class(
                    caller
                )

                if class_name:
                    qualified = (
                        f"{module.module_name}."
                        f"{class_name}."
                        f"{suffix[0]}"
                    )

                    target = self._function_target(
                        qualified
                    )

                    if target is not None:
                        return (
                            target,
                            "medium",
                            "same_class_method",
                        )

        return (
            None,
            "low",
            "dynamic",
        )

    @staticmethod
    def _attribute_chain(
        node: ast.Attribute,
    ) -> Optional[list[str]]:
        parts = [node.attr]
        current = node.value

        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.append(current.id)
            return list(reversed(parts))

        return None

    def _enclosing_class(
        self,
        symbol: SymbolNode,
    ) -> Optional[str]:
        parts = symbol.qualified_name.split(".")

        if symbol.kind != "method":
            return None

        if len(parts) < 3:
            return None

        return parts[-2]

    # ------------------------------------------------------------------
    # Relative import normalization
    # ------------------------------------------------------------------

    def _normalise_relative_binding(
        self,
        module: ModuleNode,
        binding: str,
    ) -> str:
        dots = len(binding) - len(binding.lstrip("."))

        remainder = binding[dots:]

        parts = module.module_name.split(".")

        if dots == 1:
            parts = parts[:-1]
        else:
            parts = parts[:-(dots)]

        if remainder:
            parts.append(remainder)

        return ".".join(
            part
            for part in parts
            if part
        )

    # ------------------------------------------------------------------
    # Call resolution
    # ------------------------------------------------------------------

    def resolve_calls(
        self,
        call_records: Optional[list[tuple[str, ast.Call]]] = None,
    ) -> list[CallEdge]:
        if call_records is None:
            call_records = []

        edges: list[CallEdge] = []

        for caller_id, node in call_records:
            module = self._module_for_caller(
                caller_id
            )

            if module is None:
                continue

            self._current_caller = caller_id

            target = None
            confidence = "low"
            resolution = "unknown"

            # ----------------------------------------------------------
            # foo()
            # ----------------------------------------------------------

            if isinstance(node.func, ast.Name):
                (
                    target,
                    confidence,
                    resolution,
                ) = self._resolve_name_call(
                    module,
                    node.func.id,
                )

            # ----------------------------------------------------------
            # obj.foo()
            # ----------------------------------------------------------

            elif isinstance(node.func, ast.Attribute):
                (
                    target,
                    confidence,
                    resolution,
                ) = self._resolve_attribute_call(
                    module,
                    node.func,
                )

            else:
                resolution = "dynamic"

            edges.append(
                CallEdge(
                    source=caller_id,
                    target=target,  # <-- Pass target directly (can be None)
                    resolved=target is not None,
                    confidence=confidence,
                    resolution=resolution,
                    line=getattr(
                        node,
                        "lineno",
                        0,
                    ),
                )
            )

        return edges

    

# ---------------------------------------------------------------------------
# Repository parser
# ---------------------------------------------------------------------------


def parse_python_source_tree(
    repo_path: str | Path,
) -> KnowledgeParseResult:
    """
    Parse every relevant Python source file beneath repo_path.

    This function is strictly read-only and never imports repository code.
    """

    root = Path(repo_path).resolve()

    result = KnowledgeParseResult(
        schema_version=SCHEMA_VERSION,
    )

    if not root.exists():
        result.warnings.append(
            f"Repository path does not exist: {root}"
        )
        return result

    if not root.is_dir():
        result.warnings.append(
            f"Repository path is not a directory: {root}"
        )
        return result

    python_files = sorted(
        (
            path
            for path in root.rglob("*.py")
            if not _is_ignored(path, root)
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    call_records: list[tuple[str, ast.Call]] = []

    for path in python_files:
        (module, symbols, file_calls, diagnostic, ) = _parse_python_file(path,root,)

        if diagnostic is not None:
            result.diagnostics.append(diagnostic)
            continue

        if module is None:
            continue

        result.modules.append(module)
        result.symbols.extend(symbols)

        call_records.extend(file_calls)

    # Deterministic canonical ordering.
    result.modules.sort(key=lambda item: item.id)

    result.symbols.sort(
        key=lambda item: (
            item.module_id,
            item.line_start,
            item.line_end,
            item.id,
        )
    )

    result.diagnostics.sort(
        key=lambda item: (
            item.path,
            item.line or 0,
            item.column or 0,
            item.error,
        )
    )
    # Resolve Batch 2 relationships
    resolver = ModuleResolver(result.modules, result.symbols)
    result.imports = resolver.resolve_imports()
    result.inheritance = resolver.resolve_inheritance()

    call_resolver = CallGraphResolver(result.modules, result.symbols)
    result.calls = call_resolver.resolve_calls(call_records)

    result.calls.sort(
        key=lambda edge: (
            edge.source,
            edge.line,
            edge.target or "",
            edge.resolution,
            edge.confidence,
            edge.resolved,
        )
    )

    result.imports.sort(
        key=lambda edge: (
            edge.source,
            edge.target,
            edge.kind,
        )
    )

    result.inheritance.sort(
        key=lambda edge: (
            edge.source,
            edge.target,
        )
    )
    return result


# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------


def parse_repository(
    repo_path: str | Path,
) -> KnowledgeParseResult:
    """
    Public Batch-1 entry point.

    Kept intentionally independent from Pipeline 1's RepoContext so the AST
    parser can be tested in isolation.
    """
    return parse_python_source_tree(repo_path)

# ---------------------------------------------------------------------------
# Batch 4 - .okf / repo_graph.json emission
# ---------------------------------------------------------------------------

OKF_SCHEMA_VERSION = "1.0"


def _canonical_json(data) -> str:
    """
    Serialize JSON deterministically.

    Guarantees:
      - sorted object keys
      - stable indentation
      - UTF-8 compatible output
      - trailing newline
      - no host-specific formatting differences
    """
    return json.dumps(
        data,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ": "),
    ) + "\n"


def _normalise_serialized_path(value: str) -> str:
    """
    Normalize repository-relative paths for machine-readable output.
    """
    return str(value).replace("\\", "/")


def _serialize_module(module: ModuleNode) -> dict:
    data = asdict(module)

    data["path"] = _normalise_serialized_path(data["path"])

    return data


def _serialize_symbol(symbol: SymbolNode) -> dict:
    return asdict(symbol)


def _serialize_import(edge: ImportEdge) -> dict:
    return asdict(edge)


def _serialize_inheritance(edge: InheritanceEdge) -> dict:
    return asdict(edge)


def _serialize_call(edge: CallEdge) -> dict:
    return asdict(edge)


def _build_manifest(result: KnowledgeParseResult) -> dict:
    """
    Build the stable .okf manifest.

    The manifest deliberately contains no timestamps, absolute paths,
    machine-specific information, or execution state.
    """
    return {
        "schema_version": OKF_SCHEMA_VERSION,
        "format": "okf",
        "artifacts": [
            "manifest.json",
            "project.json",
            "modules.json",
            "symbols.json",
            "relationships.json",
            "repo_graph.json",
        ],
        "counts": {
            "modules": len(result.modules),
            "symbols": len(result.symbols),
            "imports": len(result.imports),
            "inheritance": len(result.inheritance),
            "calls": len(result.calls),
            "diagnostics": len(result.diagnostics),
        },
    }


def _build_project(result: KnowledgeParseResult) -> dict:
    """
    Build project-level metadata from the knowledge result.

    Batch 1's KnowledgeParseResult currently does not carry a separate
    ProjectMetadata object, so this artifact intentionally describes the
    discovered Python repository structurally rather than inventing
    package metadata.
    """
    source_modules = [
        module
        for module in result.modules
        if not module.is_test
    ]

    test_modules = [
        module
        for module in result.modules
        if module.is_test
    ]

    return {
        "schema_version": OKF_SCHEMA_VERSION,
        "ecosystem": "python",
        "source_files": len(source_modules),
        "test_files": len(test_modules),
        "module_count": len(result.modules),
        "symbol_count": len(result.symbols),
        "diagnostic_count": len(result.diagnostics),
    }


def _build_modules(result: KnowledgeParseResult) -> dict:
    modules = [
        _serialize_module(module)
        for module in sorted(
            result.modules,
            key=lambda item: item.id,
        )
    ]

    return {
        "schema_version": OKF_SCHEMA_VERSION,
        "modules": modules,
    }


def _build_symbols(result: KnowledgeParseResult) -> dict:
    symbols = [
        _serialize_symbol(symbol)
        for symbol in sorted(
            result.symbols,
            key=lambda item: (
                item.module_id,
                item.line_start,
                item.line_end,
                item.id,
            ),
        )
    ]

    return {
        "schema_version": OKF_SCHEMA_VERSION,
        "symbols": symbols,
    }


def _build_relationships(result: KnowledgeParseResult) -> dict:
    imports = [
        _serialize_import(edge)
        for edge in sorted(
            result.imports,
            key=lambda edge: (
                edge.source,
                edge.target,
                edge.kind,
                edge.line,
            ),
        )
    ]

    inheritance = [
        _serialize_inheritance(edge)
        for edge in sorted(
            result.inheritance,
            key=lambda edge: (
                edge.source,
                edge.target,
                edge.line,
            ),
        )
    ]

    calls = [
        _serialize_call(edge)
        for edge in sorted(
            result.calls,
            key=lambda edge: (
                edge.source,
                edge.line,
                edge.target or "",
                edge.resolution,
                edge.confidence,
                edge.resolved,
            ),
        )
    ]

    return {
        "schema_version": OKF_SCHEMA_VERSION,
        "imports": imports,
        "inheritance": inheritance,
        "calls": calls,
    }


def _build_repo_graph(result: KnowledgeParseResult) -> dict:
    """
    Construct the unified graph representation.

    Nodes and edges are kept explicitly typed so downstream benchmark
    generation does not have to infer whether an ID represents a module
    or symbol.
    """

    module_nodes = []

    for module in sorted(
        result.modules,
        key=lambda item: item.id,
    ):
        module_nodes.append(
            {
                "id": module.id,
                "type": "module",
                "path": _normalise_serialized_path(module.path),
                "module_name": module.module_name,
                "package": module.package,
                "is_package": module.is_package,
                "is_test": module.is_test,
            }
        )

    symbol_nodes = []

    for symbol in sorted(
        result.symbols,
        key=lambda item: (
            item.module_id,
            item.line_start,
            item.line_end,
            item.id,
        ),
    ):
        symbol_nodes.append(
            {
                "id": symbol.id,
                "type": "symbol",
                "module_id": symbol.module_id,
                "name": symbol.name,
                "qualified_name": symbol.qualified_name,
                "kind": symbol.kind,
                "visibility": symbol.visibility,
                "line_start": symbol.line_start,
                "line_end": symbol.line_end,
            }
        )

    nodes = module_nodes + symbol_nodes

    edges = []

    for edge in sorted(
        result.imports,
        key=lambda item: (
            item.source,
            item.target,
            item.kind,
            item.line,
        ),
    ):
        edges.append(
            {
                "source": edge.source,
                "target": edge.target,
                "type": "import",
                "kind": edge.kind,
                "resolved": edge.resolved,
                "line": edge.line,
            }
        )

    for edge in sorted(
        result.inheritance,
        key=lambda item: (
            item.source,
            item.target,
            item.line,
        ),
    ):
        edges.append(
            {
                "source": edge.source,
                "target": edge.target,
                "type": "inheritance",
                "resolved": edge.resolved,
                "confidence": edge.confidence,
                "line": edge.line,
            }
        )

    for edge in sorted(
        result.calls,
            key=lambda item: (
                item.source,
                item.line,
                item.target or "",
                item.resolution,
                item.confidence,
                item.resolved,
            ),
        ):
        edges.append(
            {
                "source": edge.source,
                "target": edge.target,
                "type": "call",
                "resolved": edge.resolved,
                "confidence": edge.confidence,
                "resolution": edge.resolution,
                "line": edge.line,
            }
        )
    edges.sort(
        key=lambda edge: (
            edge["source"],
            edge["type"],
            edge["target"] or "",
            edge.get("line", 0),
            edge.get("resolution", ""),
        )
    )

    return {
        "schema_version": OKF_SCHEMA_VERSION,
        "graph": {
            "nodes": nodes,
            "edges": edges,
        },
    }


def emit_okf(
    result: KnowledgeParseResult,
    output_dir: str | Path,
) -> Path:
    """
    Emit the complete deterministic .okf knowledge layer.

    Output:

        <output_dir>/
            .okf/
                manifest.json
                project.json
                modules.json
                symbols.json
                relationships.json
                repo_graph.json

    Safety contract:
      - does not execute repository code
      - does not inspect runtime state
      - does not include absolute paths
      - does not include timestamps
      - deterministic across repeated runs
    """

    root = Path(output_dir)
    okf_dir = root / ".okf"

    okf_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    artifacts = {
        "manifest.json": _build_manifest(result),
        "project.json": _build_project(result),
        "modules.json": _build_modules(result),
        "symbols.json": _build_symbols(result),
        "relationships.json": _build_relationships(result),
        "repo_graph.json": _build_repo_graph(result),
    }

    for filename in sorted(artifacts):
        destination = okf_dir / filename

        content = _canonical_json(
            artifacts[filename]
        )

        destination.write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )

    return okf_dir