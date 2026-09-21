from __future__ import annotations

import hashlib
from zoneinfo import ZoneInfo

from aelia.contracts.actions import RiskClass
from aelia.contracts.events import InboundEvent
from aelia.models.autonomy import (
    AutonomyAuditRecord,
    AutonomyMode,
    AutonomyPolicyConfig,
    AutonomyRuntimeState,
    GuardrailCheck,
    GuardrailDecision,
    GuardrailOutcome,
    InitiativeProposal,
)

GUARDRAIL_POLICY_VERSION = "autonomy-guardrails-v1"


class AutonomyGuardrails:
    def evaluate(
        self,
        *,
        cycle_id: str,
        event: InboundEvent,
        proposal: InitiativeProposal,
        config: AutonomyPolicyConfig,
        runtime: AutonomyRuntimeState,
    ) -> tuple[GuardrailDecision, AutonomyAuditRecord]:
        confirmation_scope = f"confirm:{proposal.proposal_id}"
        confirmation_required = proposal.risk_class is RiskClass.HIGH or not proposal.reversible
        confirmation_granted = (
            not confirmation_required
            or confirmation_scope in event.permissions.scopes
            or "confirm_high_risk" in event.permissions.scopes
        )
        local_hour = event.occurred_at.astimezone(ZoneInfo(config.timezone)).hour
        quiet = config.quiet_hours_enabled and self._hour_in_window(
            local_hour,
            config.quiet_start_hour,
            config.quiet_end_hour,
        )
        permission_available = (
            event.permissions.can_send_message
            and proposal.required_permission in event.permissions.scopes
        )
        checks = (
            self._check(
                code="mode",
                passed=config.mode is AutonomyMode.SHADOW,
                observed=config.mode.value,
                limit=AutonomyMode.SHADOW.value,
                reason_code=(
                    "shadow_mode_enabled"
                    if config.mode is AutonomyMode.SHADOW
                    else "autonomy_disabled"
                ),
            ),
            self._check(
                code="actor_opt_out",
                passed=not runtime.actor_opted_out,
                observed=str(runtime.actor_opted_out).lower(),
                limit="false",
                reason_code=(
                    "actor_not_opted_out" if not runtime.actor_opted_out else "actor_opted_out"
                ),
            ),
            self._check(
                code="conversation_opt_out",
                passed=not runtime.conversation_opted_out,
                observed=str(runtime.conversation_opted_out).lower(),
                limit="false",
                reason_code=(
                    "conversation_not_opted_out"
                    if not runtime.conversation_opted_out
                    else "conversation_opted_out"
                ),
            ),
            self._check(
                code="quiet_hours",
                passed=not quiet,
                observed=f"local_hour:{local_hour}",
                limit=(
                    f"{config.quiet_start_hour:02d}:00-{config.quiet_end_hour:02d}:00"
                    if config.quiet_hours_enabled
                    else "disabled"
                ),
                reason_code="outside_quiet_hours" if not quiet else "inside_quiet_hours",
            ),
            self._check(
                code="permission",
                passed=permission_available,
                observed=proposal.required_permission,
                limit="explicit_scope_and_send_permission",
                reason_code=(
                    "proactive_permission_available"
                    if permission_available
                    else "proactive_permission_unavailable"
                ),
            ),
            self._check(
                code="privacy",
                passed=(
                    not proposal.privacy_sensitive
                    or "proactive_private" in event.permissions.scopes
                ),
                observed=str(proposal.privacy_sensitive).lower(),
                limit="proactive_private_scope_when_sensitive",
                reason_code=(
                    "privacy_scope_satisfied"
                    if (
                        not proposal.privacy_sensitive
                        or "proactive_private" in event.permissions.scopes
                    )
                    else "privacy_scope_missing"
                ),
            ),
            self._check(
                code="actor_rate_limit",
                passed=(runtime.actor_shadow_actions_last_hour < config.actor_limit_per_hour),
                observed=str(runtime.actor_shadow_actions_last_hour),
                limit=str(config.actor_limit_per_hour),
                reason_code=(
                    "actor_rate_available"
                    if runtime.actor_shadow_actions_last_hour < config.actor_limit_per_hour
                    else "actor_rate_limited"
                ),
            ),
            self._check(
                code="conversation_rate_limit",
                passed=(
                    runtime.conversation_shadow_actions_last_hour
                    < config.conversation_limit_per_hour
                ),
                observed=str(runtime.conversation_shadow_actions_last_hour),
                limit=str(config.conversation_limit_per_hour),
                reason_code=(
                    "conversation_rate_available"
                    if runtime.conversation_shadow_actions_last_hour
                    < config.conversation_limit_per_hour
                    else "conversation_rate_limited"
                ),
            ),
            self._check(
                code="cost_budget",
                passed=(
                    runtime.daily_shadow_cost_used + proposal.estimated_cost
                    <= config.daily_cost_budget
                ),
                observed=f"{runtime.daily_shadow_cost_used + proposal.estimated_cost:.6f}",
                limit=f"{config.daily_cost_budget:.6f}",
                reason_code=(
                    "cost_budget_available"
                    if runtime.daily_shadow_cost_used + proposal.estimated_cost
                    <= config.daily_cost_budget
                    else "cost_budget_exceeded"
                ),
            ),
            self._check(
                code="minimum_expected_value",
                passed=proposal.expected_value >= config.minimum_expected_value,
                observed=f"{proposal.expected_value:.6f}",
                limit=f"{config.minimum_expected_value:.6f}",
                reason_code=(
                    "minimum_value_met"
                    if proposal.expected_value >= config.minimum_expected_value
                    else "minimum_value_not_met"
                ),
            ),
            self._check(
                code="confirmation",
                passed=confirmation_granted,
                observed=str(confirmation_granted).lower(),
                limit=(confirmation_scope if confirmation_required else "not_required"),
                reason_code=(
                    "confirmation_satisfied" if confirmation_granted else "confirmation_required"
                ),
            ),
        )
        blocking_failures = [
            check for check in checks if not check.passed and check.code != "confirmation"
        ]
        if blocking_failures:
            outcome = GuardrailOutcome.BLOCKED
        elif not confirmation_granted:
            outcome = GuardrailOutcome.REQUIRE_CONFIRMATION
        else:
            outcome = GuardrailOutcome.SHADOW_APPROVED
        reason_codes = tuple(
            dict.fromkeys(
                (
                    f"guardrail:{outcome.value}",
                    *(check.reason_code for check in checks if not check.passed),
                    "no_proactive_action_materialized",
                )
            )
        )
        decision_id = self._id("guardrail", proposal.proposal_id)
        decision = GuardrailDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            outcome=outcome,
            checks=checks,
            reason_codes=reason_codes,
            confirmation_scope=confirmation_scope if confirmation_required else None,
            policy_version=GUARDRAIL_POLICY_VERSION,
            evaluated_at=event.occurred_at,
        )
        audit = AutonomyAuditRecord(
            audit_id=self._id("autonomy-audit", decision_id),
            cycle_id=cycle_id,
            source_event_id=event.event_id,
            trigger_id=proposal.trigger_id,
            proposal_id=proposal.proposal_id,
            decision_id=decision_id,
            target_actor_id=proposal.target_actor_id,
            target_conversation_id=proposal.target_conversation_id,
            outcome=outcome,
            estimated_cost=proposal.estimated_cost,
            proactive_action_materialized=False,
            reason_codes=reason_codes,
            recorded_at=event.occurred_at,
        )
        return decision, audit

    @staticmethod
    def _hour_in_window(hour: int, start: int, end: int) -> bool:
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    @staticmethod
    def _check(
        *,
        code: str,
        passed: bool,
        observed: str,
        limit: str | None,
        reason_code: str,
    ) -> GuardrailCheck:
        return GuardrailCheck(
            code=code,
            passed=passed,
            observed=observed,
            limit=limit,
            reason_code=reason_code,
        )

    @staticmethod
    def _id(namespace: str, material: str) -> str:
        digest = hashlib.sha256(material.encode()).hexdigest()[:24]
        return f"{namespace}:{digest}"
