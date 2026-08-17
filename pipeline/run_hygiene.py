import pprint

from pipeline.discover import discover_repo
from pipeline.dependencies import discover_dependencies
from pipeline.baseline import run_baseline
from pipeline.lint_format import discover_lint_format
from pipeline.hygiene_proposal import propose_hygiene
from pipeline.hygiene_mutation import (
    HygieneChange,
    apply_hygiene_change,
)


def main():
    repo_path = "."

    print("=" * 70)
    print("PIPELINE 1 - HYGIENE INTEGRATION")
    print("=" * 70)

    # ---------------------------------------------------------------
    # 1. Repository discovery
    # ---------------------------------------------------------------

    print("\n[1/7] Discovering repository...")

    context = discover_repo(repo_path)

    print(f"  ecosystem: {context.ecosystem}")
    print(f"  frameworks: {context.test_frameworks}")

    # ---------------------------------------------------------------
    # 2. Dependency discovery
    # ---------------------------------------------------------------

    print("\n[2/7] Discovering dependencies...")

    dependency_info = discover_dependencies(
        repo_path,
        context,
    )

    print(f"  dependencies: {len(dependency_info.dependencies)}")
    print(f"  sources: {len(dependency_info.sources)}")

    # ---------------------------------------------------------------
    # 3. Initial deterministic baseline
    # ---------------------------------------------------------------

    print("\n[3/7] Running initial baseline...")

    baseline = run_baseline(
        repo_path,
        context,
        dependency_info,
    )

    print(f"  overall_passed: {baseline.overall_passed}")
    print(f"  deterministic: {baseline.deterministic}")

    if not baseline.overall_passed:
        print("\nBaseline failed. Hygiene mutation will not be attempted.")

        pprint.pp(baseline)
        return

    if baseline.deterministic is not True:
        print(
            "\nBaseline is not deterministic. Hygiene mutation will not be attempted."
        )

        pprint.pp(baseline)
        return

    # ---------------------------------------------------------------
    # 4. Lint / format discovery
    # ---------------------------------------------------------------

    print("\n[4/7] Discovering lint/format conventions...")

    lint_info = discover_lint_format(
        repo_path,
        context,
    )

    print(f"  existing_conventions: {lint_info.existing_conventions}")
    print(f"  tools: {[tool.name for tool in lint_info.tools]}")
    print(f"  default_standard_proposed: {lint_info.default_standard_proposed}")

    # ---------------------------------------------------------------
    # 5. Hygiene proposal
    # ---------------------------------------------------------------

    print("\n[5/7] Building hygiene proposal...")

    proposal = propose_hygiene(
        lint_info,
        context,
    )

    print(f"  tool: {proposal.tool}")
    print(f"  action: {proposal.action}")
    print(f"  confidence: {proposal.confidence}")
    print(f"  reason: {proposal.reason}")

    # No mutation required.
    if proposal.action == "no_change":
        print("\nNo hygiene change proposed.")
        return

    # ---------------------------------------------------------------
    # 6. Convert proposal -> executable HygieneChange
    # ---------------------------------------------------------------

    print("\n[6/7] Creating hygiene change...")

    if proposal.tool == "ruff":
        if proposal.action == "introduce_default":
            command = [
                "python",
                "-m",
                "ruff",
                "format",
                ".",
            ]

            files = [
                "pyproject.toml",
                "Python source files",
            ]

        elif proposal.action == "fix_existing":
            command = [
                "python",
                "-m",
                "ruff",
                "check",
                ".",
                "--fix",
                "--unsafe-fixes",
            ]

            files = [
                "Python source files",
            ]

        else:
            command = [
                "python",
                "-m",
                "ruff",
                "check",
                ".",
            ]

            files = []

    elif proposal.tool == "black":
        command = [
            "python",
            "-m",
            "black",
            ".",
        ]

        files = []

    elif proposal.tool == "isort":
        command = [
            "python",
            "-m",
            "isort",
            ".",
        ]

        files = []

    elif proposal.tool == "flake8":
        # Flake8 is lint-only and normally does not mutate files.
        command = [
            "python",
            "-m",
            "flake8",
            ".",
        ]

        files = []

    elif proposal.tool == "pylint":
        command = [
            "python",
            "-m",
            "pylint",
            ".",
        ]

        files = []

    else:
        print(f"\nUnsupported hygiene tool: {proposal.tool}")
        return

    change = HygieneChange(
        tool=proposal.tool,
        action=proposal.action,
        command=command,
        files=files,
        reason=proposal.reason,
        confidence=proposal.confidence,
        mutates_files=(
            proposal.tool
            in {
                "ruff",
                "black",
                "isort",
            }
            and proposal.action
            in {
                "introduce_default",
                "fix_existing",
            }
        ),
    )

    print("  command:", change.command)
    print("  mutates_files:", change.mutates_files)

    # ---------------------------------------------------------------
    # 7. Safe isolated mutation + baseline verification
    # ---------------------------------------------------------------

    print("\n[7/7] Applying hygiene change safely...")

    result = apply_hygiene_change(
        repo_path=repo_path,
        context=context,
        dependency_info=dependency_info,
        baseline=baseline,
        change=change,
    )

    print("\n" + "=" * 70)
    print("FINAL HYGIENE RESULT")
    print("=" * 70)

    pprint.pp(result)

    print("\nSummary:")

    # These attribute names correspond to the HygieneResult contract.
    print(
        "  accepted:",
        result.accepted,
    )
    print(
        "  original_repo_untouched:",
        result.original_repo_untouched,
    )
    print("  baseline_passed:", result.validation.baseline_passed)
    print(
        "  changed_files:",
        result.execution.changed_files if result.execution is not None else [],
    )


if __name__ == "__main__":
    main()