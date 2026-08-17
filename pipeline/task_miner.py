from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SIDE_EFFECT_MODULES = frozenset(
    {
        "os",
        "os.path",
        "subprocess",
        "requests",
        "httpx",
        "urllib",
        "urllib.request",
        "socket",
        "shutil",
        "pathlib",
        "sqlite3",
        "psycopg2",
        "mysql",
        "boto3",
    }
)

DEFAULT_SIDE_EFFECT_NAMES = frozenset(
    {
        "open",
        "remove",
        "unlink",
        "rename",
        "mkdir",
        "makedirs",
        "rmdir",
        "system",
        "popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "request",
        "get",
        "post",
        "put",
        "delete",
    }
)

EXCLUDED_PATH_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        ".tox",
        "tasks",
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".pipeline_history_probe",
        ".okf",
    }
)

EXCLUDED_MODULE_PREFIXES = (
    "pipeline",
)



# ---------------------------------------------------------------------------
# Candidate schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExcisionCandidate:
    """
    A read-only candidate for an Excision benchmark task.

    The candidate identifies an existing function whose implementation can
    potentially be replaced by the benchmark's solution while preserving
    its observable contract.
    """

    function_id: str
    module_id: str
    name: str

    file_path: str
    line_start: int
    line_end: int

    public: bool
    callers: tuple[str, ...]
    caller_count: int

    coverage_percent: Optional[float]

    side_effect_signals: tuple[str, ...]
    side_effect_penalty: float

    public_api_bonus: float
    coverage_score: float
    caller_score: float
    complexity_score: float

    score: float
    rationale: tuple[str, ...] = ()
    associated_test_file: Optional[str] = None
    associated_test_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "module_id": self.module_id,
            "name": self.name,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "public": self.public,
            "callers": list(self.callers),
            "caller_count": self.caller_count,
            "coverage_percent": self.coverage_percent,
            "side_effect_signals": list(self.side_effect_signals),
            "side_effect_penalty": self.side_effect_penalty,
            "public_api_bonus": self.public_api_bonus,
            "coverage_score": self.coverage_score,
            "caller_score": self.caller_score,
            "complexity_score": self.complexity_score,
            "score": self.score,
            "rationale": list(self.rationale),
            "associated_test_file": self.associated_test_file,
            "associated_test_name": self.associated_test_name,
        }


@dataclass(frozen=True)
class TaskMinerConfig:
    """
    Scoring policy.

    Keeping these values explicit makes the mining policy easy to test and
    change without changing graph parsing.
    """

    public_api_bonus: float = 30.0
    coverage_weight: float = 30.0
    caller_weight: float = 25.0
    complexity_weight: float = 15.0

    side_effect_penalty: float = 35.0
    unknown_call_penalty: float = 5.0

    minimum_coverage: float = 40.0
    minimum_score: float = 10.0

    side_effect_modules: frozenset[str] = (
        DEFAULT_SIDE_EFFECT_MODULES
    )
    side_effect_names: frozenset[str] = (
        DEFAULT_SIDE_EFFECT_NAMES
    )


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def load_repo_graph(
    path: str | Path,
) -> dict[str, Any]:
    """
    Load the deterministic repo_graph.json artifact.

    This function is intentionally read-only.
    """

    graph_path = Path(path)

    with graph_path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(
            "repo_graph.json must contain a JSON object."
        )

    return data


# ---------------------------------------------------------------------------
# Generic graph helpers
# ---------------------------------------------------------------------------

def _items(
    graph: dict[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    value = graph.get(key, [])

    if isinstance(value, list):
        return [
            item
            for item in value
            if isinstance(item, dict)
        ]

    return []


def _node_id(node: dict[str, Any]) -> Optional[str]:
    value = node.get("id")

    if isinstance(value, str):
        return value

    return None


def _node_kind(node: dict[str, Any]) -> Optional[str]:
    for key in ("kind", "type", "node_type"):
        value = node.get(key)

        if isinstance(value, str):
            return value

    return None


def _is_function(node: dict[str, Any]) -> bool:
    return (
        node.get("kind") == "function"
        or (
            node.get("type") == "function"
            and node.get("kind") is None
        )
    )


def _is_public(node: dict[str, Any]) -> bool:
    if isinstance(node.get("public"), bool):
        return node["public"]

    visibility = node.get("visibility")

    if isinstance(visibility, str):
        return visibility.lower() == "public"

    name = node.get("name")

    if isinstance(name, str):
        return not name.startswith("_")

    node_id = _node_id(node) or ""

    name = node_id.rsplit(".", 1)[-1]

    return not name.startswith("_")


def _module_id_for_node(
    node: dict[str, Any],
) -> Optional[str]:
    module_id = node.get("module_id")

    if isinstance(module_id, str):
        return module_id

    module = node.get("module")

    if isinstance(module, str):
        return module

    node_id = _node_id(node)

    if node_id:
        parts = node_id.split(":")

        if len(parts) == 2:
            symbol = parts[1]
            pieces = symbol.rsplit(".", 1)

            if len(pieces) == 2:
                return pieces[0]

    return None


def _line_range(
    node: dict[str, Any],
) -> tuple[int, int]:
    start = node.get("line_start")

    if start is None:
        start = node.get("lineno")

    end = node.get("line_end")

    if end is None:
        end = node.get("end_lineno")

    try:
        start_int = int(start)
    except (TypeError, ValueError):
        start_int = 0

    try:
        end_int = int(end)
    except (TypeError, ValueError):
        end_int = start_int

    return start_int, end_int


def _file_path(
    node: dict[str, Any],
) -> str:
    for key in (
        "file_path",
        "path",
        "source_file",
        "file",
    ):
        value = node.get(key)

        if isinstance(value, str):
            return value.replace("\\", "/")

    return ""


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------

def _edge_source(edge: dict[str, Any]) -> Optional[str]:
    for key in (
        "source",
        "source_id",
        "caller",
        "caller_id",
    ):
        value = edge.get(key)

        if isinstance(value, str):
            return value

    return None


def _edge_target(edge: dict[str, Any]) -> Optional[str]:
    for key in (
        "target",
        "target_id",
        "callee",
        "callee_id",
    ):
        value = edge.get(key)

        if isinstance(value, str):
            return value

    return None


def _edge_kind(edge: dict[str, Any]) -> str:
    for key in (
        "kind",
        "type",
        "edge_type",
    ):
        value = edge.get(key)

        if isinstance(value, str):
            return value.lower()

    return ""


def _call_edges(
    graph: dict[str, Any],
) -> Iterable[dict[str, Any]]:
    """
    Support the relationship representation emitted by Pipeline 2.

    The resolver deliberately accepts both:
      relationships: [...]
    and:
      call_edges: [...]
    """

    for edge in _items(graph, "relationships"):
        kind = _edge_kind(edge)

        if kind in {
            "call",
            "calls",
            "call_edge",
        }:
            yield edge

    for edge in _items(graph, "call_edges"):
        yield edge


# ---------------------------------------------------------------------------
# Coverage extraction
# ---------------------------------------------------------------------------

def _coverage_map(
    graph: dict[str, Any],
) -> dict[str, float]:
    """
    Extract function coverage from the graph.

    Several reasonable Pipeline 2 representations are accepted so the
    miner remains decoupled from incidental serialization details.
    """

    result: dict[str, float] = {}

    for node in _items(graph, "symbols") + _items(graph, "nodes"):
        node_id = _node_id(node)

        if not node_id or not _is_function(node):
            continue

        coverage = node.get("coverage_percent")

        if coverage is None:
            coverage = node.get("coverage")

        if isinstance(coverage, dict):
            coverage = coverage.get("percent")

        try:
            if coverage is not None:
                result[node_id] = float(coverage)
        except (TypeError, ValueError):
            continue

    coverage_section = graph.get("coverage")

    if isinstance(coverage_section, dict):
        for key, value in coverage_section.items():
            try:
                result[str(key)] = float(value)
            except (TypeError, ValueError):
                continue

    return result


# ---------------------------------------------------------------------------
# Side-effect analysis
# ---------------------------------------------------------------------------

def _qualified_call_target(
    edge: dict[str, Any],
) -> str:
    """
    Extract the best available static target representation.
    """

    for key in (
        "target_name",
        "qualified_name",
        "callee_name",
        "target",
        "target_id",
    ):
        value = edge.get(key)

        if isinstance(value, str):
            return value

    return ""


def _side_effect_signals_for_function(
    function_id: str,
    call_edges: Iterable[dict[str, Any]],
    config: TaskMinerConfig,
) -> tuple[str, ...]:
    signals: set[str] = set()

    for edge in call_edges:
        source = _edge_source(edge)

        if source != function_id:
            continue

        target = _qualified_call_target(edge)

        if not target:
            continue

        normalized = target.replace(":", ".").lower()

        pieces = normalized.split(".")

        if any(
            module in normalized
            for module in config.side_effect_modules
        ):
            signals.add(target)
            continue

        name = pieces[-1]

        if name in config.side_effect_names:
            signals.add(target)

    return tuple(sorted(signals))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _coverage_score(
    coverage: Optional[float],
    config: TaskMinerConfig,
) -> float:
    if coverage is None:
        return 0.0

    bounded = max(0.0, min(100.0, coverage))

    return (
        bounded / 100.0
    ) * config.coverage_weight


def _caller_score(
    caller_count: int,
    config: TaskMinerConfig,
) -> float:
    """
    Saturating caller score.

    One caller proves integration relevance; additional callers increase
    confidence without allowing fan-out to dominate every other signal.
    """

    if caller_count <= 0:
        return 0.0

    effective = min(caller_count, 5)

    return (
        effective / 5.0
    ) * config.caller_weight


def _complexity_score(
    node: dict[str, Any],
    config: TaskMinerConfig,
) -> float:
    """
    Prefer functions with enough structural substance to make a useful
    benchmark task, while avoiding enormous functions.

    If Pipeline 2 supplies complexity metadata, use it. Otherwise use a
    conservative default.
    """

    complexity = node.get("complexity")

    if complexity is None:
        complexity = node.get("cyclomatic_complexity")

    if complexity is None:
        return config.complexity_weight * 0.5

    try:
        value = float(complexity)
    except (TypeError, ValueError):
        return config.complexity_weight * 0.5

    # Useful middle range: roughly 3-15.
    if 3 <= value <= 15:
        return config.complexity_weight

    if value < 3:
        return config.complexity_weight * 0.5

    return config.complexity_weight * 0.25


def _score_candidate(
    node: dict[str, Any],
    coverage: Optional[float],
    callers: tuple[str, ...],
    side_effect_signals: tuple[str, ...],
    config: TaskMinerConfig,
) -> tuple[
    float,
    float,
    float,
    float,
    float,
    tuple[str, ...],
]:
    public_bonus = (
        config.public_api_bonus
        if _is_public(node)
        else 0.0
    )

    coverage_score = _coverage_score(
        coverage,
        config,
    )

    caller_score = _caller_score(
        len(callers),
        config,
    )

    complexity_score = _complexity_score(
        node,
        config,
    )

    side_effect_penalty = (
        min(
            len(side_effect_signals),
            3,
        )
        * config.side_effect_penalty
    )

    score = (
        public_bonus
        + coverage_score
        + caller_score
        + complexity_score
        - side_effect_penalty
    )

    rationale: list[str] = []

    if public_bonus:
        rationale.append(
            "public API surface"
        )

    if coverage is not None:
        rationale.append(
            f"coverage={coverage:.1f}%"
        )

    if callers:
        rationale.append(
            f"{len(callers)} internal caller(s)"
        )

    if complexity_score:
        rationale.append(
            "suitable structural complexity"
        )

    if side_effect_signals:
        rationale.append(
            "side-effect signals: "
            + ", ".join(side_effect_signals)
        )

    return (
        score,
        public_bonus,
        coverage_score,
        caller_score,
        complexity_score,
        tuple(rationale),
    )


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _is_excluded_path(path: str) -> bool:
    normalized = _normalized_path(path)
    parts = [part.lower() for part in normalized.split("/") if part]
    if parts and parts[0] == "pipeline":
        return True
    if any(part in EXCLUDED_PATH_PARTS for part in parts):
        return True
    name = Path(normalized).name.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _is_excluded_module(module_id: str) -> bool:
    normalized = module_id.replace("module:", "").replace("\\", "/")
    return any(
        normalized == prefix or normalized.startswith(prefix + ".") or normalized.startswith(prefix + "/")
        for prefix in EXCLUDED_MODULE_PREFIXES
    )


def _module_from_file(path: str) -> str:
    normalized = _normalized_path(path)
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    if normalized.endswith("/__init__"):
        normalized = normalized[:-9]
    return normalized.replace("/", ".")


def _test_files(repo_path: Path) -> list[Path]:
    """Return repository test modules, excluding benchmark/generated areas."""
    result: list[Path] = []
    for path in repo_path.rglob("*.py"):
        try:
            relative = path.relative_to(repo_path)
        except ValueError:
            continue

        relative_text = relative.as_posix()
        if _is_excluded_path(relative_text):
            # _is_excluded_path also excludes test files, so handle tests
            # explicitly below instead of using it here.
            parts = {part.lower() for part in relative.parts}
            if any(part in EXCLUDED_PATH_PARTS for part in parts):
                continue
            if parts and "pipeline" in parts:
                continue

        parts = {part.lower() for part in relative.parts}
        if any(part in EXCLUDED_PATH_PARTS for part in parts):
            continue
        if relative.parts and relative.parts[0].lower() == "pipeline":
            continue

        name = path.name.lower()
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        result.append(path)

    return sorted(result, key=lambda path: path.relative_to(repo_path).as_posix())


def _candidate_module_imports(module_id: str, source_file: str) -> set[str]:
    imports = set()
    normalized = module_id.replace("module:", "").replace("/", ".")
    if normalized:
        imports.add(normalized)

    if source_file:
        source_module = _module_from_file(source_file)
        if source_module:
            imports.add(source_module)

    return imports


def _call_mentions_function(
    node: ast.AST,
    function_name: str,
    aliases: set[str],
    direct_names: set[str],
    module_names: set[str],
) -> bool:
    """Return whether a test node calls the candidate with several AST forms."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        func = child.func

        if isinstance(func, ast.Name) and func.id in direct_names:
            return True

        if isinstance(func, ast.Attribute) and func.attr == function_name:
            value = func.value
            if isinstance(value, ast.Name) and value.id in aliases:
                return True

            # Also recognize direct module-qualified calls such as
            # glom.core.foo(...), which are common in older repositories.
            dotted: list[str] = []
            current: ast.AST | None = func
            while isinstance(current, ast.Attribute):
                dotted.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                dotted.append(current.id)
                dotted_name = ".".join(reversed(dotted))
                if any(
                    dotted_name == f"{module}.{function_name}"
                    or dotted_name.endswith(f".{module}.{function_name}")
                    for module in module_names
                ):
                    return True

        if isinstance(func, ast.Name) and func.id == function_name:
            return True

    return False


def _import_evidence(
    tree: ast.AST,
    module_imports: set[str],
    function_name: str,
) -> tuple[set[str], set[str], set[str]]:
    aliases: set[str] = set()
    direct: set[str] = set()
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    alias.name == module
                    or alias.name.startswith(module + ".")
                    for module in module_imports
                ):
                    aliases.add(alias.asname or alias.name.split(".")[0])
                    imported_modules.add(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(
                module == candidate
                or module.startswith(candidate + ".")
                for candidate in module_imports
            ):
                imported_modules.add(module)
                for alias in node.names:
                    if alias.name == function_name or alias.name == "*":
                        direct.add(alias.asname or alias.name)

    return aliases, direct, imported_modules


def _test_path_score(
    repo_path: Path,
    test_path: Path,
    module_id: str,
    source_file: str,
) -> tuple[int, int, int, int, str]:
    """Score repository tests by path proximity to the candidate module."""
    rel = test_path.relative_to(repo_path).as_posix()
    source = _normalized_path(source_file)
    source_path = Path(source)
    stem = source_path.stem
    source_parent = source_path.parent.as_posix()
    module = module_id.replace("module:", "").replace("\\", "/").replace(".", "/")

    exact_name = int(test_path.name.lower() == f"test_{stem.lower()}.py")
    same_dir = int(test_path.parent.relative_to(repo_path).as_posix() == source_parent)
    conventional_glom_test = int(
        test_path.name.lower() == f"test_{stem.lower()}.py"
        and test_path.parent.name.lower() == "test"
        and source_parent.endswith(Path(module).parent.as_posix())
    )
    module_stem_match = int(stem.lower() in test_path.stem.lower())

    # Prefer exact test_<module>.py, then same package/test directory, then
    # filename/module proximity. The path itself is the final stable tie-break.
    return (
        conventional_glom_test,
        exact_name,
        same_dir,
        module_stem_match,
        rel,
    )


def _find_unique_test_oracle(
    repo_path: Optional[Path],
    module_id: str,
    source_file: str,
    function_name: str,
) -> Optional[tuple[str, str]]:
    """Find the closest AST-associated repository test, not necessarily a unique one.

    Association is intentionally permissive: multiple tests can legitimately
    exercise a public function. We rank them by repository/path proximity,
    import evidence, and direct call evidence, then choose the deterministic
    best match. Generated/benchmark directories never participate.
    """
    if _is_excluded_path(source_file) or _is_excluded_module(module_id):
        return None
    # Unit callers that provide only a graph do not have filesystem context.
    # Preserve the graph-only mining API; the repository-aware orchestrator
    # supplies repo_path and therefore gets the strict test-oracle guard.
    if repo_path is None:
        return None

    module_imports = _candidate_module_imports(module_id, source_file)
    module_names = set(module_imports)
    candidates: list[tuple[tuple[int, int, int, int, int, int, str, str], str, str]] = []

    for test_path in _test_files(repo_path):
        try:
            tree = ast.parse(
                test_path.read_text(encoding="utf-8"),
                filename=str(test_path),
            )
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        aliases, direct, imported_modules = _import_evidence(
            tree,
            module_imports,
            function_name,
        )
        imported_here = bool(aliases or direct or imported_modules)
        if not imported_here:
            continue

        path_score = _test_path_score(
            repo_path,
            test_path,
            module_id,
            source_file,
        )

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            direct_match = _call_mentions_function(
                node,
                function_name,
                aliases,
                direct,
                module_names | imported_modules,
            )

            if not direct_match:
                # A repository test may exercise the candidate indirectly
                # through another public API. Do not discard the candidate
                # merely because the function name is absent from the test
                # AST. Only permit this fallback for a conventional exact
                # test module; the verifier will still require the selected
                # test to fail after the candidate is excised.
                path_score = _test_path_score(
                    repo_path,
                    test_path,
                    module_id,
                    source_file,
                )
                if not (
                    path_score[0] or path_score[1]
                ):
                    continue

            qualified_name = node.name
            for parent in ast.walk(tree):
                if isinstance(parent, ast.ClassDef) and node in parent.body:
                    qualified_name = f"{parent.name}::{node.name}"
                    break

            # Higher is better. Direct import/call evidence dominates path
            # proximity only where the path is not already an exact module test.
            exact_path = path_score[0] + path_score[1]
            score = (
                exact_path,
                path_score[2],
                path_score[3],
                int(bool(direct)),
                int(bool(aliases)),
                int(bool(imported_modules)),
                path_score[4],
                qualified_name,
            )
            candidates.append(
                (score, test_path.relative_to(repo_path).as_posix(), qualified_name)
            )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, test_file, test_name = candidates[0]
    return test_file, test_name


# ---------------------------------------------------------------------------
# Miner
# ---------------------------------------------------------------------------

class TaskMiner:
    """
    Deterministic, read-only miner for Excision candidates.
    """

    def __init__(
        self,
        config: Optional[TaskMinerConfig] = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else TaskMinerConfig()
        )

    def mine_excision_candidates(
        self,
        graph: dict[str, Any],
        repo_path: str | Path | None = None,
    ) -> list[ExcisionCandidate]:
        root = Path(repo_path).resolve() if repo_path is not None else None

        symbols = [
            node
            for node in _items(graph, "symbols") + _items(graph, "nodes")
            if _is_function(node)
            and not _is_excluded_path(_file_path(node))
            and not _is_excluded_module(str(_module_id_for_node(node) or ""))
        ]

        function_ids = {
            node_id
            for node in symbols
            if (node_id := _node_id(node))
        }

        callers_by_target: dict[str, set[str]] = {
            function_id: set()
            for function_id in function_ids
        }

        call_edges = list(
            _call_edges(graph)
        )

        for edge in call_edges:
            source = _edge_source(edge)
            target = _edge_target(edge)

            if (
                source in function_ids
                and target in function_ids
                and source != target
            ):
                callers_by_target[target].add(source)

        coverage = _coverage_map(graph)

        candidates: list[ExcisionCandidate] = []

        for node in symbols:
            function_id = _node_id(node)

            if function_id is None:
                continue

            module_id = _module_id_for_node(node)
            source_file = _file_path(node)

            # Some OKF graphs put the source path only on the module node.
            # Reconstruct the conventional Python path for graph-only and
            # partially normalized inputs; run_tasks also propagates module
            # paths during repository-aware loading.
            if not source_file and module_id:
                module_name = module_id.replace("module:", "").replace("\\", "/").replace(".", "/")
                source_file = module_name + ".py"

            if module_id is None or not source_file:
                continue

            associated = _find_unique_test_oracle(
                root,
                module_id,
                source_file,
                str(node.get("name", function_id.rsplit(".", 1)[-1])),
            )
            if root is not None and associated is None:
                continue

            associated_test_file, associated_test_name = associated or (None, None)

            coverage_percent = coverage.get(
                function_id
            )

            # Very poorly covered functions are less useful as Excision
            # candidates because their behavior is harder to establish.
            if (
                coverage_percent is not None
                and coverage_percent < self.config.minimum_coverage
            ):
                continue

            callers = tuple(
                sorted(
                    callers_by_target.get(
                        function_id,
                        set(),
                    )
                )
            )

            side_effect_signals = (
                _side_effect_signals_for_function(
                    function_id,
                    call_edges,
                    self.config,
                )
            )

            (
                score,
                public_bonus,
                coverage_score,
                caller_score,
                complexity_score,
                rationale,
            ) = _score_candidate(
                node,
                coverage_percent,
                callers,
                side_effect_signals,
                self.config,
            )

            side_effect_penalty = (
                min(
                    len(side_effect_signals),
                    3,
                )
                * self.config.side_effect_penalty
            )

            if score < self.config.minimum_score:
                continue

            line_start, line_end = _line_range(node)

            candidate = ExcisionCandidate(
                function_id=function_id,
                module_id=module_id,
                name=str(
                    node.get(
                        "name",
                        function_id.rsplit(".", 1)[-1],
                    )
                ),
                file_path=_file_path(node),
                line_start=line_start,
                line_end=line_end,
                public=_is_public(node),
                callers=callers,
                caller_count=len(callers),
                coverage_percent=coverage_percent,
                side_effect_signals=side_effect_signals,
                side_effect_penalty=side_effect_penalty,
                public_api_bonus=public_bonus,
                coverage_score=coverage_score,
                caller_score=caller_score,
                complexity_score=complexity_score,
                score=score,
                rationale=(
                    rationale
                    + ((
                        f"test oracle={associated_test_file}::{associated_test_name}",
                    ) if associated_test_file and associated_test_name else ())
                ),
                associated_test_file=associated_test_file,
                associated_test_name=associated_test_name,
            )

            candidates.append(candidate)

        # Stable tie-breaking is essential for reproducible task generation.
        candidates.sort(
            key=lambda candidate: (
                -candidate.score,
                -(
                    candidate.coverage_percent
                    if candidate.coverage_percent is not None
                    else -1.0
                ),
                -candidate.caller_count,
                candidate.module_id,
                candidate.function_id,
            )
        )

        return candidates


def mine_excision_candidates(
    graph: dict[str, Any],
    config: Optional[TaskMinerConfig] = None,
    repo_path: str | Path | None = None,
) -> list[ExcisionCandidate]:
    """
    Functional convenience API.
    """

    return TaskMiner(
        config=config
    ).mine_excision_candidates(graph, repo_path=repo_path)


def mine_excision_candidates_from_file(
    graph_path: str | Path,
    config: Optional[TaskMinerConfig] = None,
    repo_path: str | Path | None = None,
) -> list[ExcisionCandidate]:
    graph = load_repo_graph(graph_path)

    return mine_excision_candidates(
        graph,
        config=config,
    )