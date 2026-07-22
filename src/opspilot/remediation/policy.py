from __future__ import annotations

from pydantic import ValidationError

from opspilot.domain.enums import ActionRisk
from opspilot.remediation.models import (
    ActionProposal,
    RestartServiceParameters,
    RollbackDeploymentParameters,
)


class ActionPolicyError(ValueError):
    pass


class ActionPolicy:
    allowed_environments = {"demo", "staging"}

    def validate(self, proposal: ActionProposal) -> tuple[ActionRisk, dict]:
        if proposal.target_environment not in self.allowed_environments:
            raise ActionPolicyError(
                f"remediation is not allowed in {proposal.target_environment} environment"
            )
        try:
            if proposal.action_type == "restart_service":
                parameters = RestartServiceParameters.model_validate(proposal.parameters)
                return ActionRisk.LOW, parameters.model_dump()
            if proposal.action_type == "rollback_deployment":
                parameters = RollbackDeploymentParameters.model_validate(proposal.parameters)
                return ActionRisk.MEDIUM, parameters.model_dump()
        except ValidationError as exc:
            raise ActionPolicyError(
                f"invalid {proposal.action_type} parameters: {exc.errors(include_url=False)}"
            ) from exc
        raise ActionPolicyError(f"action type {proposal.action_type} is not allowlisted")
