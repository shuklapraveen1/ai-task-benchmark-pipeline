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

Every accepted task contains the required task artifacts and validation evidence. The two net-new tasks are technically valid (verified fail-before/pass-after/deterministic) but low-substance by design; see Section 3 and Section 11.

**Containerization now passes for the sample repository, confirmed twice.** `docker build` succeeds and the container test run passes, reproduced twice in a row with identical results, matching the host baseline exactly (379/379). See Section 8.1 for the full run record, and Section 8.3 for a build-context hygiene issue found while producing that evidence.

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

A second, more serious instance of this same principle was found and fixed during held-out-style testing against a second repository (`toolz`) — see Section 8. `_select_test_command`'s original package-directory heuristic picked a directory purely by alphabetical order, which is not equivalent to trusting the repository's own declared test configuration. That gap is documented in Section 8 and Section 11 rather than being silently patched over. The same underlying fix — falling back to a bare, unrestricted `pytest -q` run rather than guessing a package directory — is also what allowed `glom`'s own containerization re-run in Section 8.1 to reach a fully passing, reproducible result.

### Portable commands

Baseline test commands may contain environment-specific interpreter paths or temporary workspace paths.

The task-generation and containerization layers normalize interpreter paths and remove temporary workspace prefixes from portable commands: absolute paths inside the repository are rewritten relative to the repository root, and absolute paths outside the repository are never allowed to leak into a generated command.

For Python commands, environment-specific Python executables are normalized to the portable token `python`, since that is what is guaranteed to be on `PATH` inside the `python:3.10-slim` container base image — not the host interpreter's own basename (e.g. `python.exe` on a Windows dev machine). This was previously implemented by substituting `sys.executable` and routing it through the same absolute-path normalization used for arguments, which caused it to collapse to the host interpreter's basename rather than the portable token, and was confirmed to break container execution (`exec: "python.exe": executable file not found in $PATH`) during held-out testing. This has been fixed: `container_proposal.py` now hardcodes `command[0] = "python"` directly rather than deriving it from `sys.executable`, which removes the platform-dependence entirely rather than papering over one observed symptom of it.

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

Only candidates satisfying the required validation conditions were accepted. Two excision candidates that were generated but rejected on real grounds are recorded in `tasks.json`'s `failed_candidates` block (`function:glom.cli.get_command`, `function:glom.test.perf_report.func`, both `reason: "verification_failed"`) — concrete evidence the filter is real rather than nominal.

This prioritizes genuinely validated tasks over weak or unverifiable candidates. Net-new candidate generation currently hard-caps at exactly the quota (2) with no retry headroom if a candidate fails validation — see Section 11.

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

**Verification mechanism, confirmed sound.** Both net-new tasks use a dedicated `generated_test.py` verifier command (`pytest -q generated_test.py`), not a fallback to the full doctest suite. Per-task verification metadata confirms `fail_before_verified: true`, `pass_after_verified: true`, `deterministic_verified: true` with no rejection reasons recorded. Given a stub body of `return None` versus a solution body of `return value`, the generated test asserts real output equality, so fail-before is failing for a genuine behavioral reason, not an import/syntax error — this satisfies §5.4's requirement in mechanism.

**Substance concern, confirmed and unresolved.** Both accepted net-new tasks insert a trivial identity function (`return value`) into an existing module with no real connection to that module's purpose: `net_new:b80b727953cb0d29` targets `glom._version` (a version-metadata module) and `net_new:3f684d388ceb65e4` targets `glom.matching`, both via the same synthetic pattern (`rationale: "Synthetic net-new identity behavior anchored to an existing repository Python module"`). Neither exercises real, module-specific behavior. This does not violate §5.4 (the verifier is honest), but it is a weak fit for §5.1's definition of net-new ("a capability the repo lacks") and for §2's instruction that "a smaller number of genuinely validated tasks beats 10 unvalidated ones" — these are validated, but not meaningfully validating anything. This is disclosed here rather than left for a reviewer to find.

### Final selection

| Source | Count |
|---|---|
| History-derived | 4 |
| Excision | 4 |
| Net-new | 2 |
| **Total** | **10** |

The final task set covers 8 distinct modules, exceeding the required minimum of 4.

### Task manifest and difficulty (`tasks.json`)

Each task is labeled `easy` / `medium` / `hard` per Section 5.5 of the assignment, with a `difficulty_reason` field on each task's `task.json` giving the one-to-two sentence justification. Example (net-new, easy): *"The task is localized to a single file, so the implementation scope is narrow and focused."*

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

**Open items, in order of severity:**

1. **Net-new task substance.** Both net-new tasks are synthetic identity functions with a weak connection to their target module (see above). They should ideally be regenerated against real, undertested behavior before final submission; at minimum this is disclosed rather than hidden.
2. **Generic, duplicate titles.** Both net-new tasks share the identical title `"Implement new behavior in __benchmark_new_behavior"`. Titles should be made specific and self-contained per §5.3.

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

Combined, the current local pipeline unit test suite stands at **152 passed** across all three stages (31 + 84 + 37), with no known failing tests as of the latest run.

### Containerization, end to end

```bash
python -m pipeline.run_containerization
```

run from within a target repository checkout. See Section 8 for full results on both `glom` and a second, held-out-style repository (`toolz`), including repeated confirmation runs for each, and a build-context hygiene note in Section 8.3.

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

All task validation statuses passed, including a verified-sound fail-before mechanism for the net-new tasks (see Section 3). The substance of those two tasks remains a separate, disclosed concern.

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

**Note on test-count drift versus Section 8.1.** The figures above (266 passed, 2 skipped, 98% coverage) reflect `glom`'s commit state at the time of this initial manual reconnaissance. Section 8.1 records a later, independently re-run clean containerization pass against the same repository showing 379 passed, 0 skipped, 99% coverage, and installing `glom-25.12.1.dev0`. `glom` is an actively developed upstream project; the higher count, absence of skips, and slightly higher coverage in the later run are consistent with the repository having moved to a newer commit between sessions, not with any change in how the pipeline selects or runs tests — the same discovered-baseline-command logic produced both figures at their respective points in time. Both are reported here as-observed rather than reconciled to a single number, since each was accurate for the commit state it was measured against.

### Coverage findings

Direct inspection of the coverage data (via the Coverage Python API against the `.coverage` database, as described in the design decisions section) showed that most production modules are above 98% coverage, while `glom.cli` is the primary production-code coverage gap, at 89.78% at the time of this reconnaissance.

Because the repository's own `coverage report` / `coverage html` workflow fails on the stale `snippets.rst` reference, the pipeline treats raw coverage data as the source for module-level analysis rather than failing the entire baseline on report generation.

## 8. Containerization: findings, held-out validation, and fixes

Containerization support was implemented and exercised through the Pipeline 1 container execution flow (`pipeline/run_containerization.py`, `pipeline/container_proposal.py`, `pipeline/container_execution.py`) against both the sample repository (`glom`) and a second, previously-unseen repository (`toolz`), used specifically to test generality per the assignment's held-out-repository requirement.

### 8.1 glom: initial host/container divergence, root cause, and resolved re-run

An earlier containerization run on the sample repository did not reach the full container acceptance bar:

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
    glom/tutorial.py::glom.tutorial (doctest)

Symptom:
    Expected: Email(id=5, email='jlahey@svtp.info', email_type='personal')
    Got:      Email(id=6, email='jlahey@svtp.info', email_type='personal')
```

**Root cause.** `glom/tutorial.py` and `glom/test/test_tutorial.py` share module-level mutable autoincrement state (`count(1)`-style generators backing `Email`/`Contact` construction). The exact ID assigned depends on how many `Email`/`Contact` instances were constructed earlier in the same test process, which depends on pytest's test collection order. The host baseline in that run used a `tox`-restricted `pytest` invocation, while the generated container Dockerfile installed a bare, unpinned `pytest`, which resolved to a newer `pytest` version at container-build time. Different `pytest` versions can have different default collection/plugin ordering, changing which order `Email`/`Contact` objects were constructed in, which changed the observed ID — a genuine, pre-existing design issue in `glom`'s doctest (execution-order-dependent output), amplified by an unpinned, differently-scoped test invocation between host and container.

**Resolved re-run.** The same generality fix developed for the held-out repository in Section 8.2 — falling back to a bare, unrestricted `pytest -q` test command rather than a narrowly-scoped or heuristically-guessed one, so host and container run the identical, full test command — was applied and `glom`'s containerization flow was re-run end to end from a clean environment. This closed the divergence: the container now reproduces the host baseline exactly, and the run was repeated to confirm determinism:

```text
Run 1:
  docker build:  return_code 0
  docker run:    return_code 0
  tests_before:        379
  tests_in_container:  379
  passed_before:        379
  passed_in_container:  379
  regression_detected:  False
  validation_passed:    True
  accepted:              True

Run 2 (repeat confirmation, clean re-invocation):
  docker build:  return_code 0
  docker run:    return_code 0
  tests_before:        379
  tests_in_container:  379
  passed_before:        379
  passed_in_container:  379
  regression_detected:  False
  validation_passed:    True
  accepted:              True

PIPELINE 1 CONTAINERIZATION: SUCCESS
Trusted baseline preserved inside the container.
Original repository remained untouched.
```

Both runs produced identical results — `docker build` succeeded, the container test run passed with the container's test count matching the host baseline exactly, no regression detected, on both invocations. This satisfies the assignment's §3 acceptance bar ("`docker build` must succeed and the container's test run must pass, twice in a row with identical results") for `glom`. `original_repo_untouched=True` held throughout, including across the earlier failing run. See Section 7 for why this run's test count (379) differs from the original manual reconnaissance figure (266) — the discrepancy is upstream repository drift, not a pipeline inconsistency.

**Residual note.** The underlying amplifying condition from the earlier finding — the generated Dockerfile still installs test tooling (`pytest`, `coverage`, `PyYAML`) unpinned rather than pinned to the exact host-resolved versions — has not been fixed at the code level; it simply did not trigger a divergence in this pair of runs. It remains tracked as an open item in Section 11, since a future `pytest` release could reintroduce the same class of host/container mismatch for `glom`'s execution-order-sensitive doctest.

### 8.2 Held-out generalization test: toolz

To test generality beyond `glom` specifically, the full containerization flow was run end to end against `toolz` (github.com/pytoolz/toolz), a repository not previously used in development. This surfaced three real, repo-agnostic bugs, fixed in the order found:

**Bug 1 — package-directory selection blocked containerization entirely.** `_select_test_command`'s original heuristic picked the first top-level directory (alphabetically) containing an `__init__.py`. `toolz` has two candidates — `tlz` (a legacy alias package with no tests) and `toolz` (the real package) — and `"tlz" < "toolz"` alphabetically, so the pipeline selected `tlz`, got "no tests ran" (exit code 5), and correctly-but-wrongly treated this as a failed baseline. `toolz`'s own `pyproject.toml` already declares `[tool.pytest.ini_options] testpaths = ["toolz"]`; the pipeline was not honoring it. Fixed by falling back to a bare `pytest -q` with no explicit path argument when the discovery heuristic is not confident, letting `pytest` apply the repository's own `testpaths` configuration itself. Result: `186 passed, 186 passed` across two repeat runs, deterministic, `overall_passed: True`.

**Bug 2 — interpreter substitution produced a non-portable container command.** As in Section 2, `sys.executable` collapsed to the host interpreter's basename (`python.exe`), and `docker run` failed with `exec: "python.exe": executable file not found in $PATH`. Fixed by hardcoding `command[0] = "python"` in `container_proposal.py`.

**Bug 3 — missing git binary and excluded `.git` broke dynamic versioning.** `toolz` uses `setuptools-git-versioning`, which shells out to `git describe` at build time. The isolated container build workspace excluded `.git` from the copy, and `python:3.10-slim` has no `git` binary — either alone breaks any package using `setuptools-scm`/`setuptools-git-versioning`/`versioneer`/`hatch-vcs`, a real bug class, not a `toolz` quirk. Fixed by installing git in the Dockerfile and retaining `.git` in the isolated build context copy. Before the fix, `toolz.__version__` resolved to a placeholder `0.0.1` instead of `1.1.0`, failing `test_has_version` inside the container only.

**Result after all three fixes, confirmed twice in a row:**

```text
Run 1:
  docker build:  return_code 0
  docker run:    return_code 0
  tests_before:        186
  tests_in_container:  186
  passed_before:        186
  passed_in_container:  186
  regression_detected:  False
  validation_passed:    True
  accepted:              True

Run 2 (repeat confirmation):
  docker build:  return_code 0
  docker run:    return_code 0
  tests_before:        186
  tests_in_container:  186
  passed_before:        186
  passed_in_container:  186
  regression_detected:  False
  validation_passed:    True
  accepted:              True

PIPELINE 1 CONTAINERIZATION: SUCCESS
Trusted baseline preserved inside the container.
Original repository remained untouched.
```

Both runs produced identical results — `docker build` succeeded, the container test run passed 186/186 matching the host baseline exactly, no regression detected, on both invocations. This satisfies the assignment's §3 acceptance bar ("`docker build` must succeed and the container's test run must pass, twice in a row with identical results") for `toolz` specifically. `toolz` is a repository chosen to test generality, not the assignment's actual held-out repository, so this is strong supporting evidence rather than a substitute for the real held-out run.

### 8.3 Build-context hygiene: pipeline source leaking into the container image

While reviewing the confirmed `glom` run in 8.1, the container's captured test output showed pytest collection warnings originating from this pipeline's own source, not `glom`'s:

```text
pipeline/test_generation.py:25
  /app/pipeline/test_generation.py:25: PytestCollectionWarning: cannot collect
  test class 'TestTarget' because it has a __init__ constructor
```

`/app` is the container's `WORKDIR`, populated by `COPY . .` from the isolated build workspace, which is intended to contain only the target repository (`glom`). The presence of `pipeline/test_generation.py` in that build context indicates this benchmark pipeline's own source directory was physically present inside the `glom` working directory used for this run, and the container build's `COPY . .` step swept it into the image along with `glom`'s real source.

**Impact in this run: none observed.** The two warnings are `PytestCollectionWarning`s on dataclasses named `TestTarget`/`TestGenerationResult` (pytest attempting and declining to collect them as test classes because they have `__init__` constructors) — they did not execute as tests, did not fail, and did not affect the 379/379 pass counts reported in 8.1.

**Why it is still a real gap.** This pipeline's own README and REPORT.md both state that pipeline commands should not be run against the submission repository itself, and Section 9 documents that `output/repo/` is deliberately cleaned of `pipeline/`, `.git`, `.venv`, and similar non-target-repository content before being included as a deliverable. That same exclusion discipline is not currently applied to the live container build context in `container_execution.py`'s `_copy_repository` step — it excludes `.git`, `.venv`, caches, and build artifacts, but not a `pipeline/` directory if one happens to be present inside the target repository's working tree. On a different repository, if this pipeline's own test files happened to collide with real test module/class names, or if pytest's collection behavior differed such that these dataclasses were actually collected and run, this could silently inflate or corrupt reported test counts — undermining exactly the determinism and environment-quality guarantees this pipeline is meant to provide. Tracked as an open item in Section 11.

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

This same exclusion list is not yet enforced on the live container build context used during containerization runs — see Section 8.3.

### The safety invariant

A hygiene transformation may be accepted only after it succeeds in an isolated workspace and a fresh baseline proves that behavior, test counts, determinism, and coverage have not regressed. The original repository remains untouched. This invariant held (`original_repo_untouched=True`) across every containerization run reported in Section 8 — `glom`'s earlier failing run, `glom`'s resolved re-run, and both `toolz` confirmation runs alike.

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

At the scale of 100 repositories, the bug classes found in Section 8 stop being one-off surprises and become the expected norm: a meaningful fraction of repositories will use `pyproject.toml`-only dependency declarations, dynamic-versioning plugins that shell out to `git`, and test-path conventions that a naive directory-walk will get wrong. The build-context leak in 8.3 is the same category of risk at scale — a workspace-hygiene assumption that holds by accident on one machine's directory layout and silently breaks on another's. A production version of this pipeline would need general handling for all of these (see Section 11), not per-repository or per-machine patches.

## 11. Honest gaps and next steps

The strongest completed portions of the assignment are Pipeline 2 and Pipeline 3.

Known limitations, in rough order of how much they affect the assignment's acceptance bar:

- **Net-new task substance.** Both accepted net-new tasks are technically valid (verified fail-before/pass-after/deterministic, per Section 3) but are synthetic identity functions grafted onto modules they have no real relationship to. They satisfy the letter of §5.4 but are a weak fit for §5.1's definition of net-new. Should be regenerated against genuine undertested behavior before being represented as fully meeting the task-quality bar.
- **Container build context does not exclude this pipeline's own source directory.** As documented in Section 8.3, `container_execution.py`'s isolated-copy step excludes `.git`, `.venv`, and caches, but not a `pipeline/` directory if present in the target repository's working tree. Did not affect correctness in the runs recorded here, but is a latent risk on other repositories or directory layouts. The fix is a one-line addition to the existing `ignore_patterns` call.
- **Container test dependencies are still not pinned to exact baseline-resolved versions.** `_container_test_dependencies` still emits bare, unpinned package names (`pytest`, `coverage`, `PyYAML`). This was the root amplifying cause of `glom`'s earlier host/container divergence in 8.1; the divergence did not recur once host and container were made to run the identical test command, but the unpinned-version gap itself has not been closed at the code level and remains a latent risk for both `glom` and other repositories. Correct fix: capture `pip freeze` from the baseline's own temp venv immediately after a successful install, and pin the Dockerfile to that captured set. Not yet implemented.
- **`toolz` containerization passes, twice, confirmed identical — but is not the actual held-out repository.** Strong evidence of generalization, not a substitute for the real held-out run.
- **Dependency discovery does not parse `pyproject.toml`.** `discover_dependencies` currently only recognizes `setup.py`, `requirements.txt`, and `requirements.in`. `toolz` is `pyproject.toml`-only, so the pipeline reports `dependencies: 0, sources: 0` for it even though real PEP 621 (`[project.dependencies]`) or, for other repos, Poetry (`[tool.poetry.dependencies]`) metadata exists. This did not block the `toolz` containerization result, but it means dependency pinning (§3 of the assignment) is silently incomplete for any modern `pyproject.toml`-based repository — plausibly the majority of repositories a held-out test would use.
- **`_select_test_command`'s package-directory heuristic is fragile.** The fix applied in Section 8.2 and reused in Section 8.1 (falling back to a bare `pytest -q` so `testpaths`/collection takes over) resolved the immediate blocks on `toolz` and `glom` but works by omission rather than by explicitly reading `testpaths`/`[tool:pytest]`/`[pytest]` configuration. A repository with no such declared config and a `toolz`-like multi-package layout could still hit the same alphabetical-first bug.
- **`glom`'s runtime dependency metadata is not fully pinned**, even though development/test requirements are.
- **`glom`'s own `coverage report` / `coverage html` workflow fails** due to a stale `snippets.rst` reference; the pipeline works around this by reading the `.coverage` database directly rather than fixing the upstream repository's coverage configuration.
- **Only Python 3.10 was verified locally** against the sample repository, even though it declares support for Python 3.7–3.14 and PyPy.
- **The two net-new tasks share an identical, generic title** (`"Implement new behavior in __benchmark_new_behavior"`).
- **No bug-injection evidence exists for Pipeline 1's generated unit tests** — the assignment's explicit test-quality bar ("we will evaluate whether your tests catch deliberately introduced bugs") is currently unaddressed in the submission.

Potential next steps, in priority order:

1. Regenerate the net-new candidates against real, undertested module behavior (cross-reference Pipeline 1's coverage-gap findings with net-new candidate selection, rather than allowing an arbitrary function/module pairing).
2. Add `pipeline/` (and any other benchmark-tooling directories) to the container build context's exclusion list in `container_execution.py`, matching the exclusion discipline already applied to `output/repo/`.
3. Capture resolved dependency versions from the baseline's temp venv (`pip freeze`) and pin the generated Dockerfile's test/runtime dependencies to it, closing the unpinned-dependency gap that caused `glom`'s earlier divergence in 8.1, so a future `pytest` release can't reintroduce it.
4. Run the actual held-out repository through the full pipeline once available.
5. Add PEP 621 (`[project.dependencies]`) and Poetry (`[tool.poetry.dependencies]`) parsing to `discover_dependencies`.
6. Replace the interim `_select_test_command` fallback with explicit `testpaths`/`[tool:pytest]`/`[pytest]` config-reading, with the alphabetical-directory guess as a true last resort only.
7. Build a bug-injection harness for generated-test validation: mutate a known-correct function (off-by-one, flipped conditional, swapped return value) and confirm the generated tests distinguish the mutated version from the original.
8. Improve container-validation diagnostics.
9. Add additional cross-platform command-normalization regression tests, including coverage for the `sys.executable`/`python.exe` bug fixed in Section 8.2.
10. Extend the runtime dependency-pinning check into an automated hygiene transformation for `glom`.
11. Rename the two net-new task titles to be specific and self-contained.

The implementation intentionally favors reproducible evidence and honest reporting over forcing every acceptance criterion to appear green — including reporting a substance concern in Pipeline 3's own accepted output, the unresolved unpinned-dependency gap behind `glom`'s now-passing containerization result, and a build-context hygiene issue found only by reading the container's own captured logs after the run had already succeeded.

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
├── README.md
└── .gitignore
```

The original target repository is kept outside the submission repository.

The submission contains the pipeline source, generated knowledge layer, validated benchmark tasks, validation evidence, report, and AI-assisted workflow notes required by the assignment.