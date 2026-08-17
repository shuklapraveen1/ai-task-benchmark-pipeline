from dataclasses import dataclass, field
from typing import List

from pipeline.discover import RepoContext
from pipeline.lint_format import LintFormatInfo


@dataclass
class HygieneProposal:
    """
    Policy-level hygiene proposal.

    This layer decides what should happen.
    It does not execute commands or modify the repository.
    """

    tool: str
    action: str
    confidence: str
    reason: str
    changes: List[str] = field(default_factory=list)


def propose_hygiene(
    info: LintFormatInfo,
    context: RepoContext,
) -> HygieneProposal:
    """
    Convert lint/format discovery into a safe mutation proposal.

    Policy:

    - Preserve an explicitly detected existing convention.
    - For an existing Ruff convention, request a Ruff autofix pass.
    - Ruff may use unsafe fixes when necessary to resolve legacy
      violations that have no safe automatic fix.
    - Never introduce Ruff when another existing convention is present.
    - If no convention exists, propose Ruff as the default.
    - Never execute commands or modify repository files.
    """

    # Context is intentionally accepted as part of the contract.
    # Future policies can use ecosystem/repository information.
    del context

    # ---------------------------------------------------------------
    # Existing convention
    # ---------------------------------------------------------------

    if info.tools:
        tool = info.tools[0]

        if tool.name.lower() == "ruff":
            return HygieneProposal(
                tool="ruff",
                action="preserve_existing",
                confidence="high",
                reason=(
                    "Existing Ruff convention was detected; "
                    "preserve the repository's existing tooling."
                ),
                changes=[],
            )

        return HygieneProposal(
            tool=tool.name,
            action="preserve_existing",
            confidence="high",
            reason=(
                f"Existing {tool.name} convention was detected; "
                "preserve the repository's existing tooling."
            ),
            changes=[],
        )

    # ---------------------------------------------------------------
    # No existing convention
    # ---------------------------------------------------------------

    if info.default_standard_proposed:
        return HygieneProposal(
            tool="ruff",
            action="introduce_default",
            confidence="medium",
            reason=(
                "No existing linting or formatting convention was "
                "detected; Ruff is proposed as the default standard."
            ),
            changes=[
                "add Ruff configuration",
                "format Python source with Ruff",
                "lint Python source with Ruff",
            ],
        )

    # ---------------------------------------------------------------
    # No safe proposal
    # ---------------------------------------------------------------

    return HygieneProposal(
        tool="none",
        action="no_change",
        confidence="low",
        reason=(
            "No safe linting or formatting proposal could be derived "
            "from repository discovery."
        ),
        changes=[],
    )