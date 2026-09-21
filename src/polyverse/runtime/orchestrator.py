from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from polyverse.autonomy.guardrails import AutonomyGuardrails
from polyverse.autonomy.initiative import (
    INITIATIVE_POLICY_VERSION,
    InitiativeManager,
    InternalTriggerPolicy,
)
from polyverse.cognition.action_policy import ActionPolicy, TurnTakingPolicy
from polyverse.cognition.appraisal import AppraisalPolicy
from polyverse.cognition.attention import AttentionPolicy
from polyverse.cognition.beliefs import BeliefPolicy
from polyverse.cognition.conversation import ConversationPolicy
from polyverse.cognition.deliberation import RuleBasedDeliberation
from polyverse.cognition.dynamics import (
    InternalDynamicsPolicy,
    InternalParticipationPolicy,
)
from polyverse.cognition.goals import GoalManager
from polyverse.cognition.memory import (
    LearningPolicy,
    MemoryPolicy,
    MemoryRetrievalPolicy,
    OutcomePolicy,
)
from polyverse.cognition.participation import ParticipationPolicy
from polyverse.cognition.perception import PerceptionPolicy
from polyverse.cognition.social import SocialPolicy
from polyverse.cognition.world import WorldModelPolicy
from polyverse.contracts.actions import (
    CURRENT_ACTION_SCHEMA_VERSION,
    ActionTarget,
    ActionType,
    CandidateActionType,
    ExecutionResult,
    ExecutionStatus,
    LanguageGenerationStatus,
    OutboundAction,
    RiskClass,
    TurnTakingOutcome,
)
from polyverse.contracts.common import utc_now
from polyverse.contracts.events import InboundEvent
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.contracts.participation import ParticipationOutcome
from polyverse.contracts.traces import (
    CURRENT_TRACE_SCHEMA_VERSION,
    CycleError,
    CycleRetry,
    CycleStatus,
    CycleTrace,
    FoundationDecision,
)
from polyverse.models.autonomy import (
    AutonomyEvaluation,
    AutonomyPolicyConfig,
    AutonomyRuntimeState,
    GuardrailOutcome,
)
from polyverse.models.belief import BeliefSnapshot
from polyverse.models.cognition import InternalState
from polyverse.models.goals import Goal
from polyverse.models.memory import MemoryRetrievalResult
from polyverse.models.self_model import SelfModel, SelfModelBuilder
from polyverse.models.social import SocialState
from polyverse.persona.disclosure import DisclosureGate
from polyverse.persona.models import PersonaSpecification
from polyverse.persona.participation import PersonaParticipationPolicy
from polyverse.persona.selector import PersonaViewSelector
from polyverse.runtime.ports import (
    ExecutionPort,
    LanguageGeneratorPort,
    LanguagePort,
    MockExecutionPort,
    MockLanguageGenerator,
    MockLanguagePort,
)
from polyverse.storage.repositories import ConcurrentStateError, KernelRepository

FOUNDATION_ORCHESTRATOR_VERSION = "v2-001"
FOUNDATION_POLICY_VERSION = "foundation-observe-v1"
OBSERVATION_ORCHESTRATOR_VERSION = "v2-002"
PERSONA_ORCHESTRATOR_VERSION = "v2-003"
COGNITIVE_ORCHESTRATOR_VERSION = "v2-004"
ACTION_ORCHESTRATOR_VERSION = "v2-005"
MEMORY_ORCHESTRATOR_VERSION = "v2-006"
AUTONOMY_ORCHESTRATOR_VERSION = "v2-010"


def _with_retry_history(
    trace: CycleTrace,
    retry_history: tuple[CycleRetry, ...],
) -> CycleTrace:
    if not retry_history:
        return trace
    return CycleTrace.model_validate(
        {
            **trace.model_dump(mode="python"),
            "retries": retry_history,
        }
    )


def _concurrent_state_retry(
    attempt: int,
    error: ConcurrentStateError,
) -> CycleRetry:
    return CycleRetry(
        attempt=attempt,
        component="state_commit",
        code="concurrent_state_conflict",
        message=str(error),
    )


def _execution_cycle_state(
    execution: ExecutionResult | None,
) -> tuple[CycleStatus, tuple[CycleError, ...]]:
    if execution is None or execution.status is not ExecutionStatus.FAILED:
        return CycleStatus.COMPLETED, ()
    return (
        CycleStatus.FAILED,
        (
            CycleError(
                code=execution.error_code or "execution_failed",
                message=execution.error_message or "Execution failed without an error message.",
                retryable=execution.retryable,
            ),
        ),
    )


@dataclass(frozen=True)
class ProcessResult:
    trace: CycleTrace
    duplicate: bool


class FoundationOrchestrator:
    """Minimal deterministic cycle used to prove ingest, trace, and replay."""

    def __init__(self, repository: KernelRepository) -> None:
        self.repository = repository

    async def initialize(self) -> None:
        await self.repository.initialize()

    async def process(self, event: InboundEvent) -> ProcessResult:
        started_at = utc_now()
        trace = self.transition(
            event=event,
            cycle_id=str(uuid4()),
            started_at=started_at,
            completed_at=utc_now(),
        )
        result = await self.repository.store_foundation_cycle(event, trace)
        return ProcessResult(trace=result.trace, duplicate=result.duplicate)

    @staticmethod
    def transition(
        event: InboundEvent,
        cycle_id: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> CycleTrace:
        """Pure foundation transition; all nondeterministic inputs are explicit."""

        return CycleTrace(
            schema_version=CURRENT_TRACE_SCHEMA_VERSION,
            cycle_id=cycle_id,
            event_id=event.event_id,
            orchestrator_version=FOUNDATION_ORCHESTRATOR_VERSION,
            started_at=started_at,
            completed_at=completed_at,
            status=CycleStatus.COMPLETED,
            state_version_before=0,
            state_version_after=0,
            decision=FoundationDecision(
                outcome="observe",
                reason_codes=("foundation_policy_not_enabled",),
                policy_version=FOUNDATION_POLICY_VERSION,
                confidence=1.0,
            ),
        )


class ObservationOrchestrator:
    """Deterministic observation and participation vertical slice."""

    def __init__(
        self,
        repository: KernelRepository,
        *,
        agent_actor_id: str,
        language_port: LanguagePort | None = None,
        execution_port: ExecutionPort | None = None,
        max_state_retries: int = 3,
    ) -> None:
        if not agent_actor_id.strip():
            raise ValueError("agent_actor_id must not be blank")
        if max_state_retries < 1:
            raise ValueError("max_state_retries must be positive")
        self.repository = repository
        self.agent_actor_id = agent_actor_id
        self.language_port = language_port or MockLanguagePort()
        self.execution_port = execution_port or MockExecutionPort()
        self.max_state_retries = max_state_retries

    async def initialize(self) -> None:
        await self.repository.initialize()

    async def process(self, event: InboundEvent) -> ProcessResult:
        last_conflict: ConcurrentStateError | None = None
        retry_history: tuple[CycleRetry, ...] = ()
        for attempt in range(1, self.max_state_retries + 1):
            observation = await self.repository.load_observation_snapshot(
                event.conversation_id,
                self.agent_actor_id,
            )
            started_at = utc_now()
            trace = self.transition(
                event=event,
                observation=observation,
                cycle_id=str(uuid4()),
                started_at=started_at,
                completed_at=utc_now(),
                language_port=self.language_port,
                execution_port=self.execution_port,
            )
            trace = _with_retry_history(trace, retry_history)
            try:
                result = await self.repository.store_observation_cycle(event, trace)
            except ConcurrentStateError as exc:
                last_conflict = exc
                retry_history = (
                    *retry_history,
                    _concurrent_state_retry(attempt, exc),
                )
                continue
            return ProcessResult(trace=result.trace, duplicate=result.duplicate)
        if last_conflict is None:
            raise RuntimeError("observation cycle exhausted retries without a state conflict")
        raise last_conflict

    @staticmethod
    def transition(
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        cycle_id: str,
        started_at: datetime,
        completed_at: datetime,
        language_port: LanguagePort,
        execution_port: ExecutionPort,
    ) -> CycleTrace:
        """Pure transition except for injected, deterministic ports."""

        attention = AttentionPolicy().evaluate(event, observation)
        decision = ParticipationPolicy().decide(
            cycle_id=cycle_id,
            event=event,
            attention=attention,
            agent_actor_id=observation.agent_actor_id,
        )
        selected_action = None
        execution_result = None
        if decision.outcome is ParticipationOutcome.REPLY:
            content_plan = language_port.create_content_plan(event, decision)
            selected_action = OutboundAction(
                schema_version=CURRENT_ACTION_SCHEMA_VERSION,
                action_id=f"{cycle_id}:reply",
                cycle_id=cycle_id,
                action_type=ActionType.REPLY,
                target=ActionTarget(
                    conversation_id=event.conversation_id,
                    reply_to_event_id=event.event_id,
                ),
                content_plan=content_plan,
                permission_scope="send_message",
                idempotency_key=f"cycle:{cycle_id}:reply",
                risk_class=RiskClass.LOW,
                created_at=completed_at,
            )
            execution_result = execution_port.execute(selected_action)

        cycle_status, cycle_errors = _execution_cycle_state(execution_result)
        return CycleTrace(
            schema_version=CURRENT_TRACE_SCHEMA_VERSION,
            cycle_id=cycle_id,
            event_id=event.event_id,
            orchestrator_version=OBSERVATION_ORCHESTRATOR_VERSION,
            started_at=started_at,
            completed_at=completed_at,
            status=cycle_status,
            state_version_before=observation.state_version,
            state_version_after=observation.state_version + 1,
            attention=attention,
            observation=observation,
            decision=decision,
            selected_action=selected_action,
            execution_result=execution_result,
            errors=cycle_errors,
        )


class PersonaOrchestrator:
    """R3 cycle: immutable self, social inertia, persona view, and disclosure."""

    def __init__(
        self,
        repository: KernelRepository,
        *,
        agent_actor_id: str,
        persona_specification: PersonaSpecification,
        language_port: LanguagePort | None = None,
        execution_port: ExecutionPort | None = None,
        max_state_retries: int = 3,
    ) -> None:
        if not agent_actor_id.strip():
            raise ValueError("agent_actor_id must not be blank")
        if max_state_retries < 1:
            raise ValueError("max_state_retries must be positive")
        self.repository = repository
        self.agent_actor_id = agent_actor_id
        self.persona_specification = persona_specification
        self.self_model = SelfModelBuilder.build(persona_specification)
        self.language_port = language_port or MockLanguagePort()
        self.execution_port = execution_port or MockExecutionPort()
        self.max_state_retries = max_state_retries

    async def initialize(self) -> None:
        await self.repository.initialize()

    async def process(self, event: InboundEvent) -> ProcessResult:
        last_conflict: ConcurrentStateError | None = None
        retry_history: tuple[CycleRetry, ...] = ()
        for attempt in range(1, self.max_state_retries + 1):
            observation = await self.repository.load_observation_snapshot(
                event.conversation_id,
                self.agent_actor_id,
            )
            social_before = await self.repository.load_social_state(
                event.platform,
                event.actor_id,
            )
            started_at = utc_now()
            trace = self.transition(
                event=event,
                observation=observation,
                social_before=social_before,
                self_model=self.self_model,
                persona_specification=self.persona_specification,
                cycle_id=str(uuid4()),
                started_at=started_at,
                completed_at=utc_now(),
                language_port=self.language_port,
                execution_port=self.execution_port,
            )
            trace = _with_retry_history(trace, retry_history)
            try:
                result = await self.repository.store_observation_cycle(event, trace)
            except ConcurrentStateError as exc:
                last_conflict = exc
                retry_history = (
                    *retry_history,
                    _concurrent_state_retry(attempt, exc),
                )
                continue
            return ProcessResult(trace=result.trace, duplicate=result.duplicate)
        if last_conflict is None:
            raise RuntimeError("persona cycle exhausted retries without a state conflict")
        raise last_conflict

    @staticmethod
    def transition(
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        social_before: SocialState,
        self_model: SelfModel,
        persona_specification: PersonaSpecification,
        cycle_id: str,
        started_at: datetime,
        completed_at: datetime,
        language_port: LanguagePort,
        execution_port: ExecutionPort,
    ) -> CycleTrace:
        attention = AttentionPolicy().evaluate(event, observation)
        social_transition = SocialPolicy().transition(event, social_before)
        disclosure = DisclosureGate().evaluate(
            content=event.content,
            relationship_tier=social_before.tier,
        )
        persona_view = PersonaViewSelector().select(
            event=event,
            specification=persona_specification,
            relationship_tier=social_before.tier,
            disclosure=disclosure,
        )
        persona_influence = PersonaParticipationPolicy().evaluate(persona_view)
        decision = ParticipationPolicy().decide(
            cycle_id=cycle_id,
            event=event,
            attention=attention,
            agent_actor_id=observation.agent_actor_id,
            persona_preference_score=persona_influence.score,
            persona_reason_codes=(
                *persona_influence.reason_codes,
                *(f"persona_rule:{rule_id}" for rule_id in persona_influence.rule_ids),
            ),
        )

        selected_action = None
        execution_result = None
        if decision.outcome is ParticipationOutcome.REPLY:
            content_plan = language_port.create_content_plan(
                event,
                decision,
                persona_view=persona_view,
                disclosure=disclosure,
            )
            selected_action = OutboundAction(
                schema_version=CURRENT_ACTION_SCHEMA_VERSION,
                action_id=f"{cycle_id}:reply",
                cycle_id=cycle_id,
                action_type=ActionType.REPLY,
                target=ActionTarget(
                    conversation_id=event.conversation_id,
                    reply_to_event_id=event.event_id,
                ),
                content_plan=content_plan,
                permission_scope="send_message",
                idempotency_key=f"cycle:{cycle_id}:reply",
                risk_class=RiskClass.LOW,
                created_at=completed_at,
            )
            execution_result = execution_port.execute(selected_action)

        cycle_status, cycle_errors = _execution_cycle_state(execution_result)
        return CycleTrace(
            schema_version=CURRENT_TRACE_SCHEMA_VERSION,
            cycle_id=cycle_id,
            event_id=event.event_id,
            orchestrator_version=PERSONA_ORCHESTRATOR_VERSION,
            started_at=started_at,
            completed_at=completed_at,
            status=cycle_status,
            state_version_before=observation.state_version,
            state_version_after=observation.state_version + 1,
            attention=attention,
            observation=observation,
            self_model=self_model,
            social_transition=social_transition,
            persona_view=persona_view,
            disclosure=disclosure,
            decision=decision,
            selected_action=selected_action,
            execution_result=execution_result,
            errors=cycle_errors,
        )


class CognitiveOrchestrator:
    """C4 cycle with explicit epistemic, appraisal, drive, and affect state."""

    def __init__(
        self,
        repository: KernelRepository,
        *,
        agent_actor_id: str,
        persona_specification: PersonaSpecification,
        language_port: LanguagePort | None = None,
        execution_port: ExecutionPort | None = None,
        max_state_retries: int = 3,
    ) -> None:
        if not agent_actor_id.strip():
            raise ValueError("agent_actor_id must not be blank")
        if max_state_retries < 1:
            raise ValueError("max_state_retries must be positive")
        self.repository = repository
        self.agent_actor_id = agent_actor_id
        self.persona_specification = persona_specification
        self.self_model = SelfModelBuilder.build(persona_specification)
        self.internal_state_id = f"persona:{persona_specification.persona_id}"
        self.language_port = language_port or MockLanguagePort()
        self.execution_port = execution_port or MockExecutionPort()
        self.max_state_retries = max_state_retries

    async def initialize(self) -> None:
        await self.repository.initialize()

    async def process(self, event: InboundEvent) -> ProcessResult:
        last_conflict: ConcurrentStateError | None = None
        retry_history: tuple[CycleRetry, ...] = ()
        for attempt in range(1, self.max_state_retries + 1):
            observation = await self.repository.load_observation_snapshot(
                event.conversation_id,
                self.agent_actor_id,
            )
            social_before = await self.repository.load_social_state(
                event.platform,
                event.actor_id,
            )
            belief_before = await self.repository.load_belief_snapshot(
                event.platform,
                event.actor_id,
            )
            internal_before = await self.repository.load_internal_state(self.internal_state_id)
            started_at = utc_now()
            trace = self.transition(
                event=event,
                observation=observation,
                social_before=social_before,
                belief_before=belief_before,
                internal_before=internal_before,
                self_model=self.self_model,
                persona_specification=self.persona_specification,
                cycle_id=str(uuid4()),
                started_at=started_at,
                completed_at=utc_now(),
                language_port=self.language_port,
                execution_port=self.execution_port,
            )
            trace = _with_retry_history(trace, retry_history)
            try:
                result = await self.repository.store_observation_cycle(event, trace)
            except ConcurrentStateError as exc:
                last_conflict = exc
                retry_history = (
                    *retry_history,
                    _concurrent_state_retry(attempt, exc),
                )
                continue
            return ProcessResult(trace=result.trace, duplicate=result.duplicate)
        if last_conflict is None:
            raise RuntimeError("cognitive cycle exhausted retries without a state conflict")
        raise last_conflict

    @staticmethod
    def transition(
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        social_before: SocialState,
        belief_before: BeliefSnapshot,
        internal_before: InternalState,
        self_model: SelfModel,
        persona_specification: PersonaSpecification,
        cycle_id: str,
        started_at: datetime,
        completed_at: datetime,
        language_port: LanguagePort,
        execution_port: ExecutionPort,
    ) -> CycleTrace:
        attention = AttentionPolicy().evaluate(
            event,
            observation,
            internal=internal_before,
        )
        perception = PerceptionPolicy().perceive(event=event, attention=attention)
        belief_transition = BeliefPolicy().transition(
            event=event,
            perception=perception,
            before=belief_before,
        )
        world_model = WorldModelPolicy().project(
            event=event,
            perception=perception,
            beliefs=belief_transition,
        )
        social_transition = SocialPolicy().transition(event, social_before)
        disclosure = DisclosureGate().evaluate(
            content=event.content,
            relationship_tier=social_before.tier,
        )
        persona_view = PersonaViewSelector().select(
            event=event,
            specification=persona_specification,
            relationship_tier=social_before.tier,
            disclosure=disclosure,
        )
        appraisal = AppraisalPolicy().appraise(
            event=event,
            observation=observation,
            perception=perception,
            social=social_transition.after,
            persona_view=persona_view,
            disclosure=disclosure,
            world=world_model,
        )
        internal_transition = InternalDynamicsPolicy().transition(
            event=event,
            before=internal_before,
            perception=perception,
            appraisal=appraisal,
            social=social_transition,
        )
        persona_influence = PersonaParticipationPolicy().evaluate(persona_view)
        internal_influence = InternalParticipationPolicy().evaluate(internal_transition.after)
        decision = ParticipationPolicy().decide(
            cycle_id=cycle_id,
            event=event,
            attention=attention,
            agent_actor_id=observation.agent_actor_id,
            persona_preference_score=persona_influence.score,
            persona_reason_codes=(
                *persona_influence.reason_codes,
                *(f"persona_rule:{rule_id}" for rule_id in persona_influence.rule_ids),
            ),
            internal_dynamics_score=internal_influence.score,
            internal_reason_codes=internal_influence.reason_codes,
        )

        selected_action = None
        execution_result = None
        if decision.outcome is ParticipationOutcome.REPLY:
            content_plan = language_port.create_content_plan(
                event,
                decision,
                persona_view=persona_view,
                disclosure=disclosure,
            )
            selected_action = OutboundAction(
                schema_version=CURRENT_ACTION_SCHEMA_VERSION,
                action_id=f"{cycle_id}:reply",
                cycle_id=cycle_id,
                action_type=ActionType.REPLY,
                target=ActionTarget(
                    conversation_id=event.conversation_id,
                    reply_to_event_id=event.event_id,
                ),
                content_plan=content_plan,
                permission_scope="send_message",
                idempotency_key=f"cycle:{cycle_id}:reply",
                risk_class=RiskClass.LOW,
                created_at=completed_at,
            )
            execution_result = execution_port.execute(selected_action)

        cycle_status, cycle_errors = _execution_cycle_state(execution_result)
        return CycleTrace(
            schema_version=CURRENT_TRACE_SCHEMA_VERSION,
            cycle_id=cycle_id,
            event_id=event.event_id,
            orchestrator_version=COGNITIVE_ORCHESTRATOR_VERSION,
            started_at=started_at,
            completed_at=completed_at,
            status=cycle_status,
            state_version_before=observation.state_version,
            state_version_after=observation.state_version + 1,
            attention=attention,
            observation=observation,
            self_model=self_model,
            social_transition=social_transition,
            persona_view=persona_view,
            disclosure=disclosure,
            perception=perception,
            belief_transition=belief_transition,
            world_model=world_model,
            appraisal=appraisal,
            internal_transition=internal_transition,
            decision=decision,
            selected_action=selected_action,
            execution_result=execution_result,
            errors=cycle_errors,
        )


class ActionOrchestrator:
    """A5 cycle with goals, candidates, explainable selection, and execution."""

    def __init__(
        self,
        repository: KernelRepository,
        *,
        agent_actor_id: str,
        persona_specification: PersonaSpecification,
        language_port: LanguagePort | None = None,
        language_generator: LanguageGeneratorPort | None = None,
        execution_port: ExecutionPort | None = None,
        max_state_retries: int = 3,
    ) -> None:
        if not agent_actor_id.strip():
            raise ValueError("agent_actor_id must not be blank")
        if max_state_retries < 1:
            raise ValueError("max_state_retries must be positive")
        self.repository = repository
        self.agent_actor_id = agent_actor_id
        self.persona_specification = persona_specification
        self.self_model = SelfModelBuilder.build(persona_specification)
        self.internal_state_id = f"persona:{persona_specification.persona_id}"
        self.language_port = language_port or MockLanguagePort()
        self.language_generator = language_generator or MockLanguageGenerator()
        self.execution_port = execution_port or MockExecutionPort()
        self.max_state_retries = max_state_retries

    async def initialize(self) -> None:
        await self.repository.initialize()

    async def process(self, event: InboundEvent) -> ProcessResult:
        last_conflict: ConcurrentStateError | None = None
        retry_history: tuple[CycleRetry, ...] = ()
        for attempt in range(1, self.max_state_retries + 1):
            observation = await self.repository.load_observation_snapshot(
                event.conversation_id,
                self.agent_actor_id,
            )
            social_before = await self.repository.load_social_state(
                event.platform,
                event.actor_id,
            )
            belief_before = await self.repository.load_belief_snapshot(
                event.platform,
                event.actor_id,
            )
            internal_before = await self.repository.load_internal_state(self.internal_state_id)
            goals_before = await self.repository.load_open_goals(
                self.persona_specification.persona_id
            )
            started_at = utc_now()
            trace = await self.transition(
                event=event,
                observation=observation,
                social_before=social_before,
                belief_before=belief_before,
                internal_before=internal_before,
                goals_before=goals_before,
                self_model=self.self_model,
                persona_specification=self.persona_specification,
                cycle_id=str(uuid4()),
                started_at=started_at,
                completed_at=utc_now(),
                language_port=self.language_port,
                language_generator=self.language_generator,
                execution_port=self.execution_port,
            )
            trace = _with_retry_history(trace, retry_history)
            try:
                result = await self.repository.store_observation_cycle(event, trace)
            except ConcurrentStateError as exc:
                last_conflict = exc
                retry_history = (
                    *retry_history,
                    _concurrent_state_retry(attempt, exc),
                )
                continue
            return ProcessResult(trace=result.trace, duplicate=result.duplicate)
        if last_conflict is None:
            raise RuntimeError("action cycle exhausted retries without a state conflict")
        raise last_conflict

    @staticmethod
    async def transition(
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        social_before: SocialState,
        belief_before: BeliefSnapshot,
        internal_before: InternalState,
        goals_before: tuple[Goal, ...],
        self_model: SelfModel,
        persona_specification: PersonaSpecification,
        cycle_id: str,
        started_at: datetime,
        completed_at: datetime,
        language_port: LanguagePort,
        language_generator: LanguageGeneratorPort,
        execution_port: ExecutionPort,
        memory_retrieval: MemoryRetrievalResult | None = None,
    ) -> CycleTrace:
        conversation_model = ConversationPolicy().project(
            event=event,
            observation=observation,
        )
        attention = AttentionPolicy().evaluate(
            event,
            observation,
            conversation=conversation_model,
            internal=internal_before,
        )
        perception = PerceptionPolicy().perceive(event=event, attention=attention)
        belief_transition = BeliefPolicy().transition(
            event=event,
            perception=perception,
            before=belief_before,
        )
        world_model = WorldModelPolicy().project(
            event=event,
            perception=perception,
            beliefs=belief_transition,
        )
        social_transition = SocialPolicy().transition(event, social_before)
        disclosure = DisclosureGate().evaluate(
            content=event.content,
            relationship_tier=social_before.tier,
        )
        persona_view = PersonaViewSelector().select(
            event=event,
            specification=persona_specification,
            relationship_tier=social_before.tier,
            disclosure=disclosure,
        )
        appraisal = AppraisalPolicy().appraise(
            event=event,
            observation=observation,
            perception=perception,
            social=social_transition.after,
            persona_view=persona_view,
            disclosure=disclosure,
            world=world_model,
        )
        internal_transition = InternalDynamicsPolicy().transition(
            event=event,
            before=internal_before,
            perception=perception,
            appraisal=appraisal,
            social=social_transition,
        )
        proposed_goals = GoalManager().propose(
            event=event,
            observation=observation,
            before=goals_before,
            owner=persona_specification.persona_id,
            internal=internal_transition.after,
        )
        persona_influence = PersonaParticipationPolicy().evaluate(persona_view)
        internal_influence = InternalParticipationPolicy().evaluate(internal_transition.after)
        decision = ParticipationPolicy().decide(
            cycle_id=cycle_id,
            event=event,
            attention=attention,
            agent_actor_id=observation.agent_actor_id,
            persona_preference_score=persona_influence.score,
            persona_reason_codes=(
                *persona_influence.reason_codes,
                *(f"persona_rule:{rule_id}" for rule_id in persona_influence.rule_ids),
            ),
            internal_dynamics_score=internal_influence.score,
            internal_reason_codes=internal_influence.reason_codes,
            conversation=conversation_model,
        )
        deliberation = RuleBasedDeliberation().deliberate(
            event=event,
            participation=decision,
            goals=proposed_goals,
            appraisal=appraisal,
            internal=internal_transition.after,
            disclosure=disclosure,
        )
        action_selection = ActionPolicy().select(
            event=event,
            deliberation=deliberation,
            memory_retrieval=memory_retrieval,
        )
        candidate = ActionPolicy.selected_candidate(deliberation, action_selection)
        turn_taking = TurnTakingPolicy().decide(
            event=event,
            observation=observation,
            candidate=candidate,
            conversation=conversation_model,
            internal=internal_transition.after,
        )
        effective_action_type = candidate.action_type if candidate is not None else None
        if turn_taking.outcome is TurnTakingOutcome.WAIT:
            effective_action_type = CandidateActionType.WAIT
        selected_action = None
        language_generation = None
        execution_result = None
        if (
            candidate is not None
            and candidate.action_type in {CandidateActionType.REPLY, CandidateActionType.JOIN}
            and turn_taking.outcome is TurnTakingOutcome.SPEAK_NOW
            and decision.outcome in {ParticipationOutcome.REPLY, ParticipationOutcome.JOIN}
        ):
            content_plan = language_port.create_content_plan(
                event,
                decision,
                persona_view=persona_view,
                disclosure=disclosure,
            )
            outbound_action_type = (
                ActionType.JOIN
                if candidate.action_type is CandidateActionType.JOIN
                else ActionType.REPLY
            )
            selected_action = OutboundAction(
                schema_version=CURRENT_ACTION_SCHEMA_VERSION,
                action_id=f"action:{event.event_id}:{outbound_action_type.value}",
                cycle_id=cycle_id,
                action_type=outbound_action_type,
                target=candidate.target,
                content_plan=content_plan,
                permission_scope=candidate.required_permission or "send_message",
                idempotency_key=f"event:{event.event_id}:{outbound_action_type.value}",
                risk_class=(
                    RiskClass.HIGH
                    if candidate.risk >= 0.7
                    else RiskClass.MEDIUM
                    if candidate.risk >= 0.3
                    else RiskClass.LOW
                ),
                created_at=completed_at,
            )
            language_generation = await language_generator.generate(
                selected_action,
                event=event,
                persona_view=persona_view,
            )
            if language_generation.status is LanguageGenerationStatus.FAILED:
                execution_result = ExecutionResult(
                    action_id=selected_action.action_id,
                    status=ExecutionStatus.FAILED,
                    executor="language-generation-gate-v1",
                    side_effect_performed=False,
                    error_code=language_generation.error_code,
                    error_message="Language generation failed before action execution.",
                    retryable=language_generation.retryable,
                )
            else:
                execution_result = execution_port.execute(selected_action)
        goal_transition = GoalManager().resolve(
            transition=proposed_goals,
            selection=action_selection,
            selected_action_type=effective_action_type,
            occurred_at=completed_at,
            execution=execution_result,
        )

        cycle_status, cycle_errors = _execution_cycle_state(execution_result)
        return CycleTrace(
            schema_version=CURRENT_TRACE_SCHEMA_VERSION,
            cycle_id=cycle_id,
            event_id=event.event_id,
            orchestrator_version=ACTION_ORCHESTRATOR_VERSION,
            started_at=started_at,
            completed_at=completed_at,
            status=cycle_status,
            state_version_before=observation.state_version,
            state_version_after=observation.state_version + 1,
            attention=attention,
            observation=observation,
            conversation_model=conversation_model,
            self_model=self_model,
            social_transition=social_transition,
            persona_view=persona_view,
            disclosure=disclosure,
            perception=perception,
            belief_transition=belief_transition,
            world_model=world_model,
            appraisal=appraisal,
            internal_transition=internal_transition,
            goal_transition=goal_transition,
            deliberation=deliberation,
            action_selection=action_selection,
            turn_taking=turn_taking,
            decision=decision,
            selected_action=selected_action,
            language_generation=language_generation,
            execution_result=execution_result,
            errors=cycle_errors,
        )


class MemoryOrchestrator(ActionOrchestrator):
    """M6 cycle with canonical memory references and validation-gated learning."""

    async def process(self, event: InboundEvent) -> ProcessResult:
        last_conflict: ConcurrentStateError | None = None
        memory_policy = MemoryPolicy()
        retry_history: tuple[CycleRetry, ...] = ()
        for attempt in range(1, self.max_state_retries + 1):
            observation = await self.repository.load_observation_snapshot(
                event.conversation_id,
                self.agent_actor_id,
            )
            social_before = await self.repository.load_social_state(
                event.platform,
                event.actor_id,
            )
            belief_before = await self.repository.load_belief_snapshot(
                event.platform,
                event.actor_id,
            )
            internal_before = await self.repository.load_internal_state(self.internal_state_id)
            goals_before = await self.repository.load_open_goals(
                self.persona_specification.persona_id
            )
            memory_query = memory_policy.build_query(
                event=event,
                self_model=self.self_model,
                internal=internal_before,
            )
            persisted_candidates = await self.repository.load_memory_candidates(memory_query)
            working_candidates = memory_policy.derive_working_records(
                observation=observation,
                event=event,
            )
            candidates_by_id = {
                memory.memory_id: memory for memory in (*persisted_candidates, *working_candidates)
            }
            memory_retrieval = MemoryRetrievalPolicy().retrieve(
                query=memory_query,
                candidates=tuple(candidates_by_id.values()),
                event=event,
            )
            started_at = utc_now()
            trace = await self.transition(
                event=event,
                observation=observation,
                social_before=social_before,
                belief_before=belief_before,
                internal_before=internal_before,
                goals_before=goals_before,
                memory_retrieval=memory_retrieval,
                self_model=self.self_model,
                persona_specification=self.persona_specification,
                cycle_id=str(uuid4()),
                started_at=started_at,
                completed_at=utc_now(),
                language_port=self.language_port,
                language_generator=self.language_generator,
                execution_port=self.execution_port,
            )
            trace = _with_retry_history(trace, retry_history)
            try:
                result = await self.repository.store_observation_cycle(event, trace)
            except ConcurrentStateError as exc:
                last_conflict = exc
                retry_history = (
                    *retry_history,
                    _concurrent_state_retry(attempt, exc),
                )
                continue
            return ProcessResult(trace=result.trace, duplicate=result.duplicate)
        if last_conflict is None:
            raise RuntimeError("memory cycle exhausted retries without a state conflict")
        raise last_conflict

    @staticmethod
    async def transition(
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        social_before: SocialState,
        belief_before: BeliefSnapshot,
        internal_before: InternalState,
        goals_before: tuple[Goal, ...],
        memory_retrieval: MemoryRetrievalResult | None = None,
        self_model: SelfModel,
        persona_specification: PersonaSpecification,
        cycle_id: str,
        started_at: datetime,
        completed_at: datetime,
        language_port: LanguagePort,
        language_generator: LanguageGeneratorPort,
        execution_port: ExecutionPort,
    ) -> CycleTrace:
        if memory_retrieval is None:
            raise ValueError("memory orchestrator requires a recorded retrieval result")
        action_trace = await ActionOrchestrator.transition(
            event=event,
            observation=observation,
            social_before=social_before,
            belief_before=belief_before,
            internal_before=internal_before,
            goals_before=goals_before,
            self_model=self_model,
            persona_specification=persona_specification,
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            language_port=language_port,
            language_generator=language_generator,
            execution_port=execution_port,
            memory_retrieval=memory_retrieval,
        )
        if (
            action_trace.social_transition is None
            or action_trace.belief_transition is None
            or action_trace.internal_transition is None
            or action_trace.goal_transition is None
        ):
            raise RuntimeError("action trace is missing required M6 state transitions")
        memory_write_set = MemoryPolicy().build_write_set(
            event=event,
            self_model=self_model,
            social=action_trace.social_transition,
            beliefs=action_trace.belief_transition,
            goals=action_trace.goal_transition,
        )
        outcome = OutcomePolicy().evaluate(
            cycle_id=cycle_id,
            event=event,
            selected_action=action_trace.selected_action,
            execution=action_trace.execution_result,
            goals=action_trace.goal_transition,
            social=action_trace.social_transition,
            internal=action_trace.internal_transition,
        )
        learning_proposals, reflection_triggers = LearningPolicy().propose(
            event=event,
            outcome=outcome,
            beliefs=action_trace.belief_transition,
            social=action_trace.social_transition,
            internal=action_trace.internal_transition,
        )
        return CycleTrace.model_validate(
            {
                **action_trace.model_dump(mode="python"),
                "orchestrator_version": MEMORY_ORCHESTRATOR_VERSION,
                "memory_retrieval": memory_retrieval,
                "memory_write_set": memory_write_set,
                "outcome_evaluation": outcome,
                "learning_proposals": learning_proposals,
                "reflection_triggers": reflection_triggers,
            }
        )


class AutonomyOrchestrator:
    """U7 cycle: internal triggers and guardrailed shadow-only initiatives."""

    def __init__(
        self,
        repository: KernelRepository,
        *,
        agent_actor_id: str,
        persona_specification: PersonaSpecification,
        autonomy_config: AutonomyPolicyConfig,
        language_port: LanguagePort | None = None,
        language_generator: LanguageGeneratorPort | None = None,
        execution_port: ExecutionPort | None = None,
        max_state_retries: int = 3,
    ) -> None:
        if not agent_actor_id.strip():
            raise ValueError("agent_actor_id must not be blank")
        if max_state_retries < 1:
            raise ValueError("max_state_retries must be positive")
        self.repository = repository
        self.agent_actor_id = agent_actor_id
        self.persona_specification = persona_specification
        self.self_model = SelfModelBuilder.build(persona_specification)
        self.internal_state_id = f"persona:{persona_specification.persona_id}"
        self.language_port = language_port or MockLanguagePort()
        self.language_generator = language_generator or MockLanguageGenerator()
        self.execution_port = execution_port or MockExecutionPort()
        self.max_state_retries = max_state_retries
        self.autonomy_config = autonomy_config

    async def initialize(self) -> None:
        await self.repository.initialize()

    async def process(self, event: InboundEvent) -> ProcessResult:
        last_conflict: ConcurrentStateError | None = None
        memory_policy = MemoryPolicy()
        retry_history: tuple[CycleRetry, ...] = ()
        for attempt in range(1, self.max_state_retries + 1):
            observation = await self.repository.load_observation_snapshot(
                event.conversation_id,
                self.agent_actor_id,
            )
            social_before = await self.repository.load_social_state(
                event.platform,
                event.actor_id,
            )
            belief_before = await self.repository.load_belief_snapshot(
                event.platform,
                event.actor_id,
            )
            internal_before = await self.repository.load_internal_state(self.internal_state_id)
            goals_before = await self.repository.load_open_goals(
                self.persona_specification.persona_id
            )
            memory_query = memory_policy.build_query(
                event=event,
                self_model=self.self_model,
                internal=internal_before,
            )
            persisted_candidates = await self.repository.load_memory_candidates(memory_query)
            working_candidates = memory_policy.derive_working_records(
                observation=observation,
                event=event,
            )
            candidates_by_id = {
                memory.memory_id: memory for memory in (*persisted_candidates, *working_candidates)
            }
            memory_retrieval = MemoryRetrievalPolicy().retrieve(
                query=memory_query,
                candidates=tuple(candidates_by_id.values()),
                event=event,
            )
            local_time = event.occurred_at.astimezone(ZoneInfo(self.autonomy_config.timezone))
            local_day_start = local_time.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            autonomy_runtime = await self.repository.load_autonomy_runtime_state(
                actor_id=event.actor_id,
                conversation_id=event.conversation_id,
                hour_window_start=event.occurred_at - timedelta(hours=1),
                day_window_start=local_day_start.astimezone(UTC),
            )
            started_at = utc_now()
            trace = await self.transition(
                event=event,
                observation=observation,
                social_before=social_before,
                belief_before=belief_before,
                internal_before=internal_before,
                goals_before=goals_before,
                memory_retrieval=memory_retrieval,
                autonomy_config=self.autonomy_config,
                autonomy_runtime=autonomy_runtime,
                self_model=self.self_model,
                persona_specification=self.persona_specification,
                cycle_id=str(uuid4()),
                started_at=started_at,
                completed_at=utc_now(),
                language_port=self.language_port,
                language_generator=self.language_generator,
                execution_port=self.execution_port,
            )
            trace = _with_retry_history(trace, retry_history)
            try:
                result = await self.repository.store_observation_cycle(event, trace)
            except ConcurrentStateError as exc:
                last_conflict = exc
                retry_history = (
                    *retry_history,
                    _concurrent_state_retry(attempt, exc),
                )
                continue
            return ProcessResult(trace=result.trace, duplicate=result.duplicate)
        if last_conflict is None:
            raise RuntimeError("autonomy cycle exhausted retries without a state conflict")
        raise last_conflict

    @staticmethod
    async def transition(
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        social_before: SocialState,
        belief_before: BeliefSnapshot,
        internal_before: InternalState,
        goals_before: tuple[Goal, ...],
        memory_retrieval: MemoryRetrievalResult | None = None,
        autonomy_config: AutonomyPolicyConfig,
        autonomy_runtime: AutonomyRuntimeState,
        self_model: SelfModel,
        persona_specification: PersonaSpecification,
        cycle_id: str,
        started_at: datetime,
        completed_at: datetime,
        language_port: LanguagePort,
        language_generator: LanguageGeneratorPort,
        execution_port: ExecutionPort,
    ) -> CycleTrace:
        if memory_retrieval is None:
            raise ValueError("autonomy orchestrator requires a memory retrieval result")
        memory_trace = await MemoryOrchestrator.transition(
            event=event,
            observation=observation,
            social_before=social_before,
            belief_before=belief_before,
            internal_before=internal_before,
            goals_before=goals_before,
            memory_retrieval=memory_retrieval,
            self_model=self_model,
            persona_specification=persona_specification,
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            language_port=language_port,
            language_generator=language_generator,
            execution_port=execution_port,
        )
        if (
            memory_trace.goal_transition is None
            or memory_trace.internal_transition is None
            or memory_trace.outcome_evaluation is None
        ):
            raise RuntimeError("memory trace is missing required U7 state")
        triggers = InternalTriggerPolicy().detect(
            event=event,
            goals=memory_trace.goal_transition,
            internal=memory_trace.internal_transition,
            outcome=memory_trace.outcome_evaluation,
            high_drive_threshold=autonomy_config.high_drive_threshold,
        )
        proposals = InitiativeManager().propose(event=event, triggers=triggers)
        guardrails = AutonomyGuardrails()
        decisions = []
        audits = []
        running_runtime = autonomy_runtime
        for proposal in proposals:
            decision, audit = guardrails.evaluate(
                cycle_id=cycle_id,
                event=event,
                proposal=proposal,
                config=autonomy_config,
                runtime=running_runtime,
            )
            decisions.append(decision)
            audits.append(audit)
            if decision.outcome is GuardrailOutcome.SHADOW_APPROVED:
                running_runtime = AutonomyRuntimeState.model_validate(
                    {
                        **running_runtime.model_dump(mode="python"),
                        "actor_shadow_actions_last_hour": (
                            running_runtime.actor_shadow_actions_last_hour + 1
                        ),
                        "conversation_shadow_actions_last_hour": (
                            running_runtime.conversation_shadow_actions_last_hour + 1
                        ),
                        "daily_shadow_cost_used": round(
                            running_runtime.daily_shadow_cost_used + proposal.estimated_cost,
                            6,
                        ),
                    }
                )
        autonomy = AutonomyEvaluation(
            policy_version=INITIATIVE_POLICY_VERSION,
            config=autonomy_config,
            runtime_state=autonomy_runtime,
            triggers=triggers,
            proposals=proposals,
            decisions=tuple(decisions),
            audit_records=tuple(audits),
            proactive_action_materialized=False,
        )
        return CycleTrace.model_validate(
            {
                **memory_trace.model_dump(mode="python"),
                "orchestrator_version": AUTONOMY_ORCHESTRATOR_VERSION,
                "autonomy_evaluation": autonomy,
            }
        )
