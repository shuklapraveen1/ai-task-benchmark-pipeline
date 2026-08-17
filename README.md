# AI Task Benchmark & Evaluation Infrastructure

A three-stage pipeline that takes an arbitrary Python repository, establishes a reproducible baseline, extracts a machine-readable knowledge layer, and mines/synthesizes/validates SWE-bench-style benchmark tasks from it.

See [REPORT.md](./REPORT.md) for the full write-up: design decisions, trade-offs, baseline reconnaissance findings, and known gaps.

## Overview

| Stage | Purpose | Entry point |
|---|---|---|
| Pipeline 1 — Repository Hygiene | Discover ecosystem/framework, pin dependencies, establish a deterministic test baseline, propose containerization | `pipeline/run_baseline.py`, `pipeline/run_hygiene.py`, `pipeline/run_containerization.py` |
| Pipeline 2 — Knowledge Layer | Parse the repository into a machine-readable OKF knowledge layer (modules, symbols, relationships, call graph) | `python -m pipeline.run_knowledge .` |
| Pipeline 3 — Task Generation | Mine, synthesize, and verify benchmark tasks from the knowledge layer and repo history | `python -m pipeline.run_tasks .` |

All repository modification and validation happens in isolated temporary workspaces. The original target repository is never intentionally modified.

## Requirements

- Python 3.10+
- `pip install -e .` (or your preferred install of this pipeline's dependencies)
- A target repository checkout to run the pipeline against (kept outside this submission repository)

## Quickstart

Run Pipeline 1 hygiene/baseline steps against your target repository as needed, then:

```bash
# From the target repository checkout

# Pipeline 2 — build the knowledge layer
python -m pipeline.run_knowledge .

# Pipeline 3 — generate and validate benchmark tasks (after Pipeline 2)
python -m pipeline.run_tasks .
```

This produces `.okf/` (knowledge layer) and `tasks.json` + `tasks/` (validated benchmark tasks) inside the target repository checkout.

**Do not** run `pipeline.run_knowledge` or `pipeline.run_tasks` against this submission repository itself — they operate on a target repository you supply.

### Running the pipeline's own tests

From this submission repository:

```powershell
python -m pytest -q `
    pipeline/test_task_history.py `
    pipeline/test_task_synthesis.py `
    pipeline/test_task_verifier.py
```

Expected result: `37 passed`.

## Repository layout

```text
ai-task-benchmark-pipeline/
├── pipeline/
│   ├── Pipeline 1 source
│   ├── Pipeline 2 source
│   ├── Pipeline 3 source
│   └── pipeline tests
│
├── output/
│   ├── repo/            # sample target repository snapshot (cleaned)
│   ├── baseline/
│   ├── .okf/             # sample knowledge layer output
│   └── repo_graph.json
│
├── tasks/                # 10 validated benchmark tasks
├── tasks.json
│
├── transcripts/
│   └── agent_workflow.md
│
├── REPORT.md
├── README.md
└── .gitignore
```

## Sample run results

Generated against the sample repository (`glom`):

- **Knowledge layer**: 1,154 modules, 23,316 symbols, 5,921 import relationships, 483 inheritance relationships, 113,703 call relationships, 0 parser diagnostics.
- **Tasks**: 10 total — 4 history-derived, 4 excision, 2 net-new — spanning 8 distinct modules.
- **Baseline**: 266 tests passed, 2 skipped, deterministic, 98% production-package coverage.

## Known limitation

The sample repository does not pass the full container acceptance bar due to an execution-order-sensitive global-state issue in `glom/tutorial.py` (see REPORT.md §8). This is documented rather than hidden or worked around by modifying the upstream repository.

## Design principles

- **Isolation**: all transformations and validation run in temporary workspaces; the source repository is never touched.
- **Generality over hardcoding**: test-runner discovery (e.g. `tox` vs. `pytest`) is dynamic, since the pipeline must also work against a held-out repository not seen during development.
- **Authoritative repo config**: a repository's own test/coverage configuration is trusted over broad, naive framework flags.
- **Evidence over appearance**: raw execution evidence is preserved even when it's inconvenient (e.g. a failing containerized test, a stale coverage report), rather than being suppressed to make acceptance criteria look green.

See [REPORT.md](./REPORT.md) for full details, trade-offs, and next steps.
