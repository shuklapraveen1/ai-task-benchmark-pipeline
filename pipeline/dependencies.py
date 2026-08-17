import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from pipeline.discover import RepoContext


def normalize_package_name(name: str) -> str:
    """
    Normalize a Python package name according to PEP 503.

    Runs of '-', '_' and '.' are treated as equivalent and
    normalized to a single '-'. The result is lower-case.

    Examples:
        PyYAML -> pyyaml
        typing_extensions -> typing-extensions
        My.Package -> my-package
    """
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class Dependency:
    name: str
    normalized_name: str
    raw_requirement: str
    constraint: Optional[str]
    scope: str
    source: str
    pinned: bool


@dataclass
class DependencySource:
    path: str
    kind: str
    scope: str
    has_exact_pins: bool
    has_unpinned: bool
    dependency_count: int


@dataclass
class DependencyInfo:
    dependencies: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    # Indicates we found a fully pinned dependency source (e.g., requirements.txt with == pins).
    # NOTE: This does NOT mean the installation is deterministic or that the pinned file
    # controls the runtime installation. It is strictly a discovery-level observation.

    has_pinned_environment: bool = False
    pinned_sources: list = field(default_factory=list)

    warnings: list = field(default_factory=list)


# Basic PEP 508-style package name.
# We intentionally keep this conservative for v1.
PACKAGE_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _parse_requirement(requirement, scope, source):
    """
    Parse a simple requirement such as:

        attrs>=19.2.0
        coverage<=7.2.7
        pytest==7.4.4

    Returns a Dependency or None for lines that aren't dependencies.
    """

    raw = requirement.strip()

    if not raw:
        return None

    # Comments.
    if raw.startswith("#"):
        return None

    # pip options and editable/local requirements.
    if raw.startswith("-"):
        return None

    match = PACKAGE_NAME_RE.match(raw)

    if not match:
        return None

    name = match.group(1)

    remainder = raw[match.end() :].strip()

    # Remove environment marker from the version expression.
    #
    # Example:
    #   tomli==2.0.1; python_version < "3.11"
    #
    # The dependency is still pinned because its package version
    # is exact.
    if ";" in remainder:
        remainder = remainder.split(";", 1)[0].strip()

    # Remove extras from the package name portion if present.
    #
    # Example:
    #   requests[socks]>=2.0
    #
    # We keep the dependency name as "requests".
    if "[" in name:
        name = name.split("[", 1)[0]

    constraint = remainder or None

    # Only == counts as an exact pin.
    pinned = bool(
        constraint
        and re.fullmatch(
            r"==\s*[A-Za-z0-9!+_.-]+",
            constraint,
        )
    )

    return Dependency(
        name=name,
        normalized_name=normalize_package_name(name),
        raw_requirement=raw,
        constraint=constraint,
        scope=scope,
        source=source,
        pinned=pinned,
    )


def _parse_setup_py(path):
    """
    Statically inspect setup.py using AST.

    We look for:
        setup(install_requires=[...])
        setup(extras_require={...})

    setup.py is never executed.
    """

    dependencies = []
    warnings = []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return dependencies, warnings + ["Could not read {}: {}".format(path.name, exc)]

    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError as exc:
        return dependencies, warnings + [
            "Could not parse {}: {}".format(path.name, exc)
        ]

    setup_calls = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Name) and node.func.id == "setup":
            setup_calls.append(node)

        elif isinstance(node.func, ast.Attribute) and node.func.attr == "setup":
            setup_calls.append(node)

    if not setup_calls:
        warnings.append("No setup() call found in setup.py.")
        return dependencies, warnings

    setup_call = setup_calls[-1]

    for keyword in setup_call.keywords:
        if keyword.arg == "install_requires":
            try:
                values = ast.literal_eval(keyword.value)
            except (ValueError, TypeError, SyntaxError):
                warnings.append(
                    "Could not statically evaluate install_requires in setup.py."
                )
                continue

            if not isinstance(values, (list, tuple)):
                warnings.append("install_requires in setup.py is not a list/tuple.")
                continue

            for requirement in values:
                if not isinstance(requirement, str):
                    continue

                dependency = _parse_requirement(
                    requirement,
                    scope="runtime",
                    source="setup.py",
                )

                if dependency is not None:
                    dependencies.append(dependency)

        elif keyword.arg == "extras_require":
            try:
                extras = ast.literal_eval(keyword.value)
            except (ValueError, TypeError, SyntaxError):
                warnings.append(
                    "Could not statically evaluate extras_require in setup.py."
                )
                continue

            if not isinstance(extras, dict):
                warnings.append("extras_require in setup.py is not a dictionary.")
                continue

            for extra_name, requirements in extras.items():
                if not isinstance(requirements, (list, tuple)):
                    continue

                for requirement in requirements:
                    if not isinstance(requirement, str):
                        continue

                    dependency = _parse_requirement(
                        requirement,
                        scope="optional",
                        source="setup.py",
                    )

                    if dependency is not None:
                        dependencies.append(dependency)

    return dependencies, warnings


def _parse_requirements_file(
    path,
    scope,
):
    """
    Parse a requirements.in or requirements.txt file.

    v1 intentionally handles ordinary requirement lines and ignores
    pip command/options. Include directives are recorded as warnings
    rather than silently pretending they were parsed.
    """

    dependencies = []
    warnings = []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return dependencies, ["Could not read {}: {}".format(path.name, exc)]

    for line_number, line in enumerate(
        content.splitlines(),
        start=1,
    ):
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            continue

        # Strip inline comments when separated by whitespace.
        stripped = re.sub(
            r"\s+#.*$",
            "",
            stripped,
        ).strip()

        if not stripped:
            continue

        if stripped.startswith("-r ") or stripped.startswith("--requirement "):
            warnings.append(
                "{}:{} contains an included requirements file; "
                "nested includes are not parsed in v1.".format(
                    path.name,
                    line_number,
                )
            )
            continue

        dependency = _parse_requirement(
            stripped,
            scope=scope,
            source=path.name,
        )

        if dependency is not None:
            dependencies.append(dependency)

    return dependencies, warnings


def _source_from_dependencies(
    path,
    kind,
    scope,
    dependencies,
):
    return DependencySource(
        path=path,
        kind=kind,
        scope=scope,
        has_exact_pins=any(dependency.pinned for dependency in dependencies),
        has_unpinned=any(not dependency.pinned for dependency in dependencies),
        dependency_count=len(dependencies),
    )


def discover_dependencies(
    repo_path: Union[str, Path],
    context: RepoContext,
) -> DependencyInfo:
    """
    Discover dependency declarations from supported Python dependency
    sources.

    Supported in v1:
        setup.py
        requirements.in
        requirements.txt

    This function is read-only and never installs or executes
    repository code.
    """

    repo_path = Path(repo_path).resolve()

    info = DependencyInfo()

    # ---------------------------------------------------------
    # setup.py
    # ---------------------------------------------------------

    if "setup.py" in context.discovered_files:
        setup_path = repo_path / "setup.py"

        dependencies, warnings = _parse_setup_py(setup_path)

        info.dependencies.extend(dependencies)
        info.warnings.extend(warnings)

        runtime_dependencies = [
            dependency for dependency in dependencies if dependency.scope == "runtime"
        ]

        optional_dependencies = [
            dependency for dependency in dependencies if dependency.scope == "optional"
        ]

        if runtime_dependencies:
            info.sources.append(
                _source_from_dependencies(
                    path="setup.py",
                    kind="setup",
                    scope="runtime",
                    dependencies=runtime_dependencies,
                )
            )

        if optional_dependencies:
            info.sources.append(
                _source_from_dependencies(
                    path="setup.py",
                    kind="setup",
                    scope="optional",
                    dependencies=optional_dependencies,
                )
            )

    # ---------------------------------------------------------
    # requirements.in
    # ---------------------------------------------------------

    if "requirements.in" in context.discovered_files:
        requirements_in = repo_path / "requirements.in"

        dependencies, warnings = _parse_requirements_file(
            requirements_in,
            scope="development",
        )

        info.dependencies.extend(dependencies)
        info.warnings.extend(warnings)

        info.sources.append(
            _source_from_dependencies(
                path="requirements.in",
                kind="requirements",
                scope="development",
                dependencies=dependencies,
            )
        )

    # ---------------------------------------------------------
    # requirements.txt
    # ---------------------------------------------------------

    if "requirements.txt" in context.discovered_files:
        requirements_txt = repo_path / "requirements.txt"

        dependencies, warnings = _parse_requirements_file(
            requirements_txt,
            scope="development",
        )

        info.dependencies.extend(dependencies)
        info.warnings.extend(warnings)

        info.sources.append(
            _source_from_dependencies(
                path="requirements.txt",
                kind="requirements",
                scope="development",
                dependencies=dependencies,
            )
        )

    # ---------------------------------------------------------
    # Determine whether we found a pinned environment.
    # ---------------------------------------------------------

    for source in info.sources:
        if source.has_exact_pins and not source.has_unpinned:
            info.has_pinned_environment = True

            if source.path not in info.pinned_sources:
                info.pinned_sources.append(source.path)

    return info
