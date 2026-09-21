from __future__ import annotations

from aelia.contracts.common import StrictModel
from aelia.models.self_model import SelfModelBuilder
from aelia.persona.models import PersonaSpecification
from aelia.runtime.orchestrator import (
    ACTION_ORCHESTRATOR_VERSION,
    AUTONOMY_ORCHESTRATOR_VERSION,
    COGNITIVE_ORCHESTRATOR_VERSION,
    FOUNDATION_ORCHESTRATOR_VERSION,
    MEMORY_ORCHESTRATOR_VERSION,
    OBSERVATION_ORCHESTRATOR_VERSION,
    PERSONA_ORCHESTRATOR_VERSION,
    ActionOrchestrator,
    AutonomyOrchestrator,
    CognitiveOrchestrator,
    FoundationOrchestrator,
    MemoryOrchestrator,
    ObservationOrchestrator,
    PersonaOrchestrator,
)
from aelia.runtime.ports import (
    MockExecutionPort,
    MockLanguageGenerator,
    MockLanguagePort,
    RecordedExecutionPort,
    RecordedLanguageGenerator,
)
from aelia.storage.repositories import KernelRepository, canonical_json, sha256_text


class ReplayResult(StrictModel):
    cycle_id: str
    event_id: str
    matched: bool
    expected_sha256: str
    actual_sha256: str


class ReplayService:
    def __init__(
        self,
        repository: KernelRepository,
        *,
        persona_specification: PersonaSpecification | None = None,
    ) -> None:
        self.repository = repository
        self.persona_specification = persona_specification

    async def replay_cycle(self, cycle_id: str) -> ReplayResult:
        expected = await self.repository.get_cycle(cycle_id)
        event = await self.repository.get_event(expected.event_id)
        if expected.orchestrator_version == FOUNDATION_ORCHESTRATOR_VERSION:
            actual = FoundationOrchestrator.transition(
                event=event,
                cycle_id=expected.cycle_id,
                started_at=expected.started_at,
                completed_at=expected.completed_at,
            )
        elif expected.orchestrator_version == OBSERVATION_ORCHESTRATOR_VERSION:
            if expected.observation is None:
                raise RuntimeError("observation trace is missing its replay snapshot")
            actual = ObservationOrchestrator.transition(
                event=event,
                observation=expected.observation,
                cycle_id=expected.cycle_id,
                started_at=expected.started_at,
                completed_at=expected.completed_at,
                language_port=MockLanguagePort(),
                execution_port=MockExecutionPort(),
            )
        elif expected.orchestrator_version == PERSONA_ORCHESTRATOR_VERSION:
            if expected.observation is None or expected.social_transition is None:
                raise RuntimeError("persona trace is missing replay state")
            if self.persona_specification is None:
                raise RuntimeError("persona specification is required to replay v2-003")
            actual = PersonaOrchestrator.transition(
                event=event,
                observation=expected.observation,
                social_before=expected.social_transition.before,
                self_model=SelfModelBuilder.build(self.persona_specification),
                persona_specification=self.persona_specification,
                cycle_id=expected.cycle_id,
                started_at=expected.started_at,
                completed_at=expected.completed_at,
                language_port=MockLanguagePort(),
                execution_port=MockExecutionPort(),
            )
        elif expected.orchestrator_version == COGNITIVE_ORCHESTRATOR_VERSION:
            if (
                expected.observation is None
                or expected.social_transition is None
                or expected.belief_transition is None
                or expected.internal_transition is None
            ):
                raise RuntimeError("cognitive trace is missing replay state")
            if self.persona_specification is None:
                raise RuntimeError("persona specification is required to replay v2-004")
            actual = CognitiveOrchestrator.transition(
                event=event,
                observation=expected.observation,
                social_before=expected.social_transition.before,
                belief_before=expected.belief_transition.before,
                internal_before=expected.internal_transition.before,
                self_model=SelfModelBuilder.build(self.persona_specification),
                persona_specification=self.persona_specification,
                cycle_id=expected.cycle_id,
                started_at=expected.started_at,
                completed_at=expected.completed_at,
                language_port=MockLanguagePort(),
                execution_port=MockExecutionPort(),
            )
        elif expected.orchestrator_version == ACTION_ORCHESTRATOR_VERSION:
            if (
                expected.observation is None
                or expected.social_transition is None
                or expected.belief_transition is None
                or expected.internal_transition is None
                or expected.goal_transition is None
            ):
                raise RuntimeError("action trace is missing replay state")
            if self.persona_specification is None:
                raise RuntimeError("persona specification is required to replay v2-005")
            language_generator = (
                RecordedLanguageGenerator(expected.language_generation)
                if expected.language_generation is not None
                else MockLanguageGenerator()
            )
            execution_port = (
                RecordedExecutionPort(expected.execution_result)
                if expected.execution_result is not None
                else MockExecutionPort()
            )
            actual = await ActionOrchestrator.transition(
                event=event,
                observation=expected.observation,
                social_before=expected.social_transition.before,
                belief_before=expected.belief_transition.before,
                internal_before=expected.internal_transition.before,
                goals_before=expected.goal_transition.before,
                self_model=SelfModelBuilder.build(self.persona_specification),
                persona_specification=self.persona_specification,
                cycle_id=expected.cycle_id,
                started_at=expected.started_at,
                completed_at=expected.completed_at,
                language_port=MockLanguagePort(),
                language_generator=language_generator,
                execution_port=execution_port,
            )
        elif expected.orchestrator_version == MEMORY_ORCHESTRATOR_VERSION:
            if (
                expected.observation is None
                or expected.social_transition is None
                or expected.belief_transition is None
                or expected.internal_transition is None
                or expected.goal_transition is None
                or expected.memory_retrieval is None
            ):
                raise RuntimeError("memory trace is missing replay state")
            if self.persona_specification is None:
                raise RuntimeError("persona specification is required to replay v2-006")
            language_generator = (
                RecordedLanguageGenerator(expected.language_generation)
                if expected.language_generation is not None
                else MockLanguageGenerator()
            )
            execution_port = (
                RecordedExecutionPort(expected.execution_result)
                if expected.execution_result is not None
                else MockExecutionPort()
            )
            actual = await MemoryOrchestrator.transition(
                event=event,
                observation=expected.observation,
                social_before=expected.social_transition.before,
                belief_before=expected.belief_transition.before,
                internal_before=expected.internal_transition.before,
                goals_before=expected.goal_transition.before,
                memory_retrieval=expected.memory_retrieval,
                self_model=SelfModelBuilder.build(self.persona_specification),
                persona_specification=self.persona_specification,
                cycle_id=expected.cycle_id,
                started_at=expected.started_at,
                completed_at=expected.completed_at,
                language_port=MockLanguagePort(),
                language_generator=language_generator,
                execution_port=execution_port,
            )
        elif expected.orchestrator_version in {
            "v2-008",
            "v2-009",
            AUTONOMY_ORCHESTRATOR_VERSION,
        }:
            if (
                expected.observation is None
                or expected.social_transition is None
                or expected.belief_transition is None
                or expected.internal_transition is None
                or expected.goal_transition is None
                or expected.memory_retrieval is None
                or expected.autonomy_evaluation is None
            ):
                raise RuntimeError("autonomy trace is missing replay state")
            if self.persona_specification is None:
                raise RuntimeError("persona specification is required to replay v2-010")
            language_generator = (
                RecordedLanguageGenerator(expected.language_generation)
                if expected.language_generation is not None
                else MockLanguageGenerator()
            )
            execution_port = (
                RecordedExecutionPort(expected.execution_result)
                if expected.execution_result is not None
                else MockExecutionPort()
            )
            actual = await AutonomyOrchestrator.transition(
                event=event,
                observation=expected.observation,
                social_before=expected.social_transition.before,
                belief_before=expected.belief_transition.before,
                internal_before=expected.internal_transition.before,
                goals_before=expected.goal_transition.before,
                memory_retrieval=expected.memory_retrieval,
                autonomy_config=expected.autonomy_evaluation.config,
                autonomy_runtime=expected.autonomy_evaluation.runtime_state,
                self_model=SelfModelBuilder.build(self.persona_specification),
                persona_specification=self.persona_specification,
                cycle_id=expected.cycle_id,
                started_at=expected.started_at,
                completed_at=expected.completed_at,
                language_port=MockLanguagePort(),
                language_generator=language_generator,
                execution_port=execution_port,
            )
        else:
            raise RuntimeError(f"unsupported orchestrator version: {expected.orchestrator_version}")
        has_legacy_action = (
            expected.selected_action is not None
            and expected.selected_action.schema_version == "2.1.0"
        )
        if (
            actual.schema_version != expected.schema_version
            or actual.orchestrator_version != expected.orchestrator_version
            or expected.retries
            or has_legacy_action
        ):
            compatibility_fields: dict[str, object] = {}
            if expected.schema_version == "2.1.0":
                compatibility_fields = {
                    "status": expected.status,
                    "errors": expected.errors,
                }
            if has_legacy_action:
                compatibility_fields["selected_action"] = expected.selected_action
            actual = type(actual).model_validate(
                {
                    **actual.model_dump(mode="python"),
                    "schema_version": expected.schema_version,
                    "orchestrator_version": expected.orchestrator_version,
                    "retries": expected.retries,
                    **compatibility_fields,
                }
            )
        expected_hash = sha256_text(canonical_json(expected.model_dump(mode="json")))
        actual_hash = sha256_text(canonical_json(actual.model_dump(mode="json")))
        return ReplayResult(
            cycle_id=cycle_id,
            event_id=event.event_id,
            matched=expected_hash == actual_hash,
            expected_sha256=expected_hash,
            actual_sha256=actual_hash,
        )
