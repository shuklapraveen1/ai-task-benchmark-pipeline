# AI Agent Workflow / Session Notes

## Purpose

This document records the key AI-assisted development workflow used to build and validate the AI Task Benchmark & Evaluation Infrastructure take-home assignment.

## Repository Hygiene and Pipeline Design

Key work performed with AI assistance:

- Inspected the target repository and identified missing engineering hygiene.
- Designed the three-stage pipeline:
  1. Repository hygiene and baseline verification.
  2. Repository knowledge graph / OKF generation.
  3. Benchmark task mining, synthesis, and verification.
- Used isolated temporary workspaces for repository transformations and task validation.
- Added automated tests for the pipeline implementation.

## Pipeline 2

AI-assisted debugging identified an issue where pipeline-internal directories such as `.pipeline_history_probe` were being parsed as repository source.

The knowledge extractor was updated so internal/generated directories are excluded.

Validation:

- `31 passed` for `pipeline/test_knowledge.py`
- Knowledge graph generated successfully.
- Parse diagnostics: `0`
- Required `.okf` artifacts generated.

## Pipeline 3

AI-assisted debugging focused on:

- Portable verifier commands.
- Avoiding machine-specific interpreter paths.
- Mapping logical task IDs to physical task directories.
- Keeping execution evidence separate from portable task artifacts.
- Removing temporary workspace paths from task manifests and golden solutions.

The final task generation produced:

- 4 history-derived tasks
- 4 excision tasks
- 2 net-new tasks
- 10 total validated tasks
- 8 modules covered

Pipeline 3 tests:

`37 passed`

Final task index:

- 10 tasks
- 4 history
- 4 excision
- 2 net_new
- all validation statuses passed

A portability audit was also performed. Temporary execution paths were excluded from historical verification evidence while portable task artifacts were checked for stale environment-specific paths.

Final stale-path audit:

`0`

## Important Debugging Decision

A task directory initially could not be located directly from the logical task ID because the task index uses IDs such as:

`excision:1e2a3f11cec3d243`

while physical directories use names such as:

`08-excision-1e2a3f11ce`

The submission audit was therefore changed to build a logical-task-ID to physical-directory mapping from each task's `task.json`.

## Containerization

Containerization was attempted and validated through the pipeline's container execution flow.

The repository has a pre-existing behavioral test involving a global ID counter whose behavior was environment/order dependent. This prevented the container validation from reaching the required clean deterministic acceptance state.

Rather than modifying the upstream repository solely to force the container check to pass, the limitation was retained and will be documented honestly in `REPORT.md`.

## Engineering Principle

AI-generated changes were treated as proposals rather than trusted automatically. Changes were followed by targeted tests, full relevant pipeline tests, generated-artifact audits, and portability checks.

