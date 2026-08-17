"""
pipeline
========

AI Task Benchmark & Evaluation Infrastructure.

This package contains three stages:

- Pipeline 1: Repository Hygiene (baseline, hygiene, containerization)
- Pipeline 2: Knowledge Layer (OKF extraction)
- Pipeline 3: Task Generation (mining, synthesis, verification)

This file is intentionally left minimal. It exists only to mark
`pipeline/` as an importable Python package and does not import any
submodules eagerly, so importing `pipeline` will not trigger side
effects or pull in heavy dependencies unless you explicitly import
the submodule you need, e.g.:

    from pipeline import run_baseline
    from pipeline import run_knowledge
    from pipeline import run_tasks
"""

__all__: list[str] = []