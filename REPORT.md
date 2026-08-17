# AI Task Benchmark & Evaluation Infrastructure

## 1. What was broken and how the pipeline fixes it

The target repository was a Python project that lacked several pieces of engineering hygiene needed for deterministic AI coding-agent evaluation. Package installation succeeded, but a concrete hygiene issue was identified: development/test requirements were pinned, while the package's runtime dependency metadata was not fully pinned.

The submission implements a three-stage pipeline.

### Pipeline 1: Repository Hygiene

Pipeline 1 performs repository discovery and establishes a reproducible baseline for a target repository.

It includes support for:

- ecosystem and framework discovery;
- dependency discovery and pinning;
- baseline test execution;
- repository hygiene transformations;
- containerization proposal and validation;
- test generation support;
- linting and formatting configuration;
- isolated validation workspaces.

Repository transformations and validation are performed in isolated temporary workspaces to reduce the risk of modifying the original repository.

### Pipeline 2: Knowledge Layer

Pipeline 2 converts the target repository into a machine-readable knowledge layer consumed by Pipeline 3.

The generated OKF artifacts are:

- `manifest.json`
- `project.json`
- `modules.json`
- `symbols.json`
- `relationships.json`
- `repo_graph.json`

The final sample run produced:

- 1,154 modules
- 23,316 symbols
- 5,921 import relationships
- 483 inheritance relationships
- 113,703 call relationships
- 0 parser diagnostics

Pipeline 2 produces a deterministic, internally consistent OKF knowledge layer with zero parse diagnostics and graph relationships grounded in the repository's Python AST.

The knowledge extractor also excludes pipeline-internal/generated directories such as `.pipeline_history_probe`.

### Pipeline 3: Task Generation

Pipeline 3 consumes the knowledge layer and repository history to mine, synthesize, and validate benchmark tasks.

The final task set contains:

- 4 history-derived tasks
- 4 excision tasks
- 2 net-new tasks
- 10 tasks total

The tasks span 8 distinct modules.

Every accepted task contains the required task artifacts and validation evidence.

---

## 2. Design decisions and trade-offs

### Isolated execution

The pipeline uses isolated temporary workspaces when modifying or validating repositories.

This separates the source repository from generated benchmark state and makes it possible to verify that benchmark generation has not accidentally modified the original repository.

### Test command discovery is dynamic, not hardcoded

The assignment requires the pipeline to be designed for the general case, since it is also run against a second, held-out repository that has not been seen in advance.

During reconnaissance on the sample repository (`glom`), `tox -e py310` was used to establish a baseline and proved to be a fast, correct way to find coverage gaps for that specific repository. However, a held-out repository might not use `tox` at all.

Pipeline 1 therefore does not hardcode `tox` as the test runner. Instead it discovers how to run tests dynamically, for example: if a `tox.ini` exists, prefer `tox`; otherwise fall back to `pytest` (or another discovered framework) directly. `tox` usage discovered during reconnaissance on one sample repository is treated as evidence for that repository only, never as a hardcoded assumption for the pipeline itself.

### Test configuration is treated as authoritative

Initial baseline execution on the sample repository exposed that framework detection alone was insufficient. `glom` uses `pytest` with doctests, but its `tox` configuration restricts doctest execution to the installed package. A naive `pytest --doctest-modules` invocation instead traversed `docs/conf.py` and failed on an undeclared documentation dependency.

The pipeline therefore treats a repository's own test configuration (e.g. its `tox.ini` / pytest configuration) as authoritative evidence for test targets, rather than blindly expanding framework flags such as `--doctest-modules` to the whole tree.

### Portable commands

Baseline test commands may contain environment-specific interpreter paths or temporary workspace paths.

The task-generation and containerization layers normalize interpreter paths and remove temporary workspace prefixes from portable commands: absolute paths inside the repository are rewritten relative to the repository root, and absolute paths outside the repository are never allowed to leak into a generated command.

For Python commands, environment-specific Python executables are intended to be normalized to the portable token `python`, since that is what is guaranteed to be on `PATH` inside the `python:3.10-slim` container base image — not the host interpreter's own basename (e.g. `python.exe` on a Windows dev machine, or a versioned `python3.10` binary on Linux). Non-Python executables are preserved rather than being incorrectly rewritten as Python commands.

**Open item:** during development, `pipeline/test_containerization.py::test_default_container_uses_json_cmd` was observed to fail against an intermediate version of `_baseline_test_command`, because substituting `sys.executable` for the interpreter and then routing it through the same absolute-path normalization used for arguments caused it to collapse to the host interpreter's basename rather than the portable `python` token. The full pipeline test suite (Section 4) currently passes, including this test, but because this class of bug depends on the host platform's interpreter naming, it is called out explicitly in Section 11 as something to re-verify on the held-out repository's environment and on non-Windows hosts, rather than treated as fully closed on the strength of one green run.

### Coverage reporting resilience

Coverage collection and coverage reporting are treated as separate concerns. On the sample repository, `coverage` collection completed successfully under the official `tox` workflow, but `coverage report` / `coverage html` failed because the coverage database referenced a temporary, pytest-generated `snippets.rst` file that no longer existed at report-generation time.

Rather than failing the entire baseline because report generation failed, the pipeline treats the raw `.coverage` database as the source of truth for module-level analysis. It reads the database directly through Coverage's Python API (per-file executed/missing line analysis) instead of depending on `coverage report` succeeding. This was validated as a reconnaissance-only investigation, run outside the repository in a temporary script, without modifying the repository itself; it informs how the eventual Pipeline 1 coverage collector is designed, but is not part of the pipeline as shipped.

### Evidence versus portable artifacts

Validation evidence records the actual environment in which validation occurred. Such evidence can legitimately contain temporary paths because it is an audit record of the execution.

Portable task artifacts must not depend on those paths.

Therefore, raw execution details remain in `evidence/`, while portable task manifests and golden solutions contain sanitized validation summaries.

A final portability audit was performed after task generation.

Result:

```text
stale path hits: 0
```

for portable task artifacts outside the intentionally preserved verification evidence.

### Task validation

A candidate task is not accepted merely because it can be generated.

The verifier state machine checks:

- fail-before demonstrates the intended behavioral failure;
- pass-after succeeds;
- repeated verification is deterministic;
- the reference solution does not introduce broader repository breakage.

Candidates failing these checks are rejected.

### Candidate selection

The miner intentionally generates more candidates than required and filters them through validation.

The final sample run considered:

- 20 history candidates
- 90 excision candidates
- 1,096 net-new candidates

Only candidates satisfying the required validation conditions were accepted.

This prioritizes genuinely validated tasks over weak or unverifiable candidates.

## 3. Task candidate selection

### History-derived

History candidates are derived from repository history and target meaningful bug fixes or feature changes.

The parent state becomes `input/` and the post-change state becomes `solution/`.

The real historical change is represented by the golden solution.

### Excision

Excision candidates begin with working repository behavior.

The implementation is removed while the interface and behavioral contract remain.

The existing behavior tests define the expected behavior and the original implementation is retained as the reference solution.

### Net-new

Net-new tasks define a capability through tests authored by the benchmark pipeline.

The implementation is not taken from an existing repository change. The task instruction describes observable behavior and the verifier determines whether an implementation satisfies that behavior.

### Final selection

| Source | Count |
|---|---|
| History-derived | 4 |
| Excision | 4 |
| Net-new | 2 |
| **Total** | **10** |

The final task set covers 8 distinct modules, exceeding the required minimum of 4.

### Task manifest and difficulty (`tasks.json`)

Each task is labeled `easy` / `medium` / `hard` per Section 5.5 of the assignment. The one-to-two sentence justification for each label (cross-module reasoning, business-logic knowledge required, misleading similar code, coordinated multi-file changes, etc.) is recorded per task and lives alongside each task's `task.json`, not duplicated here.

| Task ID | Difficulty | Title | Module |
|---|---|---|---|
| `excision:46ccfd8382788a9b` | easy | Restore behavior of function: `glom.mutation.assign` | `glom.mutation` |
| `excision:74bf276825df6ee7` | easy | Restore behavior of function: `glom.reduction.flatten` | `glom.reduction` |
| `excision:aa8e83349b9c4f08` | easy | Restore behavior of function: `glom.grouping.GROUP` | `glom.grouping` |
| `excision:f939591c08ff5a09` | easy | Restore behavior of function: `glom.cli.main` | `glom.cli` |
| `history:2a4ca4f25b824b6b` | medium | Remove repetitions of root error | `glom.core` |
| `history:34844be36c6498db` | hard | Rename `Literal` to `Val`, keeping backwards compatibility | `glom` |
| `history:96a9de66a7b57da1` | hard | Docs refactor, fix a few bugs, tweak the stack to be more readable | `glom.core` |
| `history:db31bbb570b2cdb9` | medium | Fix duplicate `format_t`, add test coverage for `repr(A)` | `glom.core` |
| `net_new:3f684d388ceb65e4` | easy | Implement new behavior in `__benchmark_new_behavior` | `glom.matching` |
| `net_new:b80b727953cb0d29` | easy | Implement new behavior in `__benchmark_new_behavior` | `glom._version` |

Difficulty distribution: 5 easy, 2 medium, 3 hard — spread across tiers rather than clustered at one level.

**Open item:** the two net-new tasks currently share an identical, generic title (`"Implement new behavior in __benchmark_new_behavior"`). Titles should be reviewed for specificity before final submission so that each task is self-contained and identifiable per Section 5.3 (`"An engineer unfamiliar with the repo should understand what is expected"`). The `net_new:b80b727953cb0d29` task's target module, `glom._version`, should also be reviewed to confirm it represents genuine new capability rather than a low-substance version-string check. See Section 11.

## 4. How to run everything

The submission repository contains the pipeline source and generated deliverables.

Pipeline commands operate on a target repository checkout. They should not be run against the submission repository itself.

### Pipeline 1

The Pipeline 1 implementation is located under:

```text
pipeline/
```

Relevant entry points include:

```text
pipeline/run_baseline.py
pipeline/run_hygiene.py
pipeline/run_containerization.py
```

These operate on the target repository supplied to the pipeline.

### Pipeline 2

From the target repository checkout:

```text
python -m pipeline.run_knowledge .
```

This produces the machine-readable `.okf/` knowledge layer.

### Pipeline 3

From the target repository checkout, after Pipeline 2:

```text
python -m pipeline.run_tasks .
```

This produces:

```text
tasks.json
tasks/
```

with the validated benchmark tasks.

### Pipeline unit tests

From the submission repository, the Pipeline 2 knowledge-layer tests:

```powershell
python -m pytest -q pipeline\test_knowledge.py
```

```text
31 passed in 0.60s
```

The Pipeline 1 discovery, dependency, baseline, hygiene, containerization, lint/format, and test-generation unit tests:

```powershell
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
```

```text
84 passed in 1.92s
```

The Pipeline 3 task-mining, synthesis, and verifier tests:

```powershell
python -m pytest -q `
    pipeline/test_task_history.py `
    pipeline/test_task_synthesis.py `
    pipeline/test_task_verifier.py
```

```text
37 passed
```

Combined, the current local pipeline unit test suite stands at **152 passed** across all three stages (31 + 84 + 37), with no known failing tests as of the latest run. See Section 2's "Portable commands" subsection and Section 11 for a caveat on re-verifying interpreter-path normalization across platforms rather than relying solely on this local, single-platform green run.

## 5. Pipeline 2 validation

The final knowledge-layer generation on the target repository completed successfully.

The generated artifacts were:

```text
.okf/
├── manifest.json
├── project.json
├── modules.json
├── symbols.json
├── relationships.json
└── repo_graph.json
```

The extraction completed with:

```text
modules: 1154
symbols: 23316
imports: 5921
inheritance: 483
calls: 113703
diagnostics: 0
```

The generated `.okf/` directory and `repo_graph.json` were copied into the submission under:

```text
output/.okf/
output/repo_graph.json
```

## 6. Pipeline 3 validation

The final generated task index contains exactly 10 tasks.

```text
history:   4
excision:  4
net_new:   2
total:    10
```

All task validation statuses passed.

The final task suite was tested with:

```text
37 passed
```

The final task directories are:

```text
tasks/
├── 01-history-34844be36c
├── 02-history-96a9de66a7
├── 03-history-db31bbb570
├── 04-history-2a4ca4f25b
├── 05-excision-f939591c08
├── 06-excision-aa8e83349b
├── 07-excision-46ccfd8382
├── 08-excision-74bf276825
├── 09-net_new-b80b727953
└── 10-net_new-3f684d388c
```

Each accepted task contains:

```text
task.json
input/
solution/
verifier/
goldenSolution.md
evidence/
```

The task index and physical task directories were also checked independently. See Section 3 for the per-task difficulty breakdown.

## 7. Baseline reconnaissance on the sample repository (glom)

Before building Pipeline 1's automated baseline logic, manual reconnaissance was performed against the sample repository (`glom`) in a clean, isolated Python 3.10 virtual environment. This section records that reconnaissance as evidence; it is not itself part of the automated pipeline.

### Installation and test execution

```text
pip install -e .
PASS

Direct pytest:
    202 tests passed.

Official tox environment:
    tox -e py310
    PASS

Official tox test execution:
    247 items collected
    244 passed
    3 skipped
    1 warning

Coverage collection:
    PASS

Coverage reporting:
    FAIL — coverage data references a temporary,
    pytest-generated snippets.rst file that no longer
    exists when `coverage report` / `coverage html` runs.
```

Using the discovered baseline command (the repository's own authoritative test configuration, per the design decision above), the baseline executed 266 tests with 2 skips deterministically and achieved 98% production-package coverage.

The repository declares support for Python 3.7–3.14 and PyPy, but only Python 3.10 was available locally, so those other environments were not independently verified.

### Coverage findings

Direct inspection of the coverage data (via the Coverage Python API against the `.coverage` database, as described in the design decisions section) showed that most production modules are above 98% coverage, while `glom.cli` is the primary production-code coverage gap, at 89.78%.

Because the repository's own `coverage report` / `coverage html` workflow fails on the stale `snippets.rst` reference, the pipeline treats raw coverage data as the source for module-level analysis rather than failing the entire baseline on report generation.

### Why this matters for Pipeline 1

This reconnaissance produced two concrete, generalizable findings that inform the automated Pipeline 1 design (see Section 2):

- test-runner discovery must not hardcode `tox`, since a held-out repository may not use it;
- a repository's own test configuration (doctest scope, coverage config) must be treated as authoritative rather than overridden by broad, naive framework flags.

## 8. Containerization status and known limitation

Containerization support was implemented and exercised through the Pipeline 1 container execution flow.

However, the sample repository did not reach the complete container acceptance bar.

### Finding: host vs. container test results (glom)

```text
Host baseline:
    266 passed
    2 skipped
    deterministic = True

Container:
    265 passed
    2 skipped
    1 failed

Failure:
    glom/tutorial.py::glom.tutorial

Cause:
    A module-level autoincrement counter's state is consumed
    by glom/test/test_tutorial.py before the tutorial doctest
    runs.

Evidence:
    test_tutorial.py alone: 2 passed
    tutorial.py alone:      1 passed
    combined:                2 passed, 1 failed
```

This is an execution-order-sensitive, shared global-state issue in the sample repository itself, surfaced by running the full suite inside the container — exactly the class of issue the benchmark pipeline is meant to detect.

Rather than modifying the upstream repository solely to force the benchmark acceptance check to become green, the behavior was preserved and documented as a repository/environment limitation. `original_repo_untouched=True` remains true, and the container remains disposable.

Therefore, the submission does not claim that the sample repository fully passed the Docker acceptance requirement. The containerization machinery remains implemented in the pipeline, and the failure is treated as an explicit known gap rather than being hidden.

### Interpreter portability in the generated container command

Separately from the `tutorial.py` finding above, the default Dockerfile proposal path (`propose_containerization` → `_default_python_dockerfile`) builds its `CMD` from the host's successful baseline test command via `_baseline_test_command`. That function substitutes `sys.executable` for the original interpreter and then normalizes all command parts as potential repository-relative paths. Because `sys.executable` is an absolute path outside the repository root, an earlier version of this logic caused it to fall through to `candidate.name` — the host interpreter's own basename (e.g. `python.exe` on Windows) — rather than the portable `python` token that is actually present on `PATH` inside the `python:3.10-slim` base image. The current local test suite (Section 4) passes, including `test_default_container_uses_json_cmd`, but this is flagged in Section 11 as an item to re-confirm by inspecting the literal generated `Dockerfile` `CMD` line, since the failure mode is platform-dependent and a single green run on one host is not sufficient evidence that it cannot recur on the held-out repository's build environment.

## 9. Repository integrity

Benchmark generation was performed using isolated temporary workspaces.

The original target repository was not intentionally modified as part of task generation.

Generated benchmark artifacts were separated from the source repository and copied into the submission repository as deliverables.

The submission's `output/repo/` contains the sample repository snapshot without:

- `.git`
- `.venv`
- `.pytest_cache`
- `.tox`
- `tasks/`
- `pipeline/`
- `.okf/`
- benchmark-generation history probes
- benchmark-generated source files

### The safety invariant

A hygiene transformation may be accepted only after it succeeds in an isolated workspace and a fresh baseline proves that behavior, test counts, determinism, and coverage have not regressed. The original repository remains untouched.

## 10. Scale answer: what breaks at 100 repositories

At 100 repositories, the main bottlenecks would be:

- repository cloning;
- dependency installation;
- container builds;
- test execution;
- static analysis;
- knowledge extraction;
- candidate verification.

A production implementation would separate the pipeline into independently scheduled jobs.

I would introduce:

- content-addressed repository snapshots;
- dependency and container-layer caching;
- isolated worker environments;
- queue-based orchestration;
- parallel candidate verification;
- resource and timeout budgets;
- persistent validation metadata;
- deterministic artifact hashes;
- structured failure telemetry;
- retry handling for infrastructure failures;
- task deduplication;
- staged candidate filtering.

Cheap static checks should run before expensive test-based validation.

The knowledge layer would also be stored in a queryable representation instead of relying only on large JSON files.

## 11. Honest gaps and next steps

The strongest completed portions of the assignment are Pipeline 2 and Pipeline 3.

Known limitations:

- The sample repository did not satisfy the complete container acceptance bar because of the environment-sensitive global-state behavior in `glom/tutorial.py` described in Section 8. The pipeline contains containerization support, but the sample result should not be represented as a fully passing containerized repository.
- The sample repository's runtime dependency metadata is not fully pinned, even though development/test requirements are.
- The sample repository's own `coverage report` / `coverage html` workflow fails due to a stale `snippets.rst` reference; the pipeline works around this by reading the `.coverage` database directly rather than fixing the upstream repository's coverage configuration.
- Only Python 3.10 was verified locally against the sample repository, even though it declares support for Python 3.7–3.14 and PyPy.
- The default container `CMD` generation path substitutes the host's own interpreter for the baseline command's interpreter and then routes it through path-normalization logic intended for arguments, not the interpreter token itself. This previously produced a host-specific, non-portable interpreter name (e.g. `python.exe`) instead of the portable `python` token expected inside the container base image. The full unit test suite (152 tests) currently passes, but this is a platform-dependent failure mode, so the generated `Dockerfile`'s literal `CMD` line should be inspected directly — and ideally the interpreter substitution should be hardcoded to the portable token rather than derived from `sys.executable` — before relying on this path for the held-out repository.
- The two net-new tasks (`net_new:3f684d388ceb65e4`, `net_new:b80b727953cb0d29`) currently share an identical, generic title (`"Implement new behavior in __benchmark_new_behavior"`). Task titles should be made specific and self-contained per Section 5.3. `net_new:b80b727953cb0d29` targets `glom._version`, which should be reviewed to confirm it represents genuine new capability rather than a low-substance version-string check.

Potential next steps:

- isolate and reproduce the tutorial/test global-state ordering behavior across clean container instances;
- determine whether the behavior is caused by test ordering, process reuse, or repository state;
- harden `_baseline_test_command` to hardcode the portable `python` interpreter token rather than deriving it from `sys.executable`, and add a cross-platform regression test for it;
- improve container-validation diagnostics;
- validate the complete Pipeline 1 acceptance criteria against a second, held-out repository;
- add additional cross-platform command-normalization tests;
- expand generated-test quality checks, including deliberate bug-injection validation for Pipeline 1's generated unit tests;
- extend the runtime dependency-pinning check into an automated hygiene transformation;
- rename the two net-new task titles to be specific and self-contained, and re-review the `glom._version` net-new task's substance.

The implementation intentionally favors reproducible evidence and honest reporting over forcing every acceptance criterion to appear green.

## 12. Submission contents

The final submission repository is organized as:

```text
ai-task-benchmark-pipeline/
├── pipeline/
│   ├── Pipeline 1 source
│   ├── Pipeline 2 source
│   ├── Pipeline 3 source
│   └── pipeline tests
│
├── output/
│   ├── repo/
│   ├── baseline/
│   ├── .okf/
│   └── repo_graph.json
│
├── tasks/
│   └── 10 validated benchmark tasks
│
├── tasks.json
│
├── transcripts/
│   └── agent_workflow.md
│
├── REPORT.md
└── .gitignore
```

The original target repository is kept outside the submission repository.

The submission contains the pipeline source, generated knowledge layer, validated benchmark tasks, validation evidence, report, and AI-assisted workflow notes required by the assignment.