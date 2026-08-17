"""
Pipeline 1 - Containerization integration runner.

Orchestrates:

    repository discovery
        -> dependency discovery
        -> deterministic baseline
        -> container discovery
        -> container proposal
        -> isolated container execution
        -> baseline validation

The original repository is never used as a mutation target.
"""

from pprint import pprint

from pipeline.discover import discover_repo
from pipeline.dependencies import discover_dependencies
from pipeline.baseline import run_baseline
from pipeline.containerization import discover_containerization
from pipeline.container_proposal import propose_containerization
from pipeline.container_execution import apply_container_proposal


def main():
    repo_path = "."

    print("=" * 70)
    print("PIPELINE 1 - CONTAINERIZATION INTEGRATION")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Repository discovery
    # ------------------------------------------------------------------
    print("\n[1/7] Discovering repository...")

    context = discover_repo(repo_path)

    print(f"  ecosystem: {context.ecosystem}")
    print(f"  frameworks: {context.test_frameworks}")
    print(f"  coverage tools: {context.coverage_tools}")

    # ------------------------------------------------------------------
    # 2. Dependency discovery
    # ------------------------------------------------------------------
    print("\n[2/7] Discovering dependencies...")

    dependencies = discover_dependencies(
        repo_path,
        context,
    )

    print(f"  dependencies: {len(dependencies.dependencies)}")
    print(f"  sources: {len(dependencies.sources)}")

    # ------------------------------------------------------------------
    # 3. Trusted baseline
    # ------------------------------------------------------------------
    print("\n[3/7] Running initial baseline...")

    baseline = run_baseline(
        repo_path,
        context,
        dependencies,
    )

    print(f"  overall_passed: {baseline.overall_passed}")
    print(f"  deterministic: {baseline.deterministic}")

    if baseline.test_runs:
        first_test = baseline.test_runs[0]

        print(
            "  tests:"
            f" {first_test.tests_passed} passed,"
            f" {first_test.tests_skipped} skipped"
        )

    if baseline.coverage is not None:
        print(
            f"  coverage: {baseline.coverage.coverage_percent}%"
        )

    # ------------------------------------------------------------------
    # Hard safety gate
    # ------------------------------------------------------------------
    #
    # We should never even create a container proposal when the
    # repository does not have a trusted baseline.
    #
    if (
        not baseline.overall_passed
        or baseline.deterministic is not True
    ):
        print("\n" + "=" * 70)
        print("CONTAINERIZATION BLOCKED")
        print("=" * 70)

        print(
            "\nThe repository does not have a trusted deterministic "
            "baseline."
        )
        print(f"  overall_passed: {baseline.overall_passed}")
        print(f"  deterministic: {baseline.deterministic}")
        print("\nDocker execution will not be attempted.")

        return 1

    # ------------------------------------------------------------------
    # 4. Container discovery
    # ------------------------------------------------------------------
    print("\n[4/7] Discovering container conventions...")

    container_info = discover_containerization(
        repo_path,
        context,
    )

    print(
        f"  existing_conventions: "
        f"{container_info.existing_conventions}"
    )

    print(
        f"  default_standard_proposed: "
        f"{container_info.default_standard_proposed}"
    )

    print(
        f"  configurations: "
        f"{len(container_info.configs)}"
    )

    if container_info.warnings:
        print("  warnings:")

        for warning in container_info.warnings:
            print(f"    - {warning}")

    # ------------------------------------------------------------------
    # 5. Container proposal
    # ------------------------------------------------------------------
    print("\n[5/7] Building container proposal...")

    proposal = propose_containerization(
        container_info,
        context,
        baseline,
    )

    print(f"  action: {proposal.action}")
    print(f"  kind: {proposal.kind}")
    print(f"  confidence: {proposal.confidence}")
    print(f"  files: {proposal.files}")
    print(f"  command: {proposal.command}")
    print(f"  reason: {proposal.reason}")

    # ------------------------------------------------------------------
    # 6. Execute safely in isolated workspace
    # ------------------------------------------------------------------
    print("\n[6/7] Applying container proposal safely...")

    print(
        "  original repository will remain untouched."
    )

    print(
        "  Docker will run only against an isolated workspace."
    )

    result = apply_container_proposal(
        repo_path,
        proposal,
        baseline,
    )

    # ------------------------------------------------------------------
    # 7. Final result
    # ------------------------------------------------------------------
    print("\n[7/7] Container validation complete.")

    print("\n" + "=" * 70)
    print("FINAL CONTAINERIZATION RESULT")
    print("=" * 70)

    pprint(result)

    print("\nSummary:")

    print(
        f"  accepted: "
        f"{result.accepted}"
    )

    print(
        f"  original_repo_untouched: "
        f"{result.original_repo_untouched}"
    )

    print(
        f"  validation_passed: "
        f"{result.validation.validation_passed}"
    )

    print(
        f"  baseline_passed: "
        f"{result.validation.baseline_passed}"
    )

    print(
        f"  baseline_deterministic: "
        f"{result.validation.baseline_deterministic}"
    )

    print(
        f"  container_build_passed: "
        f"{result.validation.container_build_passed}"
    )

    print(
        f"  container_tests_passed: "
        f"{result.validation.container_tests_passed}"
    )

    print(
        f"  regression_detected: "
        f"{result.validation.regression_detected}"
    )

    if result.execution is not None:
        print(
            f"  image_built: "
            f"{result.execution.image_built}"
        )

        print(
            f"  tests_executed: "
            f"{result.execution.tests_executed}"
        )

        print(
            f"  build_return_code: "
            f"{result.execution.build_return_code}"
        )

        print(
            f"  test_return_code: "
            f"{result.execution.test_return_code}"
        )

    if result.validation.reasons:
        print("\nValidation reasons:")

        for reason in result.validation.reasons:
            print(f"  - {reason}")

    if result.warnings:
        print("\nWarnings:")

        for warning in result.warnings:
            print(f"  - {warning}")

    print("=" * 70)

    # A successful integration run requires BOTH:
    #
    #   validation_passed == True
    #   original_repo_untouched == True
    #
    # This prevents a false positive where the container happened to
    # pass but the repository safety invariant was violated.
    if (
        result.validation.validation_passed
        and result.original_repo_untouched
    ):
        print("\nPIPELINE 1 CONTAINERIZATION: SUCCESS")
        print(
            "Trusted baseline preserved inside the container."
        )
        print(
            "Original repository remained untouched."
        )

        return 0

    print("\nPIPELINE 1 CONTAINERIZATION: REJECTED")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())