from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


SCHEMA_VERSION = "1.0"

TOTAL_TASKS_REQUIRED = 10
MINIMUM_MODULES_REQUIRED = 4


class TaskType(str, Enum):
    HISTORY = "history"
    EXCISION = "excision"
    NET_NEW = "net_new"


class TaskValidationError(ValueError):
    """Raised when a task or task batch violates the Pipeline 3 contract."""


@dataclass(frozen=True)
class TaskProvenance:
    task_type: str
    graph_ids: tuple[str, ...] = ()
    git_commit: Optional[str] = None
    git_commits: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "graph_ids": list(self.graph_ids),
            "git_commit": self.git_commit,
            "git_commits": list(self.git_commits),
            "evidence_sources": list(self.evidence_sources),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskProvenance":
        return cls(
            task_type=data["task_type"],
            graph_ids=tuple(data.get("graph_ids", [])),
            git_commit=data.get("git_commit"),
            git_commits=tuple(data.get("git_commits", [])),
            evidence_sources=tuple(data.get("evidence_sources", [])),
            rationale=data.get("rationale", ""),
        )


@dataclass(frozen=True)
class VerificationRun:
    command: tuple[str, ...]
    return_code: int

    passed: bool

    tests_total: Optional[int] = None
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None

    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "return_code": self.return_code,
            "passed": self.passed,
            "tests_total": self.tests_total,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VerificationRun":
        return cls(
            command=tuple(data.get("command", [])),
            return_code=data["return_code"],
            passed=data["passed"],
            tests_total=data.get("tests_total"),
            tests_passed=data.get("tests_passed"),
            tests_failed=data.get("tests_failed"),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass(frozen=True)
class TaskValidation:
    fail_before: VerificationRun
    pass_after: VerificationRun
    deterministic_runs: tuple[VerificationRun, ...]

    fail_before_verified: bool
    pass_after_verified: bool
    deterministic_verified: bool

    validation_passed: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fail_before": self.fail_before.to_dict(),
            "pass_after": self.pass_after.to_dict(),
            "deterministic_runs": [
                run.to_dict()
                for run in self.deterministic_runs
            ],
            "fail_before_verified": self.fail_before_verified,
            "pass_after_verified": self.pass_after_verified,
            "deterministic_verified": self.deterministic_verified,
            "validation_passed": self.validation_passed,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskValidation":
        return cls(
            fail_before=VerificationRun.from_dict(
                data["fail_before"]
            ),
            pass_after=VerificationRun.from_dict(
                data["pass_after"]
            ),
            deterministic_runs=tuple(
                VerificationRun.from_dict(run)
                for run in data.get("deterministic_runs", [])
            ),
            fail_before_verified=data["fail_before_verified"],
            pass_after_verified=data["pass_after_verified"],
            deterministic_verified=data["deterministic_verified"],
            validation_passed=data["validation_passed"],
            reasons=tuple(data.get("reasons", [])),
        )


@dataclass(frozen=True)
class TaskVerificationResult:
    task_id: str
    validation: TaskValidation

    accepted: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "validation": self.validation.to_dict(),
            "accepted": self.accepted,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "TaskVerificationResult":
        return cls(
            task_id=data["task_id"],
            validation=TaskValidation.from_dict(
                data["validation"]
            ),
            accepted=data["accepted"],
            warnings=tuple(data.get("warnings", [])),
        )


@dataclass(frozen=True)
class TaskManifest:
    schema_version: str

    task_id: str
    title: str
    description: str

    task_type: str
    difficulty: str

    source_module: str
    source_symbol: Optional[str]
    source_file: str
    source_lines: tuple[int, ...]

    behavioral_contract: str

    input_files: tuple[str, ...]
    solution_files: tuple[str, ...]
    verifier_files: tuple[str, ...]
    evidence_files: tuple[str, ...]

    baseline_command: tuple[str, ...]
    verifier_command: tuple[str, ...]

    fail_before_required: bool
    pass_after_required: bool
    deterministic_required: bool

    validation_status: str

    provenance: TaskProvenance

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise TaskValidationError(
                f"Unsupported task schema version: "
                f"{self.schema_version!r}"
            )

        if not self.task_id:
            raise TaskValidationError(
                "task_id must not be empty"
            )

        if self.task_type not in {
            task_type.value
            for task_type in TaskType
        }:
            raise TaskValidationError(
                f"Unsupported task type: {self.task_type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "task_type": self.task_type,
            "difficulty": self.difficulty,
            "source_module": self.source_module,
            "source_symbol": self.source_symbol,
            "source_file": self.source_file,
            "source_lines": list(self.source_lines),
            "behavioral_contract": self.behavioral_contract,
            "input_files": list(self.input_files),
            "solution_files": list(self.solution_files),
            "verifier_files": list(self.verifier_files),
            "evidence_files": list(self.evidence_files),
            "baseline_command": list(self.baseline_command),
            "verifier_command": list(self.verifier_command),
            "fail_before_required": self.fail_before_required,
            "pass_after_required": self.pass_after_required,
            "deterministic_required": self.deterministic_required,
            "validation_status": self.validation_status,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskManifest":
        return cls(
            schema_version=data["schema_version"],
            task_id=data["task_id"],
            title=data["title"],
            description=data["description"],
            task_type=data["task_type"],
            difficulty=data["difficulty"],
            source_module=data["source_module"],
            source_symbol=data.get("source_symbol"),
            source_file=data["source_file"],
            source_lines=tuple(data.get("source_lines", [])),
            behavioral_contract=data["behavioral_contract"],
            input_files=tuple(data.get("input_files", [])),
            solution_files=tuple(data.get("solution_files", [])),
            verifier_files=tuple(data.get("verifier_files", [])),
            evidence_files=tuple(data.get("evidence_files", [])),
            baseline_command=tuple(data.get("baseline_command", [])),
            verifier_command=tuple(data.get("verifier_command", [])),
            fail_before_required=data["fail_before_required"],
            pass_after_required=data["pass_after_required"],
            deterministic_required=data["deterministic_required"],
            validation_status=data["validation_status"],
            provenance=TaskProvenance.from_dict(
                data["provenance"]
            ),
        )


@dataclass(frozen=True)
class TaskIndexEntry:
    task_id: str
    title: str
    task_type: str

    source_module: str
    source_symbol: Optional[str]

    difficulty: str
    validation_status: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "task_type": self.task_type,
            "source_module": self.source_module,
            "source_symbol": self.source_symbol,
            "difficulty": self.difficulty,
            "validation_status": self.validation_status,
            "path": self.path.replace("\\", "/"),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "TaskIndexEntry":
        return cls(
            task_id=data["task_id"],
            title=data["title"],
            task_type=data["task_type"],
            source_module=data["source_module"],
            source_symbol=data.get("source_symbol"),
            difficulty=data["difficulty"],
            validation_status=data["validation_status"],
            path=data["path"].replace("\\", "/"),
        )


@dataclass(frozen=True)
class TaskIndex:
    schema_version: str
    repository: str
    generated_from: str

    task_count: int
    module_count: int

    task_types: dict[str, int]

    tasks: tuple[TaskIndexEntry, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise TaskValidationError(
                f"Unsupported task index schema version: "
                f"{self.schema_version!r}"
            )

        if self.task_count != TOTAL_TASKS_REQUIRED:
            raise TaskValidationError(
                f"Pipeline 3 requires exactly "
                f"{TOTAL_TASKS_REQUIRED} tasks; "
                f"received {self.task_count}."
            )

        if len(self.tasks) != self.task_count:
            raise TaskValidationError(
                "task_count does not match the number "
                "of task entries."
            )

        modules = {
            task.source_module
            for task in self.tasks
        }

        if len(modules) < MINIMUM_MODULES_REQUIRED:
            raise TaskValidationError(
                f"Pipeline 3 requires tasks spanning at least "
                f"{MINIMUM_MODULES_REQUIRED} modules; "
                f"received {len(modules)}."
            )

        task_ids = [
            task.task_id
            for task in self.tasks
        ]

        if len(task_ids) != len(set(task_ids)):
            raise TaskValidationError(
                "Task IDs must be unique."
            )

        expected_counts: dict[str, int] = {}

        for task in self.tasks:
            expected_counts[task.task_type] = (
                expected_counts.get(task.task_type, 0) + 1
            )

        if dict(self.task_types) != expected_counts:
            raise TaskValidationError(
                "task_types does not match the actual "
                "task distribution."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "generated_from": self.generated_from,
            "task_count": self.task_count,
            "module_count": self.module_count,
            "task_types": dict(
                sorted(self.task_types.items())
            ),
            "tasks": [
                task.to_dict()
                for task in self.tasks
            ],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "TaskIndex":
        tasks = tuple(
            TaskIndexEntry.from_dict(task)
            for task in data.get("tasks", [])
        )

        return cls(
            schema_version=data["schema_version"],
            repository=data["repository"],
            generated_from=data["generated_from"],
            task_count=data["task_count"],
            module_count=data["module_count"],
            task_types=dict(data.get("task_types", {})),
            tasks=tasks,
        )


def canonical_json(data: Any) -> str:
    """
    Produce deterministic JSON for task artifacts.
    """
    return (
        json.dumps(
            data,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ": "),
        )
        + "\n"
    )


def task_fingerprint(
    *,
    task_type: str,
    source_module: str,
    source_symbol: Optional[str],
    behavioral_contract: str,
    provenance: TaskProvenance,
) -> str:
    """
    Generate a stable task identifier.

    Generation order, timestamps, filesystem locations, and runtime
    information are deliberately excluded.
    """

    payload = {
        "task_type": task_type,
        "source_module": source_module,
        "source_symbol": source_symbol,
        "behavioral_contract": behavioral_contract,
        "provenance": provenance.to_dict(),
    }

    canonical = canonical_json(payload).encode("utf-8")

    digest = hashlib.sha256(canonical).hexdigest()

    return f"task-{digest[:12]}"


def build_task_index(
    *,
    repository: str,
    generated_from: str,
    tasks: list[TaskIndexEntry] | tuple[TaskIndexEntry, ...],
) -> TaskIndex:
    """
    Construct the final Pipeline 3 task index.

    This function is intentionally the enforcement point for the
    final batch-level rubric constraints.
    """

    ordered_tasks = tuple(
        sorted(
            tasks,
            key=lambda task: task.task_id,
        )
    )

    task_types: dict[str, int] = {}

    for task in ordered_tasks:
        task_types[task.task_type] = (
            task_types.get(task.task_type, 0) + 1
        )

    modules = {
        task.source_module
        for task in ordered_tasks
    }

    return TaskIndex(
        schema_version=SCHEMA_VERSION,
        repository=repository,
        generated_from=generated_from,
        task_count=len(ordered_tasks),
        module_count=len(modules),
        task_types=task_types,
        tasks=ordered_tasks,
    )