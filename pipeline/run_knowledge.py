from __future__ import annotations
import sys
from pathlib import Path

from pipeline.discover import discover_repo
from pipeline.knowledge import emit_okf, parse_python_source_tree


def main() -> int:

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

    print("=" * 70)
    print("PIPELINE 2 - KNOWLEDGE LAYER INTEGRATION")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Repository discovery
    # ------------------------------------------------------------------
    print("\n[1/3] Discovering repository...")

    context = discover_repo(str(repo))

    print(f"  ecosystem: {context.ecosystem}")
    print(f"  frameworks: {context.test_frameworks}")

    if getattr(context, "coverage_tools", None):
        print(f"  coverage tools: {context.coverage_tools}")

    # ------------------------------------------------------------------
    # 2. AST parsing + relationship resolution
    # ------------------------------------------------------------------
    print("\n[2/3] Building knowledge graph...")

    result = parse_python_source_tree(repo)

    print(f"  modules: {len(result.modules)}")
    print(f"  symbols: {len(result.symbols)}")
    print(f"  imports: {len(result.imports)}")
    print(f"  inheritance edges: {len(result.inheritance)}")
    print(f"  call edges: {len(result.calls)}")
    print(f"  diagnostics: {len(result.diagnostics)}")

    # ------------------------------------------------------------------
    # 3. Deterministic .okf emission
    # ------------------------------------------------------------------
    print("\n[3/3] Emitting .okf knowledge layer...")

    okf_dir = emit_okf(
        result,
        repo,
    )

    print(f"  output: {okf_dir}")

    artifacts = sorted(
        path.name
        for path in okf_dir.glob("*.json")
    )

    for artifact in artifacts:
        print(f"    - {artifact}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("KNOWLEDGE LAYER SUMMARY")
    print("=" * 70)

    print(f"  modules:             {len(result.modules)}")
    print(f"  symbols:             {len(result.symbols)}")
    print(f"  import edges:        {len(result.imports)}")
    print(f"  inheritance edges:   {len(result.inheritance)}")
    print(f"  call edges:          {len(result.calls)}")
    print(f"  parse diagnostics:   {len(result.diagnostics)}")
    print(f"  okf directory:       {okf_dir}")
    print(f"  repo graph:          {okf_dir / 'repo_graph.json'}")

    if result.diagnostics:
        print("\nDiagnostics:")

        for diagnostic in result.diagnostics:
            print(
                f"  - {diagnostic.path}: "
                f"{diagnostic.error}"
            )

    print("\nKnowledge extraction complete.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())