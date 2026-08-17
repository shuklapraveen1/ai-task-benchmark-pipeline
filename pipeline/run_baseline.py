import json
from dataclasses import asdict

from pipeline.baseline import run_baseline
from pipeline.dependencies import discover_dependencies
from pipeline.discover import discover_repo


repo_path = "."

context = discover_repo(repo_path)

dependency_info = discover_dependencies(
    repo_path,
    context,
)

result = run_baseline(
    repo_path,
    context,
    dependency_info,
    repeat_count=2,
)

print(
    json.dumps(
        asdict(result),
        indent=2,
    )
)
