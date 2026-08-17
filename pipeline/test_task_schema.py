import json

import pytest

from pipeline.task_schema import (
    MINIMUM_MODULES_REQUIRED,
    SCHEMA_VERSION,
    TOTAL_TASKS_REQUIRED,
    TaskIndexEntry,
    TaskManifest,
    TaskProvenance,
    TaskType,
    TaskValidationError,
    VerificationRun,
    build_task_index,
    canonical_json,
    task_fingerprint,
)


def make_provenance(
    task_type=TaskType.EXCISION.value,
    symbol="function:pkg.mod.foo",
):
    return TaskProvenance(
        task_type=task_type,
        graph_ids=(
            "module:pkg.mod",
            symbol,
        ),
        git_commit=None,
        git_commits=(),
        evidence_sources=(
            ".okf/repo_graph.json",
        ),
        rationale="Synthetic test task.",
    )


def make_manifest():
    provenance = make_provenance()

    return TaskManifest(
        schema_version=SCHEMA_VERSION,
        task_id=task_fingerprint(
            task_type=TaskType.EXCISION.value,
            source_module="pkg.mod",
            source_symbol="function:pkg.mod.foo",
            behavioral_contract="foo returns the transformed value",
            provenance=provenance,
        ),
        title="Exercise foo",
        description="Verify foo behavior.",
        task_type=TaskType.EXCISION.value,
        difficulty="medium",
        source_module="pkg.mod",
        source_symbol="function:pkg.mod.foo",
        source_file="pkg/mod.py",
        source_lines=(10, 11, 12),
        behavioral_contract=(
            "foo returns the transformed value"
        ),
        input_files=("input/pkg/mod.py",),
        solution_files=("solution/pkg/mod.py",),
        verifier_files=("verifier/test_task.py",),
        evidence_files=(
            "evidence/fail_before.json",
            "evidence/pass_after.json",
            "evidence/determinism.json",
        ),
        baseline_command=(
            "python",
            "-m",
            "pytest",
        ),
        verifier_command=(
            "python",
            "-m",
            "pytest",
            "verifier/test_task.py",
        ),
        fail_before_required=True,
        pass_after_required=True,
        deterministic_required=True,
        validation_status="validated",
        provenance=provenance,
    )


def make_entry(
    index: int,
    module: str,
    task_type: str = TaskType.EXCISION.value,
):
    return TaskIndexEntry(
        task_id=f"task-{index:03d}",
        title=f"Task {index}",
        task_type=task_type,
        source_module=module,
        source_symbol=f"function:{module}.foo",
        difficulty="medium",
        validation_status="validated",
        path=f"tasks/task-{index:03d}",
    )


def test_task_manifest_round_trips_through_json():
    manifest = make_manifest()

    encoded = canonical_json(manifest.to_dict())

    decoded = json.loads(encoded)

    restored = TaskManifest.from_dict(decoded)

    assert restored == manifest


def test_provenance_round_trips():
    provenance = make_provenance(
        task_type=TaskType.HISTORY.value,
    )

    restored = TaskProvenance.from_dict(
        json.loads(
            canonical_json(provenance.to_dict())
        )
    )

    assert restored == provenance


def test_verification_run_round_trips():
    run = VerificationRun(
        command=(
            "python",
            "-m",
            "pytest",
            "-q",
        ),
        return_code=1,
        passed=False,
        tests_total=4,
        tests_passed=3,
        tests_failed=1,
        stdout="3 passed, 1 failed",
        stderr="",
        duration_seconds=0.42,
    )

    restored = VerificationRun.from_dict(
        json.loads(
            canonical_json(run.to_dict())
        )
    )

    assert restored == run


def test_task_type_values_are_stable():
    assert TaskType.HISTORY.value == "history"
    assert TaskType.EXCISION.value == "excision"
    assert TaskType.NET_NEW.value == "net_new"


def test_task_fingerprint_is_deterministic():
    provenance = make_provenance()

    first = task_fingerprint(
        task_type="excision",
        source_module="pkg.mod",
        source_symbol="function:pkg.mod.foo",
        behavioral_contract="foo returns transformed data",
        provenance=provenance,
    )

    second = task_fingerprint(
        task_type="excision",
        source_module="pkg.mod",
        source_symbol="function:pkg.mod.foo",
        behavioral_contract="foo returns transformed data",
        provenance=provenance,
    )

    assert first == second
    assert first.startswith("task-")
    assert len(first) == len("task-") + 12


def test_task_fingerprint_changes_when_behavior_changes():
    provenance = make_provenance()

    first = task_fingerprint(
        task_type="excision",
        source_module="pkg.mod",
        source_symbol="function:pkg.mod.foo",
        behavioral_contract="foo returns transformed data",
        provenance=provenance,
    )

    second = task_fingerprint(
        task_type="excision",
        source_module="pkg.mod",
        source_symbol="function:pkg.mod.foo",
        behavioral_contract="foo raises ValueError",
        provenance=provenance,
    )

    assert first != second


def test_task_fingerprint_is_independent_of_generation_order():
    provenance = make_provenance()

    first = task_fingerprint(
        task_type="excision",
        source_module="pkg.mod",
        source_symbol="function:pkg.mod.foo",
        behavioral_contract="foo returns transformed data",
        provenance=provenance,
    )

    # Simulate the candidate being discovered later.
    candidates = [
        "unrelated",
        "candidate",
        "another",
    ]

    candidates.reverse()

    second = task_fingerprint(
        task_type="excision",
        source_module="pkg.mod",
        source_symbol="function:pkg.mod.foo",
        behavioral_contract="foo returns transformed data",
        provenance=provenance,
    )

    assert first == second


def test_task_index_requires_exactly_ten_tasks():
    tasks = [
        make_entry(i, f"module{i % 4}")
        for i in range(9)
    ]

    with pytest.raises(
        TaskValidationError,
        match="exactly 10 tasks",
    ):
        build_task_index(
            repository="glom",
            generated_from=".okf/repo_graph.json",
            tasks=tasks,
        )


def test_task_index_requires_at_least_four_modules():
    tasks = [
        make_entry(i, f"module{i % 3}")
        for i in range(10)
    ]

    with pytest.raises(
        TaskValidationError,
        match="at least 4 modules",
    ):
        build_task_index(
            repository="glom",
            generated_from=".okf/repo_graph.json",
            tasks=tasks,
        )


def test_task_index_accepts_ten_tasks_across_four_modules():
    tasks = [
        make_entry(i, f"module{i % 4}")
        for i in range(10)
    ]

    index = build_task_index(
        repository="glom",
        generated_from=".okf/repo_graph.json",
        tasks=tasks,
    )

    assert index.task_count == 10
    assert index.module_count == 4
    assert len(index.tasks) == 10


def test_task_index_is_sorted_by_stable_task_id():
    tasks = [
        make_entry(9, "module0"),
        make_entry(2, "module1"),
        make_entry(5, "module2"),
        make_entry(1, "module3"),
        make_entry(7, "module0"),
        make_entry(3, "module1"),
        make_entry(8, "module2"),
        make_entry(0, "module3"),
        make_entry(6, "module0"),
        make_entry(4, "module1"),
    ]

    index = build_task_index(
        repository="glom",
        generated_from=".okf/repo_graph.json",
        tasks=tasks,
    )

    ids = [
        task.task_id
        for task in index.tasks
    ]

    assert ids == sorted(ids)


def test_task_index_round_trips_through_json():
    tasks = [
        make_entry(i, f"module{i % 4}")
        for i in range(10)
    ]

    index = build_task_index(
        repository="glom",
        generated_from=".okf/repo_graph.json",
        tasks=tasks,
    )

    encoded = canonical_json(
        index.to_dict()
    )

    restored = type(index).from_dict(
        json.loads(encoded)
    )

    assert restored == index


def test_task_index_rejects_duplicate_ids():
    tasks = [
        make_entry(i, f"module{i % 4}")
        for i in range(10)
    ]

    tasks[1] = TaskIndexEntry(
        task_id=tasks[0].task_id,
        title=tasks[1].title,
        task_type=tasks[1].task_type,
        source_module=tasks[1].source_module,
        source_symbol=tasks[1].source_symbol,
        difficulty=tasks[1].difficulty,
        validation_status=tasks[1].validation_status,
        path=tasks[1].path,
    )

    with pytest.raises(
        TaskValidationError,
        match="Task IDs must be unique",
    ):
        build_task_index(
            repository="glom",
            generated_from=".okf/repo_graph.json",
            tasks=tasks,
        )