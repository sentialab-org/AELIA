from __future__ import annotations

from typing import Protocol

from aelia.contracts.actions import (
    ContentPlan,
    ExecutionResult,
    ExecutionStatus,
    LanguageGenerationResult,
    LanguageGenerationStatus,
    OutboundAction,
)
from aelia.contracts.events import InboundEvent
from aelia.contracts.participation import ParticipationDecision
from aelia.llm.prompts import LANGUAGE_REALIZATION_PROMPT_ID, PromptRegistry
from aelia.persona.models import DisclosureEvaluation, PersonaView


class LanguagePort(Protocol):
    def create_content_plan(
        self,
        event: InboundEvent,
        decision: ParticipationDecision,
        *,
        persona_view: PersonaView | None = None,
        disclosure: DisclosureEvaluation | None = None,
    ) -> ContentPlan: ...


class ExecutionPort(Protocol):
    def execute(self, action: OutboundAction) -> ExecutionResult: ...


class LanguageGeneratorPort(Protocol):
    async def generate(
        self,
        action: OutboundAction,
        *,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> LanguageGenerationResult: ...


class MockLanguagePort:
    """Deterministic planning boundary; it never calls a model or emits prose."""

    def create_content_plan(
        self,
        event: InboundEvent,
        decision: ParticipationDecision,
        *,
        persona_view: PersonaView | None = None,
        disclosure: DisclosureEvaluation | None = None,
    ) -> ContentPlan:
        style_constraints = (
            tuple(f"style_rule:{rule.rule_id}" for rule in persona_view.style_rules)
            if persona_view is not None
            else ()
        )
        identity_constraints = (
            tuple(f"identity_rule:{rule.rule_id}" for rule in persona_view.identity_rules)
            if persona_view is not None
            else ()
        )
        presentation_constraints = (
            tuple(f"presentation_rule:{rule.rule_id}" for rule in persona_view.presentation_rules)
            if persona_view is not None
            else ()
        )
        disclosure_constraints = (
            (
                f"disclosure_decision:{disclosure.decision.value}",
                f"disclosure_ceiling:{disclosure.allowed_ceiling.value}",
            )
            if disclosure is not None
            else ()
        )
        disclosure_prohibitions = (
            ("disclosure_above_selected_ceiling",) if disclosure is not None else ()
        )
        intent = (
            "join_open_group_question"
            if decision.outcome.value == "join"
            else "respond_to_directly_relevant_message"
        )
        constraints = (
            "brief",
            "natural_dialogue",
            f"source_event:{event.event_id}",
            f"decision:{decision.outcome.value}",
            *disclosure_constraints,
            *identity_constraints,
            *style_constraints,
            *presentation_constraints,
        )
        prohibited_traits = (
            "generic_assistant_voice",
            "unrequested_long_explanation",
            *disclosure_prohibitions,
        )
        prompt = PromptRegistry().compose(
            LANGUAGE_REALIZATION_PROMPT_ID,
            input_payload={
                "intent": intent,
                "constraints": constraints,
                "prohibited_traits": prohibited_traits,
            },
        )
        return ContentPlan(
            intent=intent,
            constraints=constraints,
            prohibited_traits=prohibited_traits,
            generator="mock-language-port-v1",
            prompt=prompt,
        )


class MockExecutionPort:
    """Records an execution-shaped result without performing an external side effect."""

    def execute(self, action: OutboundAction) -> ExecutionResult:
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.SIMULATED,
            executor="mock-execution-port-v1",
            side_effect_performed=False,
        )


class FailingExecutionPort:
    def execute(self, action: OutboundAction) -> ExecutionResult:
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="failing-execution-port-v1",
            side_effect_performed=False,
            error_code="simulated_execution_failure",
            error_message="The injected executor failed before any side effect.",
            retryable=True,
        )


class MockLanguageGenerator:
    """Consumes only the selected action; it cannot revisit participation or goals."""

    async def generate(
        self,
        action: OutboundAction,
        *,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> LanguageGenerationResult:
        return LanguageGenerationResult(
            action_id=action.action_id,
            generator="mock-language-generator-v1",
            status=LanguageGenerationStatus.SKIPPED,
            content=None,
            selected_action_type=action.action_type,
            applied_constraints=action.content_plan.constraints,
            changed_participation=False,
            provider="mock",
            attempts=0,
        )


class FixedTextLanguageGenerator:
    """Explicit test-canary generator; content is supplied by the operator."""

    def __init__(self, content: str) -> None:
        normalized = content.strip()
        if not normalized:
            raise ValueError("fixed test content must not be blank")
        if len(normalized) > 10_000:
            raise ValueError("fixed test content exceeds 10000 characters")
        self.content = normalized

    async def generate(
        self,
        action: OutboundAction,
        *,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> LanguageGenerationResult:
        return LanguageGenerationResult(
            action_id=action.action_id,
            generator="fixed-test-language-generator-v1",
            status=LanguageGenerationStatus.GENERATED,
            content=self.content,
            selected_action_type=action.action_type,
            applied_constraints=action.content_plan.constraints,
            changed_participation=False,
            provider="fixed_test",
            attempts=1,
        )


class RecordedExecutionPort:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result

    def execute(self, action: OutboundAction) -> ExecutionResult:
        if action.action_id != self.result.action_id:
            raise ValueError("recorded execution result belongs to a different action")
        return self.result


class RecordedLanguageGenerator:
    def __init__(self, result: LanguageGenerationResult) -> None:
        self.result = result

    async def generate(
        self,
        action: OutboundAction,
        *,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> LanguageGenerationResult:
        if action.action_id != self.result.action_id:
            raise ValueError("recorded language result belongs to a different action")
        return self.result
