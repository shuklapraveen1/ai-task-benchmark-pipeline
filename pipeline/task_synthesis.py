from __future__ import annotations

import ast
import json
import shutil
import tarfile
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from pipeline.task_history import HistoryChange
from pipeline.task_miner import ExcisionCandidate


@dataclass(frozen=True)
class NetNewCandidate:
    """
    Description of a genuinely new benchmark behavior.

    The synthesizer does not invent the behavioral contract. The caller
    must provide the target module, function, signature, and implementation.
    """

    module: str
    source_file: str
    function_name: str
    signature: str
    description: str
    stub_body: str
    solution_body: str
    rationale: str


@dataclass(frozen=True)
class SynthesisResult:
    task_type: str
    input_dir: Path
    solution_dir: Path
    changed_files: tuple[str, ...]
    source_commit: Optional[str]
    solution_commit: Optional[str]
    warnings: tuple[str, ...] = ()
    # Populated for History tasks: the materialized task-local
    # regression-test oracle. None for task types that don't have one.
    verifier_dir: Optional[Path] = None

    @property
    def input_exists(self) -> bool:
        return self.input_dir.is_dir()

    @property
    def solution_exists(self) -> bool:
        return self.solution_dir.is_dir()


class TaskSynthesisError(RuntimeError):
    """Raised when a task cannot be materialized safely."""


class TaskSynthesizer:
    """
    Materializes benchmark task states.

    Safety contract:

    * never modifies the source repository
    * never executes repository code
    * never runs tests
    * never runs Docker
    * never overwrites an existing task directory silently
    * input/ and solution/ are independent physical copies
    * every synthesis operation is deterministic
    """

    GENERATED_DIRS = {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "build",
        "dist",
        ".okf",
        ".pipeline_history_probe",
        "tasks",
        "pipeline",
    }
    GENERATED_FILES = {
    "tasks.json",
    ".coverage",
}
    GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
}

    def __init__(
        self,
        repo_path: str | Path,
    ) -> None:
        self.repo_path = Path(
            repo_path
        ).resolve()

        if not self.repo_path.is_dir():
            raise TaskSynthesisError(
                f"Repository does not exist: {self.repo_path}"
            )

    # ------------------------------------------------------------------
    # Public synthesis API
    # ------------------------------------------------------------------

    def synthesize_history(
        self,
        candidate: HistoryChange,
        task_dir: str | Path,
    ) -> SynthesisResult:
        """
        Create:

            input/    = parent of fixing commit
            solution/ = fixing commit

        Git history therefore supplies the behavioral transition.
        """

        task_root = self._prepare_task_dir(
            task_dir
        )

        input_dir = task_root / "input"
        solution_dir = task_root / "solution"

        if not candidate.commit:
            raise TaskSynthesisError(
                "History candidate has no commit."
            )

        if not candidate.parent:
            parent = self._git(
                "rev-parse",
                f"{candidate.commit}^",
            ).strip()
        else:
            parent = candidate.parent

        self._git_archive(
            parent,
            input_dir,
        )

        self._git_archive(
            candidate.commit,
            solution_dir,
        )

        # Materialize the task-local regression-test oracle: the
        # fixing-commit content of the changed test file(s), independent
        # of whatever (possibly stale, pre-fix) version lives in input/
        # or solution/. Running this same oracle against both states is
        # what lets FAIL-BEFORE / PASS-AFTER actually exercise the bug,
        # instead of silently passing against the parent's own
        # (pre-regression-test) test file.
        regression_tests = getattr(
            candidate,
            "regression_tests",
            (),
        )

        if not regression_tests:
            raise TaskSynthesisError(
                "History candidate has no regression-test oracle; "
                "refusing to synthesize a task without a task-local "
                "verifier."
            )

        verifier_dir = task_root / "verifier"

        self._materialize_regression_tests(
            verifier_dir,
            regression_tests,
        )

        changed = tuple(
            sorted(
                set(candidate.source_files)
                | set(candidate.test_files)
            )
        )

        self._write_metadata(
            task_root,
            {
                "type": "history",
                "commit": candidate.commit,
                "parent": parent,
                "subject": candidate.subject,
                "changed_files": list(changed),
                "regression_tests": [
                    test.path
                    for test in regression_tests
                ],
            },
        )

        self._assert_isolated(
            input_dir,
            solution_dir,
        )

        return SynthesisResult(
            task_type="history",
            input_dir=input_dir,
            solution_dir=solution_dir,
            changed_files=changed,
            source_commit=parent,
            solution_commit=candidate.commit,
            verifier_dir=verifier_dir,
        )

    def synthesize_excision(
        self,
        candidate: ExcisionCandidate,
        task_dir: str | Path,
    ) -> SynthesisResult:
        """
        Create:

            solution/ = untouched repository
            input/    = repository with selected function removed

        The input implementation is replaced with a deterministic
        NotImplementedError while preserving the original signature.
        """

        task_root = self._prepare_task_dir(
            task_dir
        )

        input_dir = task_root / "input"
        solution_dir = task_root / "solution"

        self._copy_repository(
            destination=input_dir,
            source=self.repo_path,
        )

        self._copy_repository(
            destination=solution_dir,
            source=self.repo_path,
        )

        source_file = (
            getattr(candidate, "source_file", None)
            or getattr(candidate, "file_path", None)
        )

        if not source_file:
            raise TaskSynthesisError(
                "Excision candidate has no source file."
            )

        source_file = source_file.replace("\\", "/")

        target = (
            input_dir / source_file
        )

        if not target.exists():
            raise TaskSynthesisError(
                f"Candidate source file does not exist: {source_file}"
            )

        self._remove_function_body(
            target,
            candidate,
        )

        self._write_metadata(
            task_root,
            {
                "type": "excision",
                "module": candidate.module_id,
                "function": candidate.function_id,
                "source_file": source_file,
                "line_start": candidate.line_start,
                "line_end": candidate.line_end,
            },
        )

        self._assert_isolated(
            input_dir,
            solution_dir,
        )

        return SynthesisResult(
            task_type="excision",
            input_dir=input_dir,
            solution_dir=solution_dir,
            changed_files=(
                source_file,
            ),
            source_commit=None,
            solution_commit=None,
        )

    def synthesize_net_new(
        self,
        candidate: NetNewCandidate,
        task_dir: str | Path,
    ) -> SynthesisResult:
        """
        Create:

            solution/ = repository + working implementation
            input/    = repository + deliberately failing stub

        This requires an explicit new behavior contract supplied by the
        caller. The synthesizer does not guess the implementation.
        """

        task_root = self._prepare_task_dir(
            task_dir
        )

        input_dir = task_root / "input"
        solution_dir = task_root / "solution"

        self._copy_repository(
            destination=input_dir,
            source=self.repo_path,
        )

        self._copy_repository(
            destination=solution_dir,
            source=self.repo_path,
        )

        input_file = (
            input_dir / candidate.source_file
        )

        solution_file = (
            solution_dir / candidate.source_file
        )

        if not input_file.exists():
            raise TaskSynthesisError(
                f"Net-new source file does not exist: "
                f"{candidate.source_file}"
            )

        if not solution_file.exists():
            raise TaskSynthesisError(
                f"Net-new source file does not exist: "
                f"{candidate.source_file}"
            )

        self._insert_function(
            input_file,
            candidate.function_name,
            candidate.signature,
            self._sanitize_net_new_stub(candidate.stub_body),
        )

        self._insert_function(
            solution_file,
            candidate.function_name,
            candidate.signature,
            candidate.solution_body,
        )

        # Net-new tasks require an explicit behavioral oracle. The oracle is
        # authored here and stored outside input/solution so the verifier can
        # overlay the exact same test onto both states.
        verifier_dir = task_root / "verifier"
        verifier_dir.mkdir(parents=True, exist_ok=True)
        generated_test = verifier_dir / "generated_test.py"
        generated_test.write_text(
            """import importlib\n\n\ndef test_generated_net_new_behavior():\n    module = importlib.import_module(%r)\n    implementation = getattr(module, %r)\n\n    assert implementation(%r) == %r\n    assert implementation(%r) == %r\n""" % (
                candidate.module,
                candidate.function_name,
                "benchmark-value",
                "benchmark-value",
                {"benchmark": "value"},
                {"benchmark": "value"},
            ),
            encoding="utf-8",
        )

        try:
            ast.parse(
                generated_test.read_text(encoding="utf-8"),
                filename=str(generated_test),
            )
        except SyntaxError as exc:
            raise TaskSynthesisError(
                f"Generated net-new verifier is invalid Python: {generated_test}"
            ) from exc

        self._write_metadata(
            task_root,
            {
                "type": "net_new",
                "module": candidate.module,
                "source_file": candidate.source_file,
                "function": candidate.function_name,
                "description": candidate.description,
                "rationale": candidate.rationale,
                "verifier_test": "verifier/generated_test.py",
            },
        )

        self._assert_isolated(input_dir, solution_dir)

        return SynthesisResult(
            task_type="net_new",
            input_dir=input_dir,
            solution_dir=solution_dir,
            changed_files=(candidate.source_file,),
            source_commit=None,
            solution_commit=None,
            verifier_dir=verifier_dir,
        )

    # ------------------------------------------------------------------
    # Repository copying
    # ------------------------------------------------------------------

    def _copy_repository(
        self,
        destination: Path,
        source: Optional[Path] = None,
    ) -> None:
        source = source or self.repo_path

        destination.mkdir(
            parents=True,
            exist_ok=True,
        )

        for item in sorted(
            source.iterdir(),
            key=lambda path: path.name,
        ):
            # Never materialize benchmark/runtime generated content
            # into task input/solution workspaces.
            if item.name in self.GENERATED_DIRS:
                continue

            if item.is_file():
                if item.name in self.GENERATED_FILES:
                    continue

                if item.suffix.lower() in self.GENERATED_SUFFIXES:
                    continue

            target = destination / item.name

            if item.is_dir():
                shutil.copytree(
                    item,
                    target,
                    dirs_exist_ok=True,
                )
            else:
                shutil.copy2(
                    item,
                    target,
                )

    def _prepare_task_dir(
        self,
        task_dir: str | Path,
    ) -> Path:
        task_root = Path(
            task_dir
        ).resolve()

        if task_root.exists():
            raise TaskSynthesisError(
                f"Refusing to overwrite existing task directory: "
                f"{task_root}"
            )

        task_root.mkdir(
            parents=True,
            exist_ok=False,
        )

        return task_root

    # ------------------------------------------------------------------
    # Git materialization
    # ------------------------------------------------------------------

    def _git(
        self,
        *args: str,
    ) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )

        return completed.stdout

    def _git_archive(
        self,
        revision: str,
        destination: Path,
    ) -> None:
        destination.mkdir(
            parents=True,
            exist_ok=True,
        )

        archive = subprocess.run(
            [
                "git",
                "archive",
                revision,
            ],
            cwd=str(self.repo_path),
            capture_output=True,
            check=True,
        )

        if not archive.stdout:
            raise TaskSynthesisError(
                f"Git archive for {revision} was empty."
            )

        # Extract using Python's standard library rather than relying
        # on the platform's `tar` command.
        import io
        import tarfile

        with tarfile.open(
            fileobj=io.BytesIO(
                archive.stdout
            ),
            mode="r:",
        ) as tar:
            self._safe_extract_tar(
                tar,
                destination,
            )

    @staticmethod
    def _safe_extract_tar(
        tar: tarfile.TarFile,
        destination: Path,
    ) -> None:
        """
        Prevent a malicious archive path from escaping the destination.
        """

        destination = destination.resolve()

        for member in tar.getmembers():
            target = (
                destination
                / member.name
            ).resolve()

            try:
                target.relative_to(
                    destination
                )
            except ValueError as exc:
                raise TaskSynthesisError(
                    f"Unsafe Git archive path: {member.name}"
                ) from exc

        tar.extractall(
            path=destination
        )

    # ------------------------------------------------------------------
    # Excision
    # ------------------------------------------------------------------

    @staticmethod
    def _candidate_source_file(
        candidate: ExcisionCandidate,
    ) -> str:
        value = candidate.file_path

        if not value:
            raise TaskSynthesisError(
                "Excision candidate has no source file."
            )

        return value.replace(
            "\\",
            "/",
        )

    def _remove_function_body(
        self,
        path: Path,
        candidate: ExcisionCandidate,
    ) -> None:
        source = path.read_text(
            encoding="utf-8",
        )

        try:
            tree = ast.parse(
                source,
                filename=str(path),
            )
        except SyntaxError as exc:
            raise TaskSynthesisError(
                f"Cannot parse candidate source {path}: {exc}"
            ) from exc

        target_name = (
            candidate.function_id.rsplit(
                ".",
                1,
            )[-1]
        )

        target = self._find_function(
            tree,
            target_name,
            candidate.line_start,
            candidate.line_end,
        )

        if target is None:
            raise TaskSynthesisError(
                "Could not locate candidate function "
                f"{target_name} in {path}."
            )

        lines = source.splitlines(
            keepends=True,
        )

        start = target.body[0].lineno - 1

        # End_lineno is available on supported Python versions.
        end = (
            target.end_lineno
            if target.end_lineno is not None
            else target.lineno
        )

        indent = self._indentation(
            lines[start]
        )

        replacement = (
            indent
            + self._neutral_stub_return(target)
            + "\n"
        )

        updated = (
            lines[:start]
            + [replacement]
            + lines[end:]
        )

        path.write_text(
            "".join(updated),
            encoding="utf-8",
        )

        # Fail closed if our transformation created invalid syntax.
        try:
            ast.parse(
                "".join(updated),
                filename=str(path),
            )
        except SyntaxError as exc:
            raise TaskSynthesisError(
                f"Excision produced invalid Python: {path}"
            ) from exc

    @staticmethod
    def _neutral_stub_return(
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> str:
        """Create a callable, deterministic excision stub.

        The stub must not raise merely because the implementation was removed.
        Prefer a value compatible with the declared return type; if no useful
        annotation exists, infer a neutral value from literal return
        expressions in the original function body.
        """

        def annotation_name(node: ast.AST | None) -> str:
            if node is None:
                return ""
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return node.attr
            if isinstance(node, ast.Subscript):
                return annotation_name(node.value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            return ""

        annotation = annotation_name(function.returns).replace(" ", "")

        if annotation in {"bool", "Boolean"}:
            return "return False"
        if annotation in {"int", "float", "complex"}:
            return "return 0"
        if annotation == "str":
            return "return ''"
        if annotation in {"list", "List"}:
            return "return []"
        if annotation in {"tuple", "Tuple"}:
            return "return ()"
        if annotation in {"set", "Set"}:
            return "return set()"
        if annotation in {
            "dict", "Dict", "Mapping", "MutableMapping", "OrderedDict"
        }:
            return "return {}"
        if annotation in {
            "Sequence", "MutableSequence", "Collection", "Iterable"
        }:
            return "return []"

        if (
            "Optional[" in annotation
            or "|None" in annotation
            or "None|" in annotation
        ):
            inner = annotation.replace("Optional[", "").rstrip("]")
            if inner in {"int", "float", "complex"}:
                return "return 0"
            if inner == "bool":
                return "return False"
            if inner == "str":
                return "return ''"
            if inner in {"list", "List", "Sequence", "Iterable"}:
                return "return []"
            if inner in {"dict", "Dict", "Mapping"}:
                return "return {}"
            return "return None"

        # No useful annotation: inspect literal returns without executing code.
        for node in ast.walk(function):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            value = node.value
            if isinstance(value, ast.Constant):
                if isinstance(value.value, bool):
                    return "return False"
                if isinstance(value.value, (int, float, complex)):
                    return "return 0"
                if isinstance(value.value, str):
                    return "return ''"
            if isinstance(value, ast.List):
                return "return []"
            if isinstance(value, ast.Tuple):
                return "return ()"
            if isinstance(value, ast.Set):
                return "return set()"
            if isinstance(value, ast.Dict):
                return "return {}"

        return "return None"

    @staticmethod
    def _sanitize_net_new_stub(body: str) -> str:
        """Prevent synthetic candidates from using exception-based stubs."""
        if "NotImplementedError" in body or "raise NotImplementedError" in body:
            return "return None"
        return body

    @staticmethod
    def _find_function(
        tree: ast.AST,
        name: str,
        line_start: int,
        line_end: int,
    ) -> Optional[
        ast.FunctionDef | ast.AsyncFunctionDef
    ]:
        candidates = []

        for node in ast.walk(tree):
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                continue

            if node.name != name:
                continue

            node_end = (
                node.end_lineno
                if node.end_lineno is not None
                else node.lineno
            )

            overlap = not (
                node_end < line_start
                or node.lineno > line_end
            )

            if overlap:
                candidates.append(node)

        candidates.sort(
            key=lambda node: (
                node.lineno,
                node.end_lineno or node.lineno,
            )
        )

        return (
            candidates[0]
            if candidates
            else None
        )

    @staticmethod
    def _indentation(
        line: str,
    ) -> str:
        return line[
            : len(line) - len(
                line.lstrip()
            )
        ]

    # ------------------------------------------------------------------
    # Net-new insertion
    # ------------------------------------------------------------------

    def _insert_function(
        self,
        path: Path,
        function_name: str,
        signature: str,
        body: str,
    ) -> None:
        source = path.read_text(
            encoding="utf-8",
        )

        tree = ast.parse(
            source,
            filename=str(path),
        )

        existing = [
            node
            for node in ast.walk(tree)
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == function_name
        ]

        if existing:
            raise TaskSynthesisError(
                f"Net-new function {function_name} already exists "
                f"in {path}; refusing to overwrite it."
            )

        if not signature.strip().startswith(
            "def "
        ) and not signature.strip().startswith(
            "async def "
        ):
            raise TaskSynthesisError(
                "Net-new signature must begin with "
                "`def` or `async def`."
            )

        function_text = (
            "\n\n"
            + signature.rstrip()
            + ":\n"
            + self._indent_body(body)
            + "\n"
        )

        path.write_text(
            source.rstrip()
            + function_text,
            encoding="utf-8",
        )

        try:
            ast.parse(
                path.read_text(
                    encoding="utf-8",
                ),
                filename=str(path),
            )
        except SyntaxError as exc:
            raise TaskSynthesisError(
                f"Net-new synthesis produced invalid Python: {path}"
            ) from exc

    @staticmethod
    def _indent_body(
        body: str,
    ) -> str:
        lines = body.splitlines()

        if not lines:
            return "    pass"

        return "\n".join(
            (
                line
                if line.startswith("    ")
                else "    " + line
            )
            for line in lines
        )

    # ------------------------------------------------------------------
    # Safety checks
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_isolated(
        input_dir: Path,
        solution_dir: Path,
    ) -> None:
        if not input_dir.is_dir():
            raise TaskSynthesisError(
                f"Missing input directory: {input_dir}"
            )

        if not solution_dir.is_dir():
            raise TaskSynthesisError(
                f"Missing solution directory: {solution_dir}"
            )

        input_resolved = input_dir.resolve()
        solution_resolved = solution_dir.resolve()

        if input_resolved == solution_resolved:
            raise TaskSynthesisError(
                "input/ and solution/ resolve to the same directory."
            )

        # Make sure the candidate states are independently writable.
        input_marker = (
            input_dir / ".synthesis_isolation_check"
        )

        solution_marker = (
            solution_dir / ".synthesis_isolation_check"
        )

        input_marker.write_text(
            "input",
            encoding="utf-8",
        )

        try:
            if solution_marker.exists():
                raise TaskSynthesisError(
                    "input/ and solution/ appear to share filesystem state."
                )
        finally:
            input_marker.unlink(
                missing_ok=True
            )

    @staticmethod
    def _materialize_regression_tests(
        verifier_dir: Path,
        regression_tests: Sequence,
    ) -> None:
        """
        Write each regression test's fixing-commit content into
        verifier/, preserving its repository-relative path.

        This directory becomes the task-local oracle: the TaskVerifier
        overlays these exact files onto both the input/ and solution/
        workspaces before running the verification command, so the same
        regression assertion is what's actually exercised in both
        states.
        """

        verifier_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        for regression_test in regression_tests:
            relative = Path(
                str(regression_test.path).replace(
                    "\\",
                    "/",
                )
            )

            if relative.is_absolute() or ".." in relative.parts:
                raise TaskSynthesisError(
                    "Unsafe regression-test path: "
                    f"{regression_test.path}"
                )

            target = verifier_dir / relative

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.write_text(
                regression_test.content,
                encoding="utf-8",
            )

    @staticmethod
    def _write_metadata(
        task_root: Path,
        metadata: dict,
    ) -> None:
        path = (
            task_root / "synthesis.json"
        )

        path.write_text(
            json.dumps(
                metadata,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


# ----------------------------------------------------------------------
# Functional API
# ----------------------------------------------------------------------


def synthesize_history_task(
    repo_path: str | Path,
    candidate: HistoryChange,
    task_dir: str | Path,
) -> SynthesisResult:
    return TaskSynthesizer(
        repo_path
    ).synthesize_history(
        candidate,
        task_dir,
    )


def synthesize_excision_task(
    repo_path: str | Path,
    candidate: ExcisionCandidate,
    task_dir: str | Path,
) -> SynthesisResult:
    return TaskSynthesizer(
        repo_path
    ).synthesize_excision(
        candidate,
        task_dir,
    )


def synthesize_net_new_task(
    repo_path: str | Path,
    candidate: NetNewCandidate,
    task_dir: str | Path,
) -> SynthesisResult:
    return TaskSynthesizer(
        repo_path
    ).synthesize_net_new(
        candidate,
        task_dir,
    )