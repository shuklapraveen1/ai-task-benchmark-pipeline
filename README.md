# AI Task Benchmark & Evaluation Infrastructure

A three-stage pipeline that takes an arbitrary Python repository, establishes a reproducible baseline, extracts a machine-readable knowledge layer, and mines/synthesizes/validates SWE-bench-style benchmark tasks from it.

See [REPORT.md](./REPORT.md) for the full write-up: design decisions, trade-offs, baseline reconnaissance findings, held-out generalization testing, and known gaps.

## Overview

| Stage | Purpose | Entry point |
|---|---|---|
| Pipeline 1 — Repository Hygiene | Discover ecosystem/framework, pin dependencies, establish a deterministic test baseline, propose and validate containerization | `pipeline/run_baseline.py`, `pipeline/run_hygiene.py`, `pipeline/run_containerization.py` |
| Pipeline 2 — Knowledge Layer | Parse the repository into a machine-readable OKF knowledge layer (modules, symbols, relationships, call graph) | `python -m pipeline.run_knowledge .` |
| Pipeline 3 — Task Generation | Mine, synthesize, and verify benchmark tasks from the knowledge layer and repo history | `python -m pipeline.run_tasks .` |

All repository modification and validation happens in isolated temporary workspaces. The original target repository is never intentionally modified.

## Requirements

- Python 3.10+
- Docker (for the containerization stage)
- `pip install -e .` (or your preferred install of this pipeline's dependencies)
- A target repository checkout to run the pipeline against (kept outside this submission repository)

## Quickstart

Run Pipeline 1 hygiene/baseline/containerization steps against your target repository as needed, then:

```bash
# From the target repository checkout

# Pipeline 2 — build the knowledge layer
python -m pipeline.run_knowledge .

# Pipeline 3 — generate and validate benchmark tasks (after Pipeline 2)
python -m pipeline.run_tasks .
```

This produces `.okf/` (knowledge layer) and `tasks.json` + `tasks/` (validated benchmark tasks) inside the target repository checkout.

To run just the containerization flow against a target repository:

```bash
python -m pipeline.run_containerization
```

run from within the target repository checkout.

**Do not** run `pipeline.run_knowledge` or `pipeline.run_tasks` against this submission repository itself — they operate on a target repository you supply. The same separation matters for containerization: see "Known limitations" below for a build-context hygiene gap found while validating this, and keep this submission's own `pipeline/` directory out of any target repository's working tree before running `run_containerization` against it.

### Running the pipeline's own tests

From this submission repository:

```powershell
python -m pytest -q pipeline\test_knowledge.py
python -m pytest -q `
    pipeline\test_discover.py `
    pipeline\test_dependencies.py `
    pipeline\test_baseline.py `
    pipeline\test_hygiene_proposal.py `
    pipeline\test_hygiene_mutation.py `
    pipeline\test_containerization.py `
    pipeline\test_container_execution.py `
    pipeline\test_container_proposal.py `
    pipeline\test_lint_format.py `
    pipeline\test_test_generation.py
python -m pytest -q `
    pipeline/test_task_history.py `
    pipeline/test_task_synthesis.py `
    pipeline/test_task_verifier.py
```

Expected results: `31 passed`, `84 passed`, `37 passed` — 152 passed in total.

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
- **Tasks**: 10 total — 4 history-derived, 4 excision, 2 net-new — spanning 8 distinct modules. Difficulty mix: 5 easy, 2 medium, 3 hard.
- **Baseline**: 379 tests passed, deterministic across repeat runs. (Initial manual reconnaissance recorded 266 passed / 2 skipped against an earlier commit of `glom`; the later containerization run in REPORT.md §8.1 reflects upstream repository drift, not a change in pipeline behavior — see REPORT.md §7.)
- **Containerization**: **passes, confirmed twice.** `docker build` succeeds and the container test run passes, reproduced twice in a row with identical results (379/379, matching the host baseline exactly, no regression detected, `accepted: True` both times). This satisfies the assignment's §3 acceptance bar for the sample repository — see REPORT.md §8.1 for the run detail, and §8.3 for a build-context hygiene issue found while reviewing that same run's logs.

### Held-out generalization test (`toolz`)

To validate that the pipeline generalizes beyond the sample repository, the full containerization flow was also run end to end against `toolz` (github.com/pytoolz/toolz), a repository not used during development. After fixing three real, repo-agnostic bugs surfaced by this run (see REPORT.md §8.2), the pipeline achieved a fully passing result — and this result was **reproduced twice in a row with identical output**, satisfying the assignment's literal determinism bar for this repository:

```text
Run 1 — docker build: succeeded | docker run: 186/186 passed | accepted: True
Run 2 — docker build: succeeded | docker run: 186/186 passed | accepted: True
```

Both runs matched the host baseline exactly, with no regression detected on either run. This is not the assignment's actual held-out repository, but it is strong, reproduced evidence that the pipeline's containerization path generalizes — see REPORT.md §8.2 and §11. With `glom`'s own containerization now also passing twice in a row (above), both repositories the pipeline has been run against currently meet the §3 acceptance bar; only the assignment's actual held-out repository remains unverified.

## Known limitations

- **Net-new task substance is weak.** Both accepted net-new tasks are technically valid — verified fail-before/pass-after/deterministic — but insert a trivial identity function into a module with no real relationship to it, rather than testing a genuine missing capability. Disclosed explicitly rather than left for a reviewer to find — see REPORT.md §3 and §11.
- **Container build context does not exclude this pipeline's own source directory.** While reviewing a passing `glom` containerization run, the container's captured test output showed pytest collection warnings originating from this pipeline's own `pipeline/test_generation.py`, not from `glom` — evidence that this repository's own source was physically present in the build context and got swept into the image by `COPY . .`. It caused no observed failure in the runs recorded here, but the exclusion discipline already applied to `output/repo/` (§9) is not yet applied to the live container build context. See REPORT.md §8.3 and §11.
- **Dependency discovery does not yet parse `pyproject.toml`** (PEP 621 or Poetry), which affects dependency pinning for any modern `pyproject.toml`-only repository, including `toolz`.
- **Generated container test dependencies (`pytest`, `coverage`, `PyYAML`) are still installed unpinned** in the Dockerfile, rather than pinned to the exact versions resolved in the trusted host baseline. This did not prevent `glom` or `toolz` from passing in the runs recorded here, but it remains a latent source of host/container drift for other repositories or future runs — see REPORT.md §8.1 and §11.
- **No bug-injection evidence exists** for Pipeline 1's generated unit tests, an explicit grading criterion in the assignment.

Full detail, root causes, and next steps for all of these are in [REPORT.md](./REPORT.md), Sections 8 and 11.

## Design principles

- **Isolation**: all transformations and validation run in temporary workspaces; the source repository is never touched. A gap in how far that isolation currently reaches — this pipeline's own source leaking into a container build context — was found and is disclosed rather than hidden; see REPORT.md §8.3.
- **Generality over hardcoding**: test-runner discovery (e.g. `tox` vs. bare `pytest`) is dynamic, and this was specifically stress-tested against a second, previously-unseen repository (`toolz`) — the fixes that came out of that testing are what got both `glom` and `toolz` to a passing, twice-reproduced containerization result, rather than being left as an untested design claim.
- **Authoritative repo config**: a repository's own test/coverage configuration is trusted over broad, naive framework flags — and gaps in following this principle (the original package-directory heuristic) were found and are documented, not hidden.
- **Evidence over appearance**: raw execution evidence is preserved even when it's inconvenient (a stale coverage report, a technically-valid but low-substance task, a build-context leak spotted only by reading the container's own logs after a run had already passed), rather than being suppressed to make acceptance criteria look green.

See [REPORT.md](./REPORT.md) for full details, trade-offs, and next steps.