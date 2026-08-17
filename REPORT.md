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

Every accepted task contains the required task artifacts and validation evidence, though see Section 11 for an open concern about the soundness of net-new task fail-before validation specifically.

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

A second, more serious instance of this same principle was found and fixed during held-out-style testing against a second repository (`toolz`) — see Section 8. `_select_test_command`'s original package-directory heuristic picked a directory purely by alphabetical order, which is not equivalent to trusting the repository's own declared test configuration. That gap is documented in Section 8 and Section 11 rather than being silently patched over.

### Portable commands

Baseline test commands may contain environment-specific interpreter paths or temporary workspace paths.

The task-generation and containerization layers normalize interpreter paths and remove temporary workspace prefixes from portable commands: absolute paths inside the repository are rewritten relative to the repository root, and absolute paths outside the repository are never allowed to leak into a generated command.

For Python commands, environment-specific Python executables are normalized to the portable token `python`, since that is what is guaranteed to be on `PATH` inside the `python:3.10-slim` container base image — not the host interpreter's own basename (e.g. `python.exe` on a Windows dev machine). This was previously implemented by substituting `sys.executable` and routing it through the same absolute-path normalization used for arguments, which caused it to collapse to the host interpreter's basename (`python.exe`) rather than the portable token, and was confirmed to break container execution (`exec: "python.exe": executable file not found in $PATH`) during held-out testing. This has been fixed: `container_proposal.py` now hardcodes `command[0] = "python"` directly rather than deriving it from `sys.executable`, which removes the platform-dependence entirely rather than papering over one observed symptom of it.

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

Candidates failing these checks are rejected. **This principle was itself found to be under-enforced for net-new tasks specifically; see Section 11 for the open issue.**

### Candidate selection

The miner intentionally generates more candidates than required and filters them through validation.

The final sample run considered:

- 20 history candidates
- 90 excision candidates
- 1,096 net-new candidates

Only candidates satisfying the required validation conditions were accepted.

This prioritizes genuinely validated tasks over weak or unverifiable candidates. **However, net-new candidate generation currently hard-caps at exactly the quota (2) with no retry headroom if a candidate fails validation — see Section 11.**

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

**Open concern:** during later debugging (Section 11), it was found that the net-new fail-before check currently falls back to the full doctest-suite verification command rather than a command that actually invokes the new stub function. Because nothing in the repository's existing test suite calls a not-yet-implemented function, fail-before can never observe the intended stub failure through that fallback command — it either fails for an unrelated reason or does not fail at all. This calls into question whether the two currently-accepted net-new tasks satisfy the assignment's explicit requirement (§5.4) that fail-before "fails for the right reason (an assertion about behavior)." This is flagged here rather than silently left as a passing result.

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

**Open items, in order of severity:**

1. **Fail-before validation soundness (see Section 11).** The two net-new tasks above should be re-validated to confirm their `evidence/fail_before` logs actually assert against a call to the new stub function, not the fallback doctest command. If they do not, these two tasks do not currently meet §5.4's fail-before requirement and should either be regenerated with a corrected verifier command, or excluded from the final 10 pending a fix.
2. **Generic, duplicate titles.** Both net-new tasks share the identical title `"Implement new behavior in __benchmark_new_behavior"`. Titles should be made specific and self-contained per §5.3.
3. **`glom._version` as a net-new target.** This module should be reviewed to confirm it represents genuine new capability rather than a low-substance version-string check.

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
python pipeline/run_containerization.py
```

run from within a target repository checkout. See Section 8 for full results on both `glom` and a second, held-out-style repository (`toolz`).

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

All task validation statuses passed per the pipeline's own recorded verdicts, though see Section 3 and Section 11 for an open concern about whether that verdict is currently sound for the two net-new tasks specifically.

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

## 8. Containerization: findings, held-out validation, and fixes

Containerization support was implemented and exercised through the Pipeline 1 container execution flow (`pipeline/run_containerization.py`, `pipeline/container_proposal.py`, `pipeline/container_execution.py`) against both the sample repository (`glom`) and a second, previously-unseen repository (`toolz`), used specifically to test generality per the assignment's held-out-repository requirement.

### 8.1 glom: host/container divergence and its real root cause

The sample repository did not reach the complete container acceptance bar on the first attempt.

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

**Root cause, refined.** `glom/tutorial.py` and `glom/test/test_tutorial.py` share module-level mutable autoincrement state (`count(1)`-style generators backing `Email`/`Contact` construction). The exact ID assigned to a constructed object depends on how many other `Email`/`Contact` instances were constructed earlier in the same test process — which depends on pytest's test collection order. The host baseline ran under `pytest 6.2.5` (the version already present / resolved in the trusted baseline venv); the generated container Dockerfile installs a bare, unpinned `pytest`, which resolved to `pytest 9.1.1` at container-build time. Different pytest versions can have different default collection/plugin ordering, which changed the order in which `Email`/`Contact` objects were constructed before the tutorial doctest ran, changing the observed ID.

This means the failure has two layers, not one:

1. A genuine, pre-existing design issue in the sample repository itself: `tutorial.py`'s doctest output is execution-order-dependent, which is exactly the class of hidden non-determinism the benchmark pipeline is meant to surface.
2. An amplifying issue in the pipeline's own Dockerfile generation: because `_container_test_dependencies` installs test tooling unpinned (bare `pytest`, `PyYAML`), the container's dependency versions are not guaranteed to match the trusted host baseline's resolved versions, so the container is not a faithful reproduction of the baseline environment. This is a **repo-agnostic bug in the pipeline**, independent of `glom`'s specific flaw, and is tracked as an open item in Section 11.

Rather than modifying the upstream repository solely to force the benchmark acceptance check to become green, the `glom` `tutorial.py` behavior was preserved and documented as a repository/environment limitation. `original_repo_untouched=True` remained true throughout, and the container remained disposable. The submission does not claim the sample repository fully passed the Docker acceptance requirement.

### 8.2 Held-out generalization test: toolz

To test generality beyond `glom` specifically (per the assignment's explicit warning that the pipeline "will also be run against a second, held-out repository that you have not seen"), the full containerization flow was run end to end against `toolz` (github.com/pytoolz/toolz), a repository not previously used in development. This surfaced three real, repo-agnostic bugs, in the order they were hit and fixed:

**Bug 1 — package-directory selection blocked containerization entirely.**
`_select_test_command`'s original heuristic picked the first top-level directory (alphabetically) containing an `__init__.py`. `toolz` has two candidate directories, `tlz` (a legacy compatibility alias package with no tests) and `toolz` (the real package); `"tlz" < "toolz"` alphabetically, so the pipeline selected `tlz`, ran `pytest -q .../tlz`, got "no tests ran" (exit code 5), and correctly-but-wrongly treated this as a failed baseline — blocking containerization before Docker was ever invoked, even though `toolz`'s real suite (186 tests) passes cleanly. `toolz`'s own `pyproject.toml` already declares the correct target (`[tool.pytest.ini_options] testpaths = ["toolz"]`); the pipeline was not honoring it. Interim fix: fall back to a bare `pytest -q` with no explicit path argument when the discovery heuristic is not confident, letting `pytest` apply the repository's own `testpaths` configuration itself. This resolved the block: baseline then ran `186 passed, 186 passed` across two repeat runs, deterministic, `overall_passed: True`.

**Bug 2 — interpreter substitution produced a non-portable container command.**
As described in Section 2, the original `_baseline_test_command` substituted `sys.executable` and then normalized it through path logic meant for arguments, collapsing it to the host interpreter's basename (`python.exe` on the Windows development machine). The container build succeeded, but `docker run` failed immediately: `exec: "python.exe": executable file not found in $PATH`. Fixed by hardcoding `command[0] = "python"` directly in `container_proposal.py`, removing the host-basename dependency entirely.

**Bug 3 — missing git binary and excluded `.git` broke dynamic versioning.**
With Bug 2 fixed, the container built and ran, but one test failed inside the container that passed on the host: `test_has_version`, asserting `toolz.__version__.startswith("1.")`. Inside the container, `toolz.__version__` resolved to the placeholder `0.0.1` instead of the real `1.1.0`. `toolz` uses `setuptools-git-versioning` (`dynamic = ["version"]` in `pyproject.toml`), which computes its version at build time by shelling out to `git describe`. Two compounding causes: (a) the isolated container build workspace (`_copy_repository` in `container_execution.py`) explicitly excludes `.git` via `ignore_patterns`, and (b) the `python:3.10-slim` base image has no `git` binary at all. Either alone is enough to break any package using `setuptools-scm`, `setuptools-git-versioning`, `versioneer`, `hatch-vcs`, or similar dynamic-versioning plugins — a real, repo-agnostic bug class, not a `toolz` quirk. Fixed by (a) installing git in the generated Dockerfile (`RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*`) and (b) no longer excluding `.git` from the isolated container build context copy.

**Result after all three fixes:**

```text
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

This is the first fully green, end-to-end containerization result obtained against a repository other than the original sample, and it demonstrates — rather than merely argues — that the pipeline's containerization path generalizes once the three bugs above are fixed. See Section 11 for what is still outstanding (running this twice in a row to confirm the assignment's determinism bar, and the still-unpinned test-dependency versions that originally amplified the `glom` finding in 8.1).

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

A hygiene transformation may be accepted only after it succeeds in an isolated workspace and a fresh baseline proves that behavior, test counts, determinism, and coverage have not regressed. The original repository remains untouched. This invariant held (`original_repo_untouched=True`) across every containerization run reported in Section 8, including the failing ones.

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

At the scale of 100 repositories, the bug classes found in Section 8 stop being one-off surprises and become the expected norm: a meaningful fraction of repositories will use `pyproject.toml`-only dependency declarations, dynamic-versioning plugins that shell out to `git`, and test-path conventions that a naive directory-walk will get wrong. A production version of this pipeline would need general handling for all three (see Section 11), not per-repository patches.

## 11. Honest gaps and next steps

The strongest completed portions of the assignment are Pipeline 2 and Pipeline 3.

Known limitations, in rough order of how much they affect the assignment's acceptance bar:

- **Net-new task fail-before validation may not be sound.** `_make_net_new_candidates` hard-caps generation at exactly the quota (2) with no retry headroom if a candidate fails validation, and — more seriously — the fail-before verifier command for net-new stub functions currently falls back to the full doctest-suite command rather than a command that actually calls the new stub. Since nothing in the existing test suite calls a function that doesn't exist yet, fail-before cannot observe the intended "an assertion about the stub's absent behavior" failure through that fallback — it can only fail (or not fail) for an unrelated reason. This means the two currently-accepted net-new tasks should be re-audited against §5.4's explicit requirement that fail-before "fails for the right reason," before being represented as validated. This is the most serious open item in the submission and should be resolved or the two tasks should be regenerated/excluded before final submission.
- **Container acceptance was not yet confirmed twice-in-a-row per the assignment's literal bar.** Section 8.2's `toolz` run passed fully (build + container test run, matching host results exactly), which is strong evidence the pipeline generalizes — but §3's acceptance bar requires the container test run to pass "twice in a row with identical results." That second confirming run has not yet been executed and recorded. `glom` still does not pass at all, for the reasons in 8.1.
- **Dependency discovery does not parse `pyproject.toml`.** `discover_dependencies` currently only recognizes `setup.py`, `requirements.txt`, and `requirements.in`. `toolz` has none of these — it is `pyproject.toml`-only — so the pipeline reports `dependencies: 0, sources: 0` for it even though real dependency/metadata sections exist under PEP 621 (`[project.dependencies]`, `[project.optional-dependencies]`) or, for other repositories, Poetry (`[tool.poetry.dependencies]`). This did not block the `toolz` containerization result in Section 8.2, but it means the dependency-pinning deliverable (§3 of the assignment) is currently silently incomplete for any modern `pyproject.toml`-based repository — plausibly the majority of repositories a held-out test would use, not an edge case.
- **Container test dependencies are not pinned to the exact baseline-resolved versions.** `_container_test_dependencies` still emits bare, unpinned package names (`pytest`, `PyYAML`) into the generated Dockerfile's `RUN pip install` line. This was the root amplifying cause of the `glom` finding in 8.1 (host baseline resolved `pytest 6.2.5`; the container independently resolved `pytest 9.1.1`, changing test collection order). The correct fix is to capture the exact resolved versions from the baseline's own temporary virtual environment (e.g. `pip freeze` immediately after a successful baseline install) and pin the Dockerfile to that captured set, rather than inferring versions from any external source. This is not yet implemented.
- **`_select_test_command`'s package-directory heuristic is fragile.** The interim fix in Section 8.2 (falling back to a bare `pytest -q` so the repository's own `testpaths` configuration takes over) resolved the immediate block on `toolz`, but it works by omission rather than by explicitly reading `testpaths` / `[tool:pytest]` / `[pytest]` configuration. A repository with no such declared config and a `toolz`-like multiple-top-level-package layout could still hit the same alphabetical-first bug. This should be replaced with explicit config-reading before final submission.
- **`glom`'s runtime dependency metadata is not fully pinned**, even though development/test requirements are.
- **`glom`'s own `coverage report` / `coverage html` workflow fails** due to a stale `snippets.rst` reference; the pipeline works around this by reading the `.coverage` database directly rather than fixing the upstream repository's coverage configuration.
- **Only Python 3.10 was verified locally** against the sample repository, even though it declares support for Python 3.7–3.14 and PyPy.
- **The two net-new tasks share an identical, generic title** (`"Implement new behavior in __benchmark_new_behavior"`) and one targets `glom._version`, which should be reviewed for substance. See Section 3.

Potential next steps, in priority order:

1. Audit and, if necessary, fix the net-new fail-before verifier command so it genuinely invokes the new stub function, then re-validate (or regenerate) the two accepted net-new tasks.
2. Re-run the `toolz` containerization flow a second time to confirm identical results, satisfying the assignment's literal determinism bar; do the same against the actual held-out repository once available.
3. Capture resolved dependency versions from the baseline's temp venv (`pip freeze`) and use that to pin the generated Dockerfile's test/runtime dependencies, closing the `glom` root cause from 8.1.
4. Add PEP 621 (`[project.dependencies]`) and Poetry (`[tool.poetry.dependencies]`) parsing to `discover_dependencies`.
5. Replace the interim `_select_test_command` fallback with explicit `testpaths`/`[tool:pytest]`/`[pytest]` config-reading, with the alphabetical-directory guess as a true last resort only.
6. Improve container-validation diagnostics.
7. Add additional cross-platform command-normalization tests, including regression coverage for the `sys.executable`/`python.exe` bug fixed in Section 8.2.
8. Expand generated-test quality checks, including deliberate bug-injection validation for Pipeline 1's generated unit tests.
9. Extend the runtime dependency-pinning check into an automated hygiene transformation for `glom`.
10. Rename the two net-new task titles to be specific and self-contained.

The implementation intentionally favors reproducible evidence and honest reporting over forcing every acceptance criterion to appear green — including reporting a bug found in Pipeline 3's own validation logic against the submission's own accepted tasks, rather than treating a passing validation status as final proof of correctness.

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