# pipeline/run_tasks.py
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from pipeline.task_verifier import TaskVerifier, VerifierConfig
from pipeline.discover import discover_repo
from pipeline.task_history import HistoryChange, mine_history_candidates
from pipeline.task_miner import ExcisionCandidate, mine_excision_candidates
from pipeline.task_schema import TaskIndex, TaskManifest
from pipeline.task_synthesis import (
    NetNewCandidate,
    TaskSynthesisError,
    TaskSynthesizer,
)


TOTAL_TASKS = 10
HISTORY_QUOTA = 4
EXCISION_QUOTA = 4
NET_NEW_QUOTA = 2
MIN_MODULES = 4

TASK_ROOT = Path("tasks")
TASKS_JSON = Path("tasks.json")
GRAPH_PATH = Path(".okf") / "repo_graph.json"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """
    Convert one of our dataclasses / enums / paths into deterministic JSON.
    """
    if is_dataclass(value):
        return {
            key: _jsonable(val)
            for key, val in asdict(value).items()
        }

    if hasattr(value, "value"):
        return _jsonable(value.value)

    if isinstance(value, Path):
        return value.as_posix()

    if isinstance(value, dict):
        return {
            str(key): _jsonable(val)
            for key, val in sorted(
                value.items(),
                key=lambda item: str(item[0]),
            )
        }

    if isinstance(value, (list, tuple)):
        return [
            _jsonable(item)
            for item in value
        ]

    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            _jsonable(value),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()[:16]


def _call_compatible(
    function,
    candidates: list[tuple[Any, ...]],
):
    """
    Select an actually compatible positional signature using inspect.signature().
    Any exception raised *inside* the execution of the function will propagate.
    """
    sig = inspect.signature(function)
    last_error = None

    for args in candidates:
        try:
            sig.bind(*args)
        except TypeError as exc:
            last_error = exc
            continue
        
        return function(*args)

    raise TypeError(
        f"Could not call {function.__name__} with any supported signature."
    ) from last_error

def _load_graph(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(payload, dict):
        raise RuntimeError(
            "repo_graph.json must be a JSON object"
        )

    raw_graph = payload.get("graph")

    if not isinstance(raw_graph, dict):
        raise RuntimeError(
            "repo_graph.json missing graph object"
        )

    nodes = raw_graph.get("nodes", [])
    edges = raw_graph.get("edges", [])

    if not isinstance(nodes, list):
        raise RuntimeError(
            "graph.nodes must be a list"
        )

    if not isinstance(edges, list):
        raise RuntimeError(
            "graph.edges must be a list"
        )

    # Index modules to resolve missing function paths
    modules_by_id = {
        n.get("id"): n for n in nodes 
        if n.get("type", n.get("kind", "")) == "module"
    }

    # Propagate module paths to symbols so Excision candidates know their file
    for node in nodes:
        if node.get("type", node.get("kind", "")) in {"class", "function", "method", "symbol"}:
            if not node.get("file_path") and not node.get("path"):
                mod = modules_by_id.get(node.get("module_id"))
                if mod:
                    node["file_path"] = mod.get("path", mod.get("file_path", ""))

    return {
        "schema_version": payload.get("schema_version"),
        "nodes": nodes,
        "edges": edges,
        "modules": list(modules_by_id.values()),
        "symbols": [n for n in nodes if n.get("type", n.get("kind", "")) in {"class", "function", "method", "symbol"}],
        "relationships": edges,
        "call_edges": edges,
    }


# ---------------------------------------------------------------------------
# Candidate normalization
# ---------------------------------------------------------------------------


def _as_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    return list(value)


def _candidate_module(candidate: Any) -> str:
    for name in (
        "module",
        "module_id",
        "module_name",
    ):
        value = getattr(candidate, name, None)
        if value:
            value = str(value)
            if value.startswith("module:"):
                value = value[len("module:"):]
            return value

    modules = getattr(candidate, "modules", ())
    if modules:
        values = sorted(
            {
                str(module).replace("module:", "")
                for module in modules
                if str(module).strip()
            }
        )
        if values:
            return values[0]

    function_id = getattr(candidate, "function_id", "")
    if function_id:
        value = str(function_id)
        if value.startswith("function:"):
            value = value[len("function:"):]
        parts = value.split(".")
        if len(parts) >= 2:
            return ".".join(parts[:-1])

    return "unknown"


def _candidate_id(candidate: Any) -> str:
    for name in (
        "task_id",
        "function_id",
        "commit",
        "id",
    ):
        value = getattr(
            candidate,
            name,
            None,
        )

        if value:
            return str(value)

    return _fingerprint(candidate)


def _candidate_score(candidate: Any) -> float:
    value = getattr(
        candidate,
        "score",
        0.0,
    )

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Mining
# ---------------------------------------------------------------------------


def _mine_excision(
    repo_path: Path,
    graph: dict[str, Any],
    context,
):
    """
    Adapt to the tested TaskMiner implementation.

    The preferred API is:

        mine_excision_candidates(repo_graph)

    but common repository/context-aware forms are also accepted.
    """

    from pipeline import task_miner

    function = getattr(
        task_miner,
        "mine_excision_candidates",
        None,
    )

    if function is None:
        function = getattr(
            task_miner,
            "mine_excision",
            None,
        )

    if function is None:
        raise RuntimeError(
            "task_miner does not expose an excision mining function."
        )

    result = _call_compatible(
        function,
        [
            (graph,),
            (repo_path, graph),
            (repo_path, context, graph),
            (graph, context),
        ],
    )

    return sorted(
        _as_list(result),
        key=lambda candidate: (
            -_candidate_score(candidate),
            _candidate_module(candidate),
            _candidate_id(candidate),
        ),
    )

def _history_verification_command(
    candidate: Any,
) -> Optional[list[str]]:
    """
    Build a targeted pytest command for a history candidate.

    Prefers the specific "path::function" node IDs for the test
    function(s) the fixing commit actually changed (regression_node_ids)
    over whole test files. Whole files can bundle unrelated,
    pre-existing breakage (compatibility issues, missing fixtures) that
    has nothing to do with the mined commit, which pollutes the
    fail-before/pass-after verdict. Mining now fails candidates closed
    when no node ID can be pinpointed, so this should always have node
    IDs available; the whole-file fallback exists only for
    candidates constructed some other way.
    """
    node_ids = getattr(
        candidate,
        "regression_node_ids",
        (),
    )

    if node_ids:
        return [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *sorted(
                str(node_id).replace("\\", "/")
                for node_id in node_ids
            ),
        ]

    test_files = getattr(candidate, "test_files", ())

    python_tests = sorted(
        {
            str(path).replace("\\", "/")
            for path in test_files
            if str(path).lower().endswith(".py")
        }
    )

    if not python_tests:
        return None

    return [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *python_tests,
    ]

def _qualify_history_candidate(
    candidate: Any,
    synthesizer: TaskSynthesizer,
    verifier: TaskVerifier,
    repo_path: Path,
) -> bool:
    """
    Accept a history candidate only when it demonstrates:

        parent  -> FAIL
        commit  -> PASS
        commit  -> PASS again

    This is a discovery-time qualification step. It prevents the final
    task quota from being filled with commits that merely look behavioral
    from Git metadata.
    """

    temporary_root = (
        repo_path / ".pipeline_history_probe"
        / str(candidate.commit)[:12]
    )

    shutil.rmtree(
        temporary_root,
        ignore_errors=True,
    )

    try:
        synthesis = synthesizer.synthesize_history(
            candidate,
            temporary_root,
        )

        command = _task_command_for_candidate(
            task_type="history",
            candidate=candidate,
            baseline_command=[],
            repo_path=repo_path,
            synthesis=synthesis,
        )

        result = verifier.verify(
            input_dir=synthesis.input_dir,
            solution_dir=synthesis.solution_dir,
            command=command,
            evidence_dir=temporary_root / "evidence",
            task_id=f"history-probe-{candidate.commit[:12]}",
            oracle_dir=synthesis.verifier_dir,
        )

        validation = result.validation

        accepted = bool(
            validation is not None
            and validation.fail_before_verified
            and validation.pass_after_verified
            and validation.deterministic_verified
            and validation.validation_passed
        )

        print(
            f"    history {candidate.commit[:12]}: "
            f"fail_before={getattr(validation, 'fail_before_verified', None)}, "
            f"pass_after={getattr(validation, 'pass_after_verified', None)}, "
            f"deterministic={getattr(validation, 'deterministic_verified', None)}, "
            f"valid={getattr(validation, 'validation_passed', None)}"
        )

        if not accepted and validation is not None:
            print(
                f"      reasons={validation.reasons}"
            )

        return accepted

    except Exception as exc:
        print(
            f"    HISTORY QUALIFICATION ERROR "
            f"{candidate.commit[:12]}: "
            f"{type(exc).__name__}: {exc}"
        )
        return False

    finally:
        shutil.rmtree(
            temporary_root,
            ignore_errors=True,
        )

def _mine_history(
    repo_path: Path,
):
    function = mine_history_candidates

    result = _call_compatible(
        function,
        [
            (repo_path,),
            (str(repo_path),),
        ],
    )

    return sorted(
        _as_list(result),
        key=lambda candidate: (
            -_candidate_score(candidate),
            str(
                getattr(
                    candidate,
                    "commit",
                    "",
                )
            ),
            str(
                getattr(
                    candidate,
                    "subject",
                    "",
                )
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Net-new candidates
# ---------------------------------------------------------------------------

def _make_net_new_candidates(
    graph: dict[str, Any],
) -> list[NetNewCandidate]:
    nodes = graph.get("nodes", [])

    if not isinstance(nodes, list):
        return []

    module_names: list[tuple[str, str]] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue

        if node.get("type") != "module":
            continue

        module_name = (
            node.get("module_name")
            or node.get("name")
            or str(node.get("id", "")).removeprefix("module:")
        )

        source_file = (
            node.get("path")
            or node.get("file_path")
        )

        if not module_name or not source_file:
            continue

        normalized_path = str(source_file).replace("\\", "/")

        if not normalized_path.endswith(".py"):
            continue

        if normalized_path.endswith("__init__.py"):
            continue

        if module_name.startswith("docs.") or module_name.startswith("tests."):
            continue

        if module_name in {
            "glom.__main__",
            "glom.cli",
        }:
            continue

        path_parts = set(normalized_path.split("/"))
        if path_parts.intersection({".venv", "build", "dist", "__pycache__"}):
            continue

        module_names.append((str(module_name), normalized_path))

    module_names = sorted(set(module_names), key=lambda item: (item[0], item[1]))

    candidates: list[NetNewCandidate] = []

    for module_name, source_file in module_names:
        function_name = "__benchmark_new_behavior"

        candidates.append(
            NetNewCandidate(
                module=module_name,
                source_file=source_file,
                function_name=function_name,
                signature=f"def {function_name}(value)",
                description="Return the supplied value unchanged.",
                stub_body="return None",
                solution_body="return value",
                rationale=(
                    "Synthetic net-new identity behavior anchored to "
                    "an existing repository Python module."
                ),
            )
        )
        

    return candidates




# ---------------------------------------------------------------------------
# Verifier adapter
# ---------------------------------------------------------------------------


def _verify(
    verifier,
    input_dir: Path,
    solution_dir: Path,
    verifier_dir: Path,
    task_command: list[str],
    task_id: str,
    oracle_dir: Optional[Path] = None,
):
    return verifier.verify(
        input_dir=input_dir,
        solution_dir=solution_dir,
        command=task_command,
        evidence_dir=verifier_dir,
        task_id=task_id,
        oracle_dir=oracle_dir,
    )

# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _write_verification_evidence(
    task_root: Path,
    verification: Any,
) -> None:
    evidence = (
        task_root
        / "evidence"
    )

    evidence.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = _jsonable(
        verification
    )

    if not isinstance(
        data,
        dict,
    ):
        data = {
            "result": data,
        }

    # Preserve the exact three-state evidence contract.
    fail_before = data.get(
        "fail_before"
    )

    pass_after = data.get(
        "pass_after"
    )

    determinism = data.get(
        "determinism"
    )

    if fail_before is None:
        fail_before = {
            "passed": data.get(
                "fail_before_passed",
                False,
            )
        }

    if pass_after is None:
        pass_after = {
            "passed": data.get(
                "pass_after_passed",
                False,
            )
        }

    if determinism is None:
        determinism = {
            "passed": data.get(
                "deterministic",
                data.get(
                    "determinism_passed",
                    False,
                ),
            )
        }

    _write_json(
        evidence / "fail_before.json",
        fail_before,
    )

    _write_json(
        evidence / "pass_after.json",
        pass_after,
    )

    _write_json(
        evidence / "determinism.json",
        determinism,
    )

    _write_json(
        evidence / "verification.json",
        data,
    )


# ---------------------------------------------------------------------------
# Task materialization
# ---------------------------------------------------------------------------


def _baseline_command(baseline) -> list[str]:
    if baseline is None or not baseline.test_runs:
        raise RuntimeError("A successful baseline test command is required.")

    command = list(baseline.test_runs[0].command)
    if not command:
        raise RuntimeError("Baseline test command is empty.")

    command[0] = sys.executable

    repo_path = Path(".").resolve()
    repo_name = repo_path.name

    normalized = []

    for part in command:
        value = str(part)

        try:
            path = Path(value)

            if path.is_absolute():
                resolved = path.resolve()

                try:
                    relative = resolved.relative_to(repo_path)
                    value = relative.as_posix()
                except ValueError:
                    # Baseline may have run against a temp copy of the repo
                    # (e.g. tempfile.mkdtemp(prefix="repo-baseline-workspace-")).
                    # Strip everything up to and including the workspace root
                    # (first occurrence of the repo's own directory name) so
                    # the command stays portable.
                    parts = resolved.parts
                    idx = next(
                        (i for i, p in enumerate(parts) if p == repo_name),
                        None,
                    )
                    if idx is not None and idx + 1 < len(parts):
                        value = Path(*parts[idx + 1:]).as_posix()

        except (OSError, ValueError):
            pass

        normalized.append(value.replace("\\", "/"))

    return normalized


def _materialize_verifier_directory(
    task_root: Path,
) -> Path:
    """
    Create the required verifier/ directory.

    The TaskVerifier owns the actual oracle; this directory is the stable
    task artifact location for verifier-side material.
    """

    verifier_dir = (
        task_root
        / "verifier"
    )

    verifier_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    _write_json(
        verifier_dir / "contract.json",
        {
            "state_machine": [
                "fail_before",
                "pass_after",
                "determinism",
            ],
            "strict": True,
        },
    )

    return verifier_dir


def _task_title(
    task_type: str,
    candidate: Any,
) -> str:
    """Derive a short deterministic title from candidate metadata."""
    subject = getattr(candidate, "subject", None)
    if subject:
        return str(subject).strip()

    function_id = (
        getattr(candidate, "function_id", None)
        or getattr(candidate, "target", None)
        or getattr(candidate, "function_name", None)
    )

    if function_id:
        target = str(function_id)
        if task_type == "excision":
            return f"Restore behavior of {target}"
        if task_type == "net_new":
            return f"Implement new behavior in {target}"
        return f"Implement historical fix for {target}"

    commit = getattr(candidate, "commit", None)
    if commit:
        return f"Implement historical fix {str(commit)[:12]}"

    description = getattr(candidate, "description", None)
    if description:
        return str(description).strip()

    module = _candidate_module(candidate)
    return f"{task_type.replace('_', '-').title()} task for {module}"


def _task_instruction(
    task_type: str,
    candidate: Any,
) -> str:
    """Build an implementation-neutral task instruction."""
    module = _candidate_module(candidate)

    function_id = (
        getattr(candidate, "function_id", None)
        or getattr(candidate, "target", None)
        or getattr(candidate, "function_name", None)
    )

    if task_type == "history":
        commit = getattr(candidate, "commit", None)
        if commit:
            return (
                f"Implement the behavioral correction required by the task-local "
                f"regression tests in module {module}. "
                "The implementation must satisfy the task-local regression tests."
            )
        return (
            f"Implement the required historical behavioral correction in module "
            f"{module} so that the task-local regression tests pass."
        )

    if task_type == "excision":
        target = str(function_id or module)
        return (
            f"Restore the required behavior of {target}. "
            "The implementation must satisfy the existing task-local tests."
        )

    description = getattr(candidate, "description", None)
    if description:
        return (
            f"Implement the new behavior for {module}: "
            f"{str(description).strip()} "
            "The implementation must satisfy the task-local tests."
        )

    target = str(function_id or module)
    return (
        f"Implement the specified new behavior for {target} "
        "according to the task-local tests."
    )


def _task_provenance(
    task_type: str,
    candidate: Any,
) -> dict[str, Any]:
    """Return rubric-facing provenance without changing candidate data."""
    module = _candidate_module(candidate)

    if task_type == "history":
        return {
            "source": "history-derived",
            "parent_commit": getattr(candidate, "parent", None),
            "fixing_commit": getattr(candidate, "commit", None),
        }

    target = (
        getattr(candidate, "function_id", None)
        or getattr(candidate, "target", None)
        or getattr(candidate, "function_name", None)
        or _candidate_id(candidate)
    )

    return {
        "source": (
            "excision"
            if task_type == "excision"
            else "net-new"
        ),
        "target_function": str(target),
        "module": module,
    }


def _task_files_in_scope(
    task_type: str,
    candidate: Any,
    synthesis: Any,
) -> list[str]:
    """Collect deterministic source files relevant to the generated task."""
    values: list[Any] = []

    synthesis_data = _jsonable(synthesis)
    if isinstance(synthesis_data, dict):
        for key in ("changed_files", "source_files", "files_in_scope"):
            value = synthesis_data.get(key)
            if isinstance(value, (list, tuple)):
                values.extend(value)
            elif value:
                values.append(value)

    for name in (
        "files",
        "source_files",
        "test_files",
    ):
        value = getattr(candidate, name, None)
        if isinstance(value, (list, tuple)):
            values.extend(value)
        elif value:
            values.append(value)

    for name in (
        "source_file",
        "file_path",
        "path",
    ):
        value = getattr(candidate, name, None)
        if value:
            values.append(value)

    result = sorted(
        {
            str(value).replace("\\", "/")
            for value in values
            if str(value).strip()
        }
    )

    return result


def _task_difficulty(
    task_type: str,
    files_in_scope: list[str],
) -> tuple[str, str]:
    """Assign deterministic difficulty from the task's implementation scope."""
    file_count = len(files_in_scope)

    if file_count <= 1:
        return (
            "easy",
            "The task is localized to a single file, so the implementation "
            "scope is narrow and focused.",
        )

    if file_count <= 3:
        return (
            "medium",
            f"The task spans {file_count} files, requiring coordination across "
            "a small but non-trivial implementation scope.",
        )

    return (
        "hard",
        f"The task spans {file_count} files, creating a broader implementation "
        "scope and requiring coordination across multiple repository areas.",
    )

def _sanitized_validation_summary(verification: Any) -> dict[str, Any]:
    """
    Extract only the pass/fail verdict from a verification result.

    The full verification result embeds the literal commands, stdout, and
    stderr captured per stage — captured against whatever temp workspace
    happened to be in use on this machine (baseline copy, pytest's own
    tmp_path fixture, etc). That raw detail is host-specific and must stay
    confined to evidence/*.json; it must never be baked into task.json or
    goldenSolution.md.
    """
    data = _jsonable(verification)

    if not isinstance(data, dict):
        return {"validation_passed": _verification_passed(verification)}

    validation = data.get("validation")
    if not isinstance(validation, dict):
        validation = data

    return {
        "fail_before_verified": validation.get("fail_before_verified"),
        "pass_after_verified": validation.get("pass_after_verified"),
        "deterministic_verified": validation.get("deterministic_verified"),
        "validation_passed": validation.get(
            "validation_passed",
            _verification_passed(verification),
        ),
        "reasons": validation.get("reasons", []),
    }

def _write_task_manifest(
    task_root: Path,
    task_type: str,
    candidate: Any,
    synthesis,
    verification,
    verifier_command: list[str],
) -> dict[str, Any]:
    candidate_data = _jsonable(
        candidate
    )

    verification_data = _jsonable(
        verification
    )

    module = _candidate_module(
        candidate
    )

    candidate_key = _candidate_id(
        candidate
    )

    task_id = (
        f"{task_type}:"
        f"{_fingerprint(candidate_data)}"
    )

    files_in_scope = _task_files_in_scope(
        task_type=task_type,
        candidate=candidate,
        synthesis=synthesis,
    )

    difficulty, difficulty_reason = _task_difficulty(
        task_type=task_type,
        files_in_scope=files_in_scope,
    )

    validation_status = (
        "passed"
        if _verification_accepted(verification)
        else "failed"
    )

    manifest = {
        "schema_version": "1.0",
        "id": task_id,
        "task_id": task_id,
        "title": _task_title(
            task_type,
            candidate,
        ),
        "instruction": _task_instruction(
            task_type,
            candidate,
        ),
        "provenance": _task_provenance(
            task_type,
            candidate,
        ),
        "difficulty": difficulty,
        "difficulty_reason": difficulty_reason,
        "files_in_scope": files_in_scope,
        "verifier_command": list(verifier_command),
        "validation_status": validation_status,
        "type": task_type,
        "module": module,
        "candidate": candidate_data,
        "paths": {
            "input": "input",
            "solution": "solution",
            "verifier": "verifier",
            "evidence": "evidence",
        },
        "synthesis": _jsonable(
            synthesis
        ),
        "verification": _sanitized_validation_summary(
    verification
),
        "accepted": _verification_passed(
            verification
        ),
    }

    _write_json(
        task_root / "task.json",
        manifest,
    )

    return manifest




def _write_golden_solution(
    task_dir: Path,
    task_type: str,
    candidate: Any,
    verification_result: Any,
    repo_path: Path,
) -> None:
    """Write the mandatory goldenSolution.md artifact for an accepted task."""
    if task_type == "history":
        parent = getattr(candidate, "parent", None)
        commit = getattr(candidate, "commit", None)

        if not parent and commit:
            completed = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    f"{commit}^",
                ],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
            parent = completed.stdout.strip()

        if not parent or not commit:
            raise RuntimeError(
                "History task is missing parent/fixing commit SHA for golden solution."
            )

        diff_result = subprocess.run(
            [
                "git",
                "diff",
                parent,
                commit,
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
        reference_diff = diff_result.stdout.strip()
        provenance = (
            f"Source: history-derived\n"
            f"Parent commit: `{parent}`\n"
            f"Fixing commit: `{commit}`"
        )
        why_correct = (
            "The reference solution is the actual change introduced by the "
            "fixing commit. The input state is the parent commit, while the "
            "solution state is the post-fix commit, so this diff captures the "
            "repository's real historical behavioral correction."
        )

    elif task_type in {"excision", "net_new"}:
        input_dir = task_dir / "input"
        solution_dir = task_dir / "solution"

        if not input_dir.is_dir() or not solution_dir.is_dir():
            raise RuntimeError(
                f"Cannot create golden solution: missing input/ or solution/ in {task_dir}"
            )

        diff_result = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--",
                str(input_dir),
                str(solution_dir),
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        # git diff --no-index returns 1 when differences exist; that is the
        # expected result for an input/solution pair with a reference change.
        if diff_result.returncode not in {0, 1}:
            raise RuntimeError(
                "Unable to generate golden solution diff for "
                f"{task_type} task {task_dir}: {diff_result.stderr.strip()}"
            )

        reference_diff = diff_result.stdout.strip()
        module = _candidate_module(candidate)
        function_id = getattr(candidate, "function_id", None)
        candidate_id = function_id or _candidate_id(candidate)

        if task_type == "excision":
            provenance = (
                "Source: excision (red → green)\n"
                f"Target module: `{module}`\n"
                f"Target: `{candidate_id}`"
            )
            why_correct = (
                "The input state contains the selected implementation removed "
                "from its original function, while solution/ preserves the "
                "working repository implementation. Therefore the input-to-solution "
                "diff is the original implementation that restores the behavior "
                "required by the verifier."
            )
        else:
            provenance = (
                "Source: net-new feature\n"
                f"Target module: `{module}`\n"
                f"Target: `{candidate_id}`"
            )
            why_correct = (
                "The solution state contains the repository plus the reference "
                "implementation for the newly specified behavior, while input/ "
                "contains the deliberately failing starting state. The input-to-"
                "solution diff therefore represents the reference implementation "
                "that satisfies the task-local behavioral contract."
            )

    else:
        raise RuntimeError(
            f"Unsupported task type for golden solution: {task_type}"
        )

    validation = _sanitized_validation_summary(verification_result)
    validation_text = json.dumps(
        validation,
        indent=2,
        sort_keys=True,
    )

    if not reference_diff:
        reference_diff = "(No textual diff was produced.)"

    content = (
        "# Golden Solution\n\n"
        "## Provenance\n\n"
        f"{provenance}\n\n"
        "## Reference Diff\n\n"
        "```diff\n"
        f"{reference_diff}\n"
        "```\n\n"
        "## Why this is correct\n\n"
        f"{why_correct}\n\n"
        "## Validation\n\n"
        "The task was accepted only after the strict verifier completed its "
        "required validation state machine. The machine-generated verification "
        "result is recorded below.\n\n"
        "```json\n"
        f"{validation_text}\n"
        "```\n"
    )

    (task_dir / "goldenSolution.md").write_text(
        content,
        encoding="utf-8",
    )

def _verification_passed(
    result: Any,
) -> bool:
    if result is None:
        return False

    for name in (
        "accepted",
        "valid",
        "validation_passed",
        "passed",
    ):
        value = getattr(
            result,
            name,
            None,
        )

        if value is True:
            return True

    if isinstance(
        result,
        dict,
    ):
        for name in (
            "accepted",
            "valid",
            "validation_passed",
            "passed",
        ):
            if result.get(name) is True:
                return True

        validation = result.get(
            "validation"
        )

        if isinstance(
            validation,
            dict,
        ):
            return validation.get(
                "validation_passed",
                validation.get(
                    "passed",
                    False,
                ),
            )

    return False


# ---------------------------------------------------------------------------
# Quota selection
# ---------------------------------------------------------------------------

def _candidate_module_key(candidate: Any) -> str:
    module = _candidate_module(candidate)

    if module and module != "unknown":
        return module

    return f"unknown:{_candidate_id(candidate)}"


def _ordered_candidates(candidates: list[Any]) -> list[Any]:
    """
    Deterministic candidate ordering.

    Higher-scoring candidates come first, with stable module/id
    tie-breaking.
    """
    return sorted(
        candidates,
        key=lambda candidate: (
            -_candidate_score(candidate),
            _candidate_module(candidate),
            _candidate_id(candidate),
        ),
    )

def _verification_accepted(result: Any) -> bool:
    return _verification_passed(result)


def _history_regression_node_ids(candidate: Any) -> tuple[str, ...]:
    """
    Derive precise pytest node IDs from the task-local regression tests.

    HistoryChange stores regression tests as minimal source snapshots
    (path + content), rather than as pytest node IDs. Parse those snapshots
    here so verification runs only the regression test(s) extracted from
    the fixing commit instead of an entire test file.
    """
    regression_tests = getattr(candidate, "regression_tests", ()) or ()
    node_ids: set[str] = set()

    for regression_test in regression_tests:
        path = getattr(regression_test, "path", "")
        content = getattr(regression_test, "content", "")

        if not path or not content:
            continue

        try:
            tree = ast.parse(
                str(content),
                filename=str(path),
            )
        except (SyntaxError, TypeError, ValueError):
            continue

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    normalized_path = str(path).replace("\\", "/")
                    node_ids.add(
                        f"{normalized_path}::{node.name}"
                    )

            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(
                        child,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    ) and child.name.startswith("test_"):
                        normalized_path = str(path).replace("\\", "/")
                        node_ids.add(
                            f"{normalized_path}::{node.name}::{child.name}"
                        )

    return tuple(sorted(node_ids))


def _task_command_for_candidate(
    task_type: str,
    candidate: Any,
    baseline_command: list[str],
    repo_path: Path,
    synthesis: Any = None,
) -> list[str]:
    """
    Select the verification command.

    History uses its precise regression oracle when available.
    Net-new MUST use the generated task-local oracle.
    Excision uses the repository baseline command.
    """
    python_executable = sys.executable

    if task_type == "history":
        node_ids = (
            getattr(synthesis, "verifier_node_ids", ())
            or getattr(candidate, "regression_node_ids", ())
            or _history_regression_node_ids(candidate)
        )

        normalized_node_ids = sorted(
            {
                str(node_id).replace("\\", "/")
                for node_id in node_ids
                if str(node_id).strip()
            }
        )

        if normalized_node_ids:
            return [
                python_executable,
                "-m",
                "pytest",
                "-q",
                *normalized_node_ids,
            ]

        # Do NOT fall back to whole test files. A History task must have a
        # precise regression oracle; otherwise an unrelated already-passing
        # test can make a valid commit look invalid (or vice versa).
        raise TaskSynthesisError(
            "History candidate has no targeted regression test node."
        )

    if task_type == "net_new":
        verifier_dir = getattr(
            synthesis,
            "verifier_dir",
            None,
        )

        if verifier_dir is None:
            raise TaskSynthesisError(
                "Net-new candidate has no verifier directory."
            )

        generated_test = Path(verifier_dir) / "generated_test.py"

        if not generated_test.is_file():
            raise TaskSynthesisError(
                "Net-new candidate has no verifier/generated_test.py oracle."
            )

        return [
            python_executable,
            "-m",
            "pytest",
            "-q",
            "generated_test.py",
        ]

    if task_type == "excision":
        return list(baseline_command)

    raise TaskSynthesisError(
        f"Unsupported task type for verification command: {task_type}"
    )

def _try_candidate(
    task_type: str,
    candidate: Any,
    task_index: int,
    synthesizer: TaskSynthesizer,
    verifier: TaskVerifier,
    baseline_command: list[str],
    repo_path: Path,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """
    Synthesize and verify one candidate.

    Returns:
        (accepted_manifest, failure_record)
    """
    task_name = (
        f"{task_index:02d}-"
        f"{task_type}-"
        f"{_fingerprint(candidate)[:10]}"
    )

    task_root = TASK_ROOT / task_name

    print(
        f"\n  [{task_index}] {task_name}"
    )
    print(
        f"    module: {_candidate_module(candidate)}"
    )

    try:
        if task_type == "history":
            synthesis = synthesizer.synthesize_history(
                candidate,
                task_root,
            )

        elif task_type == "excision":
            synthesis = synthesizer.synthesize_excision(
                candidate,
                task_root,
            )

        elif task_type == "net_new":
            synthesis = synthesizer.synthesize_net_new(
                candidate,
                task_root,
            )

        else:
            raise TaskSynthesisError(
                f"Unknown task type: {task_type}"
            )

        verifier_dir = _materialize_verifier_directory(
            task_root
        )

        task_command = _task_command_for_candidate(
            task_type,
            candidate,
            baseline_command,
            repo_path,
            synthesis=synthesis,
        )

        # History tasks carry a task-local regression-test oracle
        # (materialized by the synthesizer into verifier/); overlay it
        # onto both the input/ and solution/ workspaces so the same
        # fixing-commit regression assertion is what's actually
        # exercised in every stage, instead of whichever stale test
        # file happens to already live in each state.
        oracle_dir = (
            getattr(
                synthesis,
                "verifier_dir",
                None,
            )
            if task_type in {"history", "net_new"}
            else None
        )

        verification = _verify(
            verifier,
            synthesis.input_dir,
            synthesis.solution_dir,
            verifier_dir,
            task_command,
            task_name,
            oracle_dir=oracle_dir,
        )

        # print(
        #     "    VERIFICATION RESULT:",
        #     _jsonable(verification),
        # )

        validation = getattr(
            verification,
            "validation",
            None,
        )

        if validation is not None:
            print(
                "    fail_before:",
                getattr(validation, "fail_before_verified", None),
            )
            print(
                "    pass_after:",
                getattr(validation, "pass_after_verified", None),
            )
            print(
                "    deterministic:",
                getattr(validation, "deterministic_verified", None),
            )
            print(
                "    validation_passed:",
                getattr(validation, "validation_passed", None),
            )
            print(
                "    reasons:",
                getattr(validation, "reasons", None),
            )

        _write_verification_evidence(
            task_root,
            verification,
        )

        manifest = _write_task_manifest(
            task_root,
            task_type,
            candidate,
            synthesis,
            verification,
            task_command,
        )

        if not _verification_accepted(verification):
            print(
                "    REJECTED: verifier state machine did not pass."
            )
            print(
                f"    DEBUG ARTIFACTS RETAINED: {task_root}"
            )

            return None, {
                "task": task_name,
                "type": task_type,
                "candidate": _candidate_id(candidate),
                "reason": "verification_failed",
                "path": task_root.as_posix(),
            }

        _write_golden_solution(
            task_root,
            task_type,
            candidate,
            verification,
            repo_path,
        )

        print("    ACCEPTED")

        return manifest, None

    except Exception as exc:
        print(
            f"    REJECTED: {type(exc).__name__}: {exc}"
        )
        print(
            f"    DEBUG ARTIFACTS RETAINED: {task_root}"
        )

        return None, {
            "task": task_name,
            "type": task_type,
            "candidate": _candidate_id(candidate),
            "reason": str(exc),
            "path": task_root.as_posix(),
        }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    import sys

    repo_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

    print("=" * 70)
    print("PIPELINE 3 - TASK GENERATION")
    print("=" * 70)

    # --------------------------------------------------------------
    # 1. Repository discovery
    # --------------------------------------------------------------

    print("\n[1/7] Discovering repository...")

    context = discover_repo(
        str(repo_path)
    )

    print(
        f"  ecosystem: {context.ecosystem}"
    )
    print(
        f"  frameworks: "
        f"{getattr(context, 'test_frameworks', [])}"
    )

    # --------------------------------------------------------------
    # 2. Knowledge graph
    # --------------------------------------------------------------

    print("\n[2/7] Loading knowledge graph...")

    graph = _load_graph(
        repo_path / GRAPH_PATH
    )

    nodes = graph["nodes"]
    edges = graph["edges"]

    modules = [
        node
        for node in nodes
        if node.get("type") == "module"
    ]

    symbols = [
        node
        for node in nodes
        if node.get("type") in {
            "class",
            "function",
            "method",
            "symbol",
        }
    ]

    relationships = edges

    print(
        f"  modules: {len(modules)}"
    )
    print(
        f"  symbols: {len(symbols)}"
    )
    print(
        f"  relationships: "
        f"{len(relationships)}"
    )

    # --------------------------------------------------------------
    # 3. Baseline
    # --------------------------------------------------------------

    print("\n[3/7] Running baseline...")

    from pipeline.dependencies import (
        discover_dependencies,
    )
    from pipeline.baseline import (
        run_baseline,
    )

    dependencies = discover_dependencies(
        str(repo_path),
        context,
    )

    baseline = run_baseline(
        str(repo_path),
        context,
        dependencies,
    )

    print(
        f"  passed: "
        f"{baseline.overall_passed}"
    )
    print(
        f"  deterministic: "
        f"{baseline.deterministic}"
    )

    if (
        not baseline.overall_passed
        or baseline.deterministic is not True
    ):
        print(
            "\nERROR: refusing to generate benchmark tasks because "
            "the repository baseline is not a successful deterministic "
            "state."
        )
        return 2

    baseline_command = _baseline_command(
        baseline
    )

    print(
        "  command:",
        baseline_command,
    )

    # --------------------------------------------------------------
    # 4. Mine candidates
    # --------------------------------------------------------------

    print("\n[4/7] Mining task candidates...")

    history_candidates = _mine_history(
        repo_path
    )

    excision_candidates = _mine_excision(
        repo_path,
        graph,
        context,
    )

    net_new_candidates = _make_net_new_candidates(
        graph
    )
    print(
        "  graph node types:",
        sorted(
            {
                node.get("type")
                for node in graph["nodes"]
            }
        ),
    )

    print(
        "  candidate modules:",
        len(
            [
                node
                for node in graph["nodes"]
                if node.get("type") == "module"
            ]
        ),
    )

    print(
        f"  history candidates: "
        f"{len(history_candidates)}"
    )
    print(
        f"  excision candidates: "
        f"{len(excision_candidates)}"
    )
    print(
        f"  net-new candidates: "
        f"{len(net_new_candidates)}"
    )


    # --------------------------------------------------------------
    # 5. Prepare task workspace
    # --------------------------------------------------------------

    print("\n[5/7] Preparing task workspace...")

    if TASK_ROOT.exists():
        print(
            f"  removing previous generated workspace: "
            f"{TASK_ROOT}"
        )
        shutil.rmtree(
            TASK_ROOT
        )

    TASK_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    synthesizer = TaskSynthesizer(
        repo_path
    )

    verifier = TaskVerifier(
        config=VerifierConfig(
            deterministic_stdout=False,
            deterministic_stderr=False,
            deterministic_return_code=True,
        )
    )

    accepted_manifests = []
    failed_tasks = []

    # --------------------------------------------------------------
    # 6. Synthesize + verify
    # --------------------------------------------------------------

        # --------------------------------------------------------------
    # 6. Synthesize + verify
    # --------------------------------------------------------------

    print("\n[6/7] Synthesizing and verifying tasks...")

    # History candidates are mined from Git metadata, so qualify them against
    # the actual parent/fixing-commit states before spending final task slots.
    # This filters out commits whose extracted regression test already passes
    # on the parent and lets the main loop continue until it finds four real
    # History tasks.
    qualified_history_candidates: list[Any] = []

    for candidate in _ordered_candidates(history_candidates):
        if _qualify_history_candidate(
            candidate=candidate,
            synthesizer=synthesizer,
            verifier=verifier,
            repo_path=repo_path,
        ):
            qualified_history_candidates.append(candidate)

    candidate_pools = {
        "history": qualified_history_candidates,
        "excision": _ordered_candidates(excision_candidates),
        "net_new": _ordered_candidates(net_new_candidates),
    }

    quotas = {
        "history": HISTORY_QUOTA,
        "excision": EXCISION_QUOTA,
        "net_new": NET_NEW_QUOTA,
    }

    accepted_manifests: list[dict[str, Any]] = []
    failed_tasks: list[dict[str, Any]] = []

    accepted_by_type = {
        "history": 0,
        "excision": 0,
        "net_new": 0,
    }

    accepted_modules: set[str] = set()

    task_index = 1

    for task_type in (
        "history",
        "excision",
        "net_new",
    ):
        candidates = list(candidate_pools[task_type])
        quota = quotas[task_type]

        print(
            f"\n  Searching for {quota} valid "
            f"{task_type} task(s)..."
        )

        # Candidates rejected by synthesis/verification are not retried.
        # Diversity is only a preference during selection; it is NOT a
        # reason to discard an otherwise valid benchmark task.
        used_candidate_ids: set[str] = set()

        while accepted_by_type[task_type] < quota:
            remaining = [
                candidate
                for candidate in candidates
                if _candidate_id(candidate)
                not in used_candidate_ids
            ]

            if not remaining:
                break

            # Dynamically prefer a candidate from a module that is not yet
            # represented. This preference is recalculated after every
            # candidate so newly accepted modules immediately affect ordering.
            remaining = sorted(
                remaining,
                key=lambda candidate: (
                    0
                    if (
                        _candidate_module(candidate) != "unknown"
                        and _candidate_module(candidate)
                        not in accepted_modules
                    )
                    else 1,
                    -_candidate_score(candidate),
                    _candidate_module(candidate),
                    _candidate_id(candidate),
                ),
            )

            candidate = remaining[0]
            used_candidate_ids.add(_candidate_id(candidate))

            manifest, failure = _try_candidate(
                task_type=task_type,
                candidate=candidate,
                task_index=task_index,
                synthesizer=synthesizer,
                verifier=verifier,
                baseline_command=baseline_command,
                repo_path=repo_path,
            )

            if failure is not None:
                failed_tasks.append(failure)

            elif manifest is not None:
                accepted_manifests.append(manifest)
                accepted_by_type[task_type] += 1

                module = manifest.get(
                    "module",
                    "unknown",
                )

                if module != "unknown":
                    accepted_modules.add(module)

                task_index += 1

            print()
            print("Current task generation progress:")
            print("| Type | Accepted | Required |")
            print("|---|---:|---:|")
            print(
                f"| History-derived | "
                f"{accepted_by_type['history']} | 4 |"
            )
            print(
                f"| Excision (red → green) | "
                f"{accepted_by_type['excision']} | 4 |"
            )
            print(
                f"| Net-new feature | "
                f"{accepted_by_type['net_new']} | 2 |"
            )
            print(
                f"| Modules | "
                f"{len(accepted_modules)} | {MIN_MODULES} |"
            )

        if accepted_by_type[task_type] < quota:
            print(
                f"\nERROR: unable to find enough valid "
                f"{task_type} candidates."
            )

            print(
                f"  required: {quota}"
            )

            print(
                f"  accepted: "
                f"{accepted_by_type[task_type]}"
            )

            return 4

    # Remove rejected/debug task directories.
    # Match accepted tasks using the task_id stored inside task.json,
    # not the directory name. The directory name also contains the
    # task sequence/type prefix and therefore is not necessarily equal
    # to task_id.
    accepted_task_ids = {
        manifest["task_id"]
        for manifest in accepted_manifests
    }

    for task_dir in TASK_ROOT.iterdir():
        if not task_dir.is_dir():
            continue

        task_json = task_dir / "task.json"

        # Anything without a task.json is not an accepted task artifact.
        if not task_json.is_file():
            print(
                f"  removing rejected task artifact: "
                f"{task_dir.name}"
            )
            shutil.rmtree(task_dir)
            continue

        try:
            task_manifest = json.loads(
                task_json.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            print(
                f"  removing invalid task artifact: "
                f"{task_dir.name}"
            )
            shutil.rmtree(task_dir)
            continue

        task_id = task_manifest.get("task_id")

        if task_id not in accepted_task_ids:
            print(
                f"  removing rejected task artifact: "
                f"{task_dir.name}"
            )
            shutil.rmtree(task_dir)


    # --------------------------------------------------------------
    # 7. Final quota validation + tasks.json
    # --------------------------------------------------------------

    print("\n[7/7] Compiling final task index...")

    accepted_manifests.sort(
        key=lambda item: item["task_id"]
    )

    counts = {
        "history": 0,
        "excision": 0,
        "net_new": 0,
    }

    modules = set()

    for manifest in accepted_manifests:
        task_type = manifest[
            "type"
        ]

        counts[task_type] = (
            counts.get(
                task_type,
                0,
            )
            + 1
        )

        modules.add(
            manifest[
                "module"
            ]
        )

    print(
        f"  accepted: {len(accepted_manifests)}"
    )
    print(
        f"  history: {counts['history']}"
    )
    print(
        f"  excision: {counts['excision']}"
    )
    print(
        f"  net-new: {counts['net_new']}"
    )
    print(
        f"  modules: {len(modules)}"
    )

    # Never emit a partially valid benchmark as the final result.
    if len(accepted_manifests) != TOTAL_TASKS:
        print(
            "\nERROR: final benchmark contains "
            f"{len(accepted_manifests)} accepted tasks; "
            f"exactly {TOTAL_TASKS} are required."
        )
        return 4

    if counts["history"] != HISTORY_QUOTA:
        print(
            "\nERROR: History quota not satisfied."
        )
        return 5

    if counts["excision"] != EXCISION_QUOTA:
        print(
            "\nERROR: Excision quota not satisfied."
        )
        return 6

    if counts["net_new"] != NET_NEW_QUOTA:
        print(
            "\nERROR: Net-new quota not satisfied."
        )
        return 7

    if len(modules) < MIN_MODULES:
        print(
            "\nERROR: module diversity requirement not satisfied: "
            f"{len(modules)} < {MIN_MODULES}."
        )
        return 8

    final_manifest = {
        "schema_version": "1.0",
        "total_tasks": len(
            accepted_manifests
        ),
        "distribution": counts,
        "module_count": len(
            modules
        ),
        "modules": sorted(
            modules
        ),
        "tasks": [
            {
                "id": task["id"],
                "title": task["title"],
                "type": task["type"],
                "module": task["module"],
                "difficulty": task["difficulty"],
                "provenance": task["provenance"],
                "verifier_command": task["verifier_command"],
                "validation_status": task["validation_status"],
                "path": (
                    "tasks/"
                    + next(
                        directory.name
                        for directory in TASK_ROOT.iterdir()
                        if (
                            directory.is_dir()
                            and (directory / "task.json").is_file()
                            and json.loads(
                                (directory / "task.json").read_text(
                                    encoding="utf-8"
                                )
                            ).get("id") == task["id"]
                        )
                    )
                ),
            }
            for task in accepted_manifests
        ],
        "failed_candidates": failed_tasks,
    }

    _write_json(
        TASKS_JSON,
        final_manifest,
    )

    # Final task-schema safety gate. Never report completion unless every
    # accepted task contains the complete mandatory artifact layout.
    for accepted_task in accepted_manifests:
        task_id = accepted_task["task_id"]
        matching_dirs = [
            directory
            for directory in TASK_ROOT.iterdir()
            if (
                directory.is_dir()
                and (directory / "task.json").is_file()
                and json.loads(
                    (directory / "task.json").read_text(
                        encoding="utf-8"
                    )
                ).get("task_id") == task_id
            )
        ]

        if len(matching_dirs) != 1:
            raise RuntimeError(
                f"Missing artifact in {TASK_ROOT / task_id}"
            )

        task_dir = matching_dirs[0]

        required_files = (
            "task.json",
            "goldenSolution.md",
        )
        required_dirs = (
            "input",
            "solution",
            "verifier",
            "evidence",
        )

        if any(
            not (task_dir / filename).is_file()
            for filename in required_files
        ) or any(
            not (task_dir / dirname).is_dir()
            for dirname in required_dirs
        ):
            raise RuntimeError(
                f"Missing artifact in {task_dir}"
            )

    print(
        "\n"
        + "=" * 70
    )
    print(
        "PIPELINE 3 COMPLETE"
    )
    print(
        "=" * 70
    )

    print(
        f"  tasks: {TASKS_JSON}"
    )
    print(
        f"  task directory: {TASK_ROOT}/"
    )
    print(
        f"  validated tasks: "
        f"{len(accepted_manifests)}"
    )
    print(
        f"  modules covered: "
        f"{len(modules)}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )