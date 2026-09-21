from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from polyverse.contracts.common import StrictModel
from polyverse.contracts.events import ChannelType, InboundEvent, Platform
from polyverse.contracts.observation import (
    ConversationMessage,
    ObservationSnapshot,
    RecentParticipation,
)
from polyverse.contracts.participation import ParticipationDecision, ParticipationOutcome
from polyverse.contracts.traces import CycleTrace
from polyverse.models.autonomy import (
    AutonomyRuntimeState,
    GuardrailOutcome,
    OptOutScope,
)
from polyverse.models.belief import BeliefRecord, BeliefSnapshot
from polyverse.models.cognition import InternalState
from polyverse.models.goals import Goal
from polyverse.models.memory import MemoryQuery, MemoryRecord
from polyverse.models.social import SocialState
from polyverse.storage.database import Database


class EventConflictError(RuntimeError):
    """Raised when an existing event id is reused with a different payload."""


class RecordNotFoundError(LookupError):
    """Raised when a requested event or cycle does not exist."""


class ConcurrentStateError(RuntimeError):
    """Raised when an optimistic conversation-state write loses a race."""


@dataclass(frozen=True)
class FoundationIngestResult:
    trace: CycleTrace
    duplicate: bool


class KernelRepository(Protocol):
    async def initialize(self) -> None: ...

    async def store_foundation_cycle(
        self, event: InboundEvent, trace: CycleTrace
    ) -> FoundationIngestResult: ...

    async def load_observation_snapshot(
        self,
        conversation_id: str,
        agent_actor_id: str,
    ) -> ObservationSnapshot: ...

    async def store_observation_cycle(
        self,
        event: InboundEvent,
        trace: CycleTrace,
    ) -> FoundationIngestResult: ...

    async def load_social_state(
        self,
        platform: Platform,
        actor_id: str,
    ) -> SocialState: ...

    async def load_belief_snapshot(
        self,
        platform: Platform,
        actor_id: str,
    ) -> BeliefSnapshot: ...

    async def load_internal_state(self, state_id: str) -> InternalState: ...

    async def load_open_goals(self, owner: str) -> tuple[Goal, ...]: ...

    async def load_memory_candidates(
        self,
        query: MemoryQuery,
    ) -> tuple[MemoryRecord, ...]: ...

    async def load_autonomy_runtime_state(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        hour_window_start: datetime,
        day_window_start: datetime,
    ) -> AutonomyRuntimeState: ...

    async def set_autonomy_opt_out(
        self,
        *,
        scope_type: OptOutScope,
        scope_id: str,
        opted_out: bool,
        source: str,
        updated_at: datetime,
    ) -> None: ...

    async def get_event(self, event_id: str) -> InboundEvent: ...

    async def get_cycle(self, cycle_id: str) -> CycleTrace: ...

    async def get_cycle_for_event(self, event_id: str) -> CycleTrace: ...


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SqliteKernelRepository:
    def __init__(
        self,
        database: Database,
        *,
        conversation_buffer_limit: int = 100,
        recent_participation_limit: int = 10,
    ) -> None:
        if conversation_buffer_limit < 1:
            raise ValueError("conversation_buffer_limit must be positive")
        if recent_participation_limit < 1:
            raise ValueError("recent_participation_limit must be positive")
        self.database = database
        self.conversation_buffer_limit = conversation_buffer_limit
        self.recent_participation_limit = recent_participation_limit

    async def initialize(self) -> None:
        await self.database.initialize()

    async def store_foundation_cycle(
        self, event: InboundEvent, trace: CycleTrace
    ) -> FoundationIngestResult:
        if trace.event_id != event.event_id:
            raise ValueError("trace event_id does not match inbound event")

        event_json = canonical_json(event.model_dump(mode="json"))
        event_hash = sha256_text(event_json)
        trace_json = canonical_json(trace.model_dump(mode="json"))
        trace_hash = sha256_text(trace_json)
        decision_json = canonical_json(trace.decision.model_dump(mode="json"))
        decision_hash = sha256_text(decision_json)

        async with self.database.connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    """
                    SELECT payload_sha256
                    FROM inbound_events
                    WHERE event_id = ?
                    """,
                    (event.event_id,),
                )
                existing_event = await cursor.fetchone()
                if existing_event is not None:
                    if str(existing_event["payload_sha256"]) != event_hash:
                        raise EventConflictError(
                            f"event_id {event.event_id!r} already exists with different payload"
                        )
                    cursor = await connection.execute(
                        "SELECT trace_json FROM cycles WHERE event_id = ?",
                        (event.event_id,),
                    )
                    existing_cycle = await cursor.fetchone()
                    if existing_cycle is None:
                        raise RuntimeError(
                            "inbound event exists without its required foundation cycle"
                        )
                    await connection.rollback()
                    return FoundationIngestResult(
                        trace=CycleTrace.model_validate_json(str(existing_cycle["trace_json"])),
                        duplicate=True,
                    )

                await connection.execute(
                    """
                    INSERT INTO inbound_events(
                        event_id,
                        schema_version,
                        platform,
                        conversation_id,
                        event_type,
                        occurred_at,
                        payload_json,
                        payload_sha256,
                        ingested_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.schema_version,
                        event.platform.value,
                        event.conversation_id,
                        event.event_type.value,
                        event.occurred_at.isoformat(),
                        event_json,
                        event_hash,
                        trace.started_at.isoformat(),
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO cycles(
                        cycle_id,
                        event_id,
                        schema_version,
                        status,
                        orchestrator_version,
                        started_at,
                        completed_at,
                        trace_json,
                        trace_sha256
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.cycle_id,
                        trace.event_id,
                        trace.schema_version,
                        trace.status.value,
                        trace.orchestrator_version,
                        trace.started_at.isoformat(),
                        trace.completed_at.isoformat(),
                        trace_json,
                        trace_hash,
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO processed_events(event_id, cycle_id, processed_at, outcome)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        trace.cycle_id,
                        trace.completed_at.isoformat(),
                        trace.decision.outcome,
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO cycle_artifacts(
                        cycle_id,
                        artifact_type,
                        artifact_version,
                        payload_json,
                        payload_sha256,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.cycle_id,
                        "foundation_decision",
                        trace.decision.policy_version,
                        decision_json,
                        decision_hash,
                        trace.completed_at.isoformat(),
                    ),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

        return FoundationIngestResult(trace=trace, duplicate=False)

    async def load_observation_snapshot(
        self,
        conversation_id: str,
        agent_actor_id: str,
    ) -> ObservationSnapshot:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT version FROM conversation_state WHERE conversation_id = ?",
                (conversation_id,),
            )
            state_row = await cursor.fetchone()
            state_version = int(state_row["version"]) if state_row is not None else 0

            cursor = await connection.execute(
                """
                SELECT
                    position,
                    event_id,
                    actor_id,
                    occurred_at,
                    channel_type,
                    content,
                    reply_to_event_id,
                    reply_to_actor_id,
                    mentions_json
                FROM conversation_buffer
                WHERE conversation_id = ?
                ORDER BY position DESC
                LIMIT ?
                """,
                (conversation_id, self.conversation_buffer_limit),
            )
            message_rows = tuple(reversed(tuple(await cursor.fetchall())))

            cursor = await connection.execute(
                """
                SELECT position, event_id, outcome
                FROM conversation_participation
                WHERE conversation_id = ?
                ORDER BY position DESC
                LIMIT ?
                """,
                (conversation_id, self.recent_participation_limit),
            )
            participation_rows = tuple(reversed(tuple(await cursor.fetchall())))

        recent_messages = tuple(
            ConversationMessage(
                position=int(row["position"]),
                event_id=str(row["event_id"]),
                actor_id=str(row["actor_id"]),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
                channel_type=ChannelType(str(row["channel_type"])),
                content=str(row["content"]) if row["content"] is not None else None,
                reply_to_event_id=(
                    str(row["reply_to_event_id"]) if row["reply_to_event_id"] is not None else None
                ),
                reply_to_actor_id=(
                    str(row["reply_to_actor_id"]) if row["reply_to_actor_id"] is not None else None
                ),
                mentions=self._decode_mentions(str(row["mentions_json"])),
            )
            for row in message_rows
        )
        recent_participation = tuple(
            RecentParticipation(
                position=int(row["position"]),
                event_id=str(row["event_id"]),
                outcome=ParticipationOutcome(str(row["outcome"])),
            )
            for row in participation_rows
        )
        return ObservationSnapshot(
            conversation_id=conversation_id,
            agent_actor_id=agent_actor_id,
            state_version=state_version,
            recent_messages=recent_messages,
            recent_participation=recent_participation,
        )

    async def load_social_state(
        self,
        platform: Platform,
        actor_id: str,
    ) -> SocialState:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT state_json
                FROM social_relationships
                WHERE platform = ? AND actor_id = ?
                """,
                (platform.value, actor_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return SocialState.unknown(platform, actor_id)
        return SocialState.model_validate_json(str(row["state_json"]))

    async def load_belief_snapshot(
        self,
        platform: Platform,
        actor_id: str,
    ) -> BeliefSnapshot:
        scope_id = f"{platform.value}:{actor_id}"
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT record_json
                FROM beliefs
                WHERE scope_id = ?
                ORDER BY belief_id
                """,
                (scope_id,),
            )
            rows = tuple(await cursor.fetchall())
        return BeliefSnapshot(
            scope_id=scope_id,
            records=tuple(
                BeliefRecord.model_validate_json(str(row["record_json"])) for row in rows
            ),
        )

    async def load_internal_state(self, state_id: str) -> InternalState:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT state_json FROM internal_states WHERE state_id = ?",
                (state_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return InternalState.initial(state_id)
        return InternalState.model_validate_json(str(row["state_json"]))

    async def load_open_goals(self, owner: str) -> tuple[Goal, ...]:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT goal_json
                FROM goals
                WHERE owner = ? AND status IN ('active', 'paused')
                ORDER BY priority DESC, urgency DESC, goal_id
                """,
                (owner,),
            )
            rows = tuple(await cursor.fetchall())
        return tuple(Goal.model_validate_json(str(row["goal_json"])) for row in rows)

    async def load_memory_candidates(
        self,
        query: MemoryQuery,
    ) -> tuple[MemoryRecord, ...]:
        scope_placeholders = ",".join("?" for _ in query.scope_ids)
        category_placeholders = ",".join("?" for _ in query.categories)
        parameters = (
            *query.scope_ids,
            *(category.value for category in query.categories),
            query.limit * 10,
        )
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                f"""
                SELECT record_json
                FROM memory_records
                WHERE scope_id IN ({scope_placeholders})
                  AND category IN ({category_placeholders})
                ORDER BY importance DESC, updated_at DESC, memory_id
                LIMIT ?
                """,
                parameters,
            )
            rows = tuple(await cursor.fetchall())
        return tuple(MemoryRecord.model_validate_json(str(row["record_json"])) for row in rows)

    async def load_autonomy_runtime_state(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        hour_window_start: datetime,
        day_window_start: datetime,
    ) -> AutonomyRuntimeState:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT scope_type, scope_id, opted_out
                FROM autonomy_opt_outs
                WHERE (scope_type = 'actor' AND scope_id = ?)
                   OR (scope_type = 'conversation' AND scope_id = ?)
                """,
                (actor_id, conversation_id),
            )
            preference_rows = tuple(await cursor.fetchall())
            cursor = await connection.execute(
                """
                SELECT
                    audit_id,
                    target_actor_id,
                    target_conversation_id,
                    outcome,
                    estimated_cost,
                    recorded_at
                FROM autonomy_audit_log
                WHERE (
                    (
                        target_actor_id = ?
                        OR target_conversation_id = ?
                    )
                    AND recorded_at >= ?
                )
                OR (
                    outcome = ?
                    AND recorded_at >= ?
                )
                ORDER BY recorded_at, audit_id
                """,
                (
                    actor_id,
                    conversation_id,
                    hour_window_start.isoformat(),
                    GuardrailOutcome.SHADOW_APPROVED.value,
                    day_window_start.isoformat(),
                ),
            )
            audit_rows = tuple(await cursor.fetchall())

        preferences = {
            (str(row["scope_type"]), str(row["scope_id"])): bool(row["opted_out"])
            for row in preference_rows
        }
        counted_outcome = GuardrailOutcome.SHADOW_APPROVED.value
        hour_start = hour_window_start.isoformat()
        day_start = day_window_start.isoformat()
        actor_count = sum(
            str(row["target_actor_id"]) == actor_id
            and str(row["outcome"]) == counted_outcome
            and str(row["recorded_at"]) >= hour_start
            for row in audit_rows
        )
        conversation_count = sum(
            str(row["target_conversation_id"]) == conversation_id
            and str(row["outcome"]) == counted_outcome
            and str(row["recorded_at"]) >= hour_start
            for row in audit_rows
        )
        daily_cost = sum(
            float(row["estimated_cost"])
            for row in audit_rows
            if str(row["outcome"]) == counted_outcome and str(row["recorded_at"]) >= day_start
        )
        return AutonomyRuntimeState(
            actor_id=actor_id,
            conversation_id=conversation_id,
            actor_opted_out=preferences.get(
                (OptOutScope.ACTOR.value, actor_id),
                False,
            ),
            conversation_opted_out=preferences.get(
                (OptOutScope.CONVERSATION.value, conversation_id),
                False,
            ),
            actor_shadow_actions_last_hour=actor_count,
            conversation_shadow_actions_last_hour=conversation_count,
            daily_shadow_cost_used=round(daily_cost, 6),
            evidence_audit_ids=tuple(str(row["audit_id"]) for row in audit_rows),
        )

    async def set_autonomy_opt_out(
        self,
        *,
        scope_type: OptOutScope,
        scope_id: str,
        opted_out: bool,
        source: str,
        updated_at: datetime,
    ) -> None:
        if not scope_id.strip() or scope_id != scope_id.strip():
            raise ValueError("autonomy opt-out scope_id must be canonical")
        if not source.strip():
            raise ValueError("autonomy opt-out source must not be blank")
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError("autonomy opt-out timestamp must include a timezone")
        async with self.database.connection() as connection:
            await connection.execute(
                """
                INSERT INTO autonomy_opt_outs(
                    scope_type,
                    scope_id,
                    opted_out,
                    source,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope_type, scope_id) DO UPDATE SET
                    opted_out = excluded.opted_out,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    scope_type.value,
                    scope_id,
                    int(opted_out),
                    source,
                    updated_at.isoformat(),
                ),
            )
            await connection.commit()

    async def store_observation_cycle(
        self,
        event: InboundEvent,
        trace: CycleTrace,
    ) -> FoundationIngestResult:
        if trace.event_id != event.event_id:
            raise ValueError("trace event_id does not match inbound event")
        if not isinstance(trace.decision, ParticipationDecision):
            raise ValueError("observation cycle requires a participation decision")
        if trace.observation is None or trace.attention is None:
            raise ValueError("observation cycle requires observation and attention artifacts")
        if trace.observation.conversation_id != event.conversation_id:
            raise ValueError("observation conversation_id does not match inbound event")

        event_json = canonical_json(event.model_dump(mode="json"))
        event_hash = sha256_text(event_json)
        trace_json = canonical_json(trace.model_dump(mode="json"))
        trace_hash = sha256_text(trace_json)

        artifacts: list[tuple[str, str, StrictModel]] = [
            ("observation", "1.0.0", trace.observation),
            ("attention", trace.attention.policy_version, trace.attention),
            ("participation", trace.decision.policy_version, trace.decision),
        ]
        if trace.conversation_model is not None:
            artifacts.append(
                (
                    "conversation_model",
                    trace.conversation_model.model_version,
                    trace.conversation_model,
                )
            )
        if trace.selected_action is not None:
            artifacts.append(
                ("selected_action", trace.selected_action.schema_version, trace.selected_action)
            )
        if trace.execution_result is not None:
            artifacts.append(
                ("execution_result", trace.execution_result.executor, trace.execution_result)
            )
        if trace.self_model is not None:
            artifacts.append(("self_model", trace.self_model.model_version, trace.self_model))
        if trace.social_transition is not None:
            artifacts.append(
                (
                    "social_transition",
                    trace.social_transition.delta.provenance.method,
                    trace.social_transition,
                )
            )
        if trace.persona_view is not None:
            artifacts.append(
                ("persona_view", trace.persona_view.selector_version, trace.persona_view)
            )
        if trace.disclosure is not None:
            artifacts.append(("disclosure", trace.disclosure.gate_version, trace.disclosure))
        if trace.perception is not None:
            artifacts.append(("perception", trace.perception.policy_version, trace.perception))
        if trace.belief_transition is not None:
            artifacts.append(
                (
                    "belief_transition",
                    trace.belief_transition.policy_version,
                    trace.belief_transition,
                )
            )
        if trace.world_model is not None:
            artifacts.append(("world_model", trace.world_model.model_version, trace.world_model))
        if trace.appraisal is not None:
            artifacts.append(("appraisal", trace.appraisal.policy_version, trace.appraisal))
        if trace.internal_transition is not None:
            artifacts.append(
                (
                    "internal_transition",
                    trace.internal_transition.policy_version,
                    trace.internal_transition,
                )
            )
        if trace.goal_transition is not None:
            artifacts.append(
                ("goal_transition", trace.goal_transition.policy_version, trace.goal_transition)
            )
        if trace.deliberation is not None:
            artifacts.append(
                ("deliberation", trace.deliberation.policy_version, trace.deliberation)
            )
        if trace.action_selection is not None:
            artifacts.append(
                (
                    "action_selection",
                    trace.action_selection.policy_version,
                    trace.action_selection,
                )
            )
        if trace.turn_taking is not None:
            artifacts.append(("turn_taking", trace.turn_taking.policy_version, trace.turn_taking))
        if trace.language_generation is not None:
            artifacts.append(
                (
                    "language_generation",
                    trace.language_generation.generator,
                    trace.language_generation,
                )
            )
        if trace.memory_retrieval is not None:
            artifacts.append(
                (
                    "memory_retrieval",
                    trace.memory_retrieval.policy_version,
                    trace.memory_retrieval,
                )
            )
        if trace.memory_write_set is not None:
            artifacts.append(
                (
                    "memory_write_set",
                    trace.memory_write_set.policy_version,
                    trace.memory_write_set,
                )
            )
        if trace.outcome_evaluation is not None:
            artifacts.append(
                (
                    "outcome_evaluation",
                    trace.outcome_evaluation.policy_version,
                    trace.outcome_evaluation,
                )
            )
        artifacts.extend(
            (
                f"learning_proposal:{proposal.proposal_id}",
                proposal.provenance.method,
                proposal,
            )
            for proposal in trace.learning_proposals
        )
        artifacts.extend(
            (
                f"reflection_trigger:{trigger.trigger_id}",
                trigger.trigger_type.value,
                trigger,
            )
            for trigger in trace.reflection_triggers
        )
        if trace.autonomy_evaluation is not None:
            artifacts.append(
                (
                    "autonomy_evaluation",
                    trace.autonomy_evaluation.policy_version,
                    trace.autonomy_evaluation,
                )
            )

        async with self.database.connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "SELECT payload_sha256 FROM inbound_events WHERE event_id = ?",
                    (event.event_id,),
                )
                existing_event = await cursor.fetchone()
                if existing_event is not None:
                    if str(existing_event["payload_sha256"]) != event_hash:
                        raise EventConflictError(
                            f"event_id {event.event_id!r} already exists with different payload"
                        )
                    cursor = await connection.execute(
                        "SELECT trace_json FROM cycles WHERE event_id = ?",
                        (event.event_id,),
                    )
                    existing_cycle = await cursor.fetchone()
                    if existing_cycle is None:
                        raise RuntimeError("inbound event exists without its required cycle")
                    await connection.rollback()
                    return FoundationIngestResult(
                        trace=CycleTrace.model_validate_json(str(existing_cycle["trace_json"])),
                        duplicate=True,
                    )

                cursor = await connection.execute(
                    "SELECT version FROM conversation_state WHERE conversation_id = ?",
                    (event.conversation_id,),
                )
                state_row = await cursor.fetchone()
                current_version = int(state_row["version"]) if state_row is not None else 0
                if current_version != trace.state_version_before:
                    raise ConcurrentStateError(
                        f"conversation {event.conversation_id!r} changed from "
                        f"version {trace.state_version_before} to {current_version}"
                    )
                if trace.social_transition is not None:
                    social_before = trace.social_transition.before
                    cursor = await connection.execute(
                        """
                        SELECT version
                        FROM social_relationships
                        WHERE relationship_id = ?
                        """,
                        (social_before.relationship_id,),
                    )
                    social_row = await cursor.fetchone()
                    current_social_version = (
                        int(social_row["version"]) if social_row is not None else 0
                    )
                    if current_social_version != social_before.version:
                        raise ConcurrentStateError(
                            f"relationship {social_before.relationship_id!r} changed from "
                            f"version {social_before.version} to {current_social_version}"
                        )
                if trace.internal_transition is not None:
                    internal_before = trace.internal_transition.before
                    cursor = await connection.execute(
                        "SELECT version FROM internal_states WHERE state_id = ?",
                        (internal_before.state_id,),
                    )
                    internal_row = await cursor.fetchone()
                    current_internal_version = (
                        int(internal_row["version"]) if internal_row is not None else 0
                    )
                    if current_internal_version != internal_before.version:
                        raise ConcurrentStateError(
                            f"internal state {internal_before.state_id!r} changed from "
                            f"version {internal_before.version} to {current_internal_version}"
                        )
                if trace.autonomy_evaluation is not None and trace.autonomy_evaluation.proposals:
                    autonomy = trace.autonomy_evaluation
                    runtime = autonomy.runtime_state
                    cursor = await connection.execute(
                        """
                        SELECT scope_type, scope_id, opted_out
                        FROM autonomy_opt_outs
                        WHERE (scope_type = 'actor' AND scope_id = ?)
                           OR (scope_type = 'conversation' AND scope_id = ?)
                        """,
                        (runtime.actor_id, runtime.conversation_id),
                    )
                    preference_rows = tuple(await cursor.fetchall())
                    preferences = {
                        (str(row["scope_type"]), str(row["scope_id"])): bool(row["opted_out"])
                        for row in preference_rows
                    }
                    actor_opted_out = preferences.get(
                        (OptOutScope.ACTOR.value, runtime.actor_id),
                        False,
                    )
                    conversation_opted_out = preferences.get(
                        (
                            OptOutScope.CONVERSATION.value,
                            runtime.conversation_id,
                        ),
                        False,
                    )
                    hour_start = event.occurred_at - timedelta(hours=1)
                    cursor = await connection.execute(
                        """
                        SELECT
                            COALESCE(SUM(
                                CASE WHEN target_actor_id = ? THEN 1 ELSE 0 END
                            ), 0) AS actor_count,
                            COALESCE(SUM(
                                CASE WHEN target_conversation_id = ? THEN 1 ELSE 0 END
                            ), 0) AS conversation_count
                        FROM autonomy_audit_log
                        WHERE outcome = ?
                          AND recorded_at >= ?
                          AND (
                              target_actor_id = ?
                              OR target_conversation_id = ?
                          )
                        """,
                        (
                            runtime.actor_id,
                            runtime.conversation_id,
                            GuardrailOutcome.SHADOW_APPROVED.value,
                            hour_start.isoformat(),
                            runtime.actor_id,
                            runtime.conversation_id,
                        ),
                    )
                    rate_row = await cursor.fetchone()
                    local_time = event.occurred_at.astimezone(ZoneInfo(autonomy.config.timezone))
                    day_start = local_time.replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    ).astimezone(UTC)
                    cursor = await connection.execute(
                        """
                        SELECT COALESCE(SUM(estimated_cost), 0.0) AS daily_cost
                        FROM autonomy_audit_log
                        WHERE outcome = ? AND recorded_at >= ?
                        """,
                        (
                            GuardrailOutcome.SHADOW_APPROVED.value,
                            day_start.isoformat(),
                        ),
                    )
                    cost_row = await cursor.fetchone()
                    if rate_row is None or cost_row is None:
                        raise RuntimeError("autonomy concurrency query returned no row")
                    current_actor_count = int(rate_row["actor_count"])
                    current_conversation_count = int(rate_row["conversation_count"])
                    current_daily_cost = round(float(cost_row["daily_cost"]), 6)
                    if (
                        actor_opted_out != runtime.actor_opted_out
                        or conversation_opted_out != runtime.conversation_opted_out
                        or current_actor_count != runtime.actor_shadow_actions_last_hour
                        or current_conversation_count
                        != runtime.conversation_shadow_actions_last_hour
                        or abs(current_daily_cost - runtime.daily_shadow_cost_used) > 1e-6
                    ):
                        raise ConcurrentStateError("autonomy guardrail state changed before commit")

                await connection.execute(
                    """
                    INSERT INTO inbound_events(
                        event_id,
                        schema_version,
                        platform,
                        conversation_id,
                        event_type,
                        occurred_at,
                        payload_json,
                        payload_sha256,
                        ingested_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.schema_version,
                        event.platform.value,
                        event.conversation_id,
                        event.event_type.value,
                        event.occurred_at.isoformat(),
                        event_json,
                        event_hash,
                        trace.started_at.isoformat(),
                    ),
                )
                if trace.social_transition is not None:
                    social_after = trace.social_transition.after
                    social_json = canonical_json(social_after.model_dump(mode="json"))
                    await connection.execute(
                        """
                        INSERT INTO social_relationships(
                            relationship_id,
                            platform,
                            actor_id,
                            version,
                            state_json,
                            state_sha256,
                            last_event_id,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(relationship_id) DO UPDATE SET
                            version = excluded.version,
                            state_json = excluded.state_json,
                            state_sha256 = excluded.state_sha256,
                            last_event_id = excluded.last_event_id,
                            updated_at = excluded.updated_at
                        """,
                        (
                            social_after.relationship_id,
                            social_after.platform.value,
                            social_after.actor_id,
                            social_after.version,
                            social_json,
                            sha256_text(social_json),
                            social_after.last_event_id,
                            trace.completed_at.isoformat(),
                        ),
                    )
                if trace.belief_transition is not None:
                    for belief in trace.belief_transition.upserts:
                        belief_json = canonical_json(belief.model_dump(mode="json"))
                        await connection.execute(
                            """
                            INSERT INTO beliefs(
                                belief_id,
                                scope_id,
                                subject,
                                predicate,
                                status,
                                confidence,
                                record_json,
                                record_sha256,
                                updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(belief_id) DO UPDATE SET
                                status = excluded.status,
                                confidence = excluded.confidence,
                                record_json = excluded.record_json,
                                record_sha256 = excluded.record_sha256,
                                updated_at = excluded.updated_at
                            """,
                            (
                                belief.belief_id,
                                belief.scope_id,
                                belief.subject,
                                belief.predicate,
                                belief.status.value,
                                belief.confidence,
                                belief_json,
                                sha256_text(belief_json),
                                belief.updated_at.isoformat(),
                            ),
                        )
                if trace.internal_transition is not None:
                    internal_after = trace.internal_transition.after
                    internal_json = canonical_json(internal_after.model_dump(mode="json"))
                    await connection.execute(
                        """
                        INSERT INTO internal_states(
                            state_id,
                            version,
                            state_json,
                            state_sha256,
                            last_event_id,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(state_id) DO UPDATE SET
                            version = excluded.version,
                            state_json = excluded.state_json,
                            state_sha256 = excluded.state_sha256,
                            last_event_id = excluded.last_event_id,
                            updated_at = excluded.updated_at
                        """,
                        (
                            internal_after.state_id,
                            internal_after.version,
                            internal_json,
                            sha256_text(internal_json),
                            internal_after.last_event_id,
                            trace.completed_at.isoformat(),
                        ),
                    )
                if trace.goal_transition is not None:
                    for goal in trace.goal_transition.after:
                        goal_json = canonical_json(goal.model_dump(mode="json"))
                        await connection.execute(
                            """
                            INSERT INTO goals(
                                goal_id,
                                owner,
                                status,
                                priority,
                                urgency,
                                goal_json,
                                goal_sha256,
                                updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(goal_id) DO UPDATE SET
                                status = excluded.status,
                                priority = excluded.priority,
                                urgency = excluded.urgency,
                                goal_json = excluded.goal_json,
                                goal_sha256 = excluded.goal_sha256,
                                updated_at = excluded.updated_at
                            """,
                            (
                                goal.goal_id,
                                goal.owner,
                                goal.status.value,
                                goal.priority,
                                goal.urgency,
                                goal_json,
                                sha256_text(goal_json),
                                goal.updated_at.isoformat(),
                            ),
                        )
                await connection.execute(
                    """
                    INSERT INTO cycles(
                        cycle_id,
                        event_id,
                        schema_version,
                        status,
                        orchestrator_version,
                        started_at,
                        completed_at,
                        trace_json,
                        trace_sha256
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.cycle_id,
                        trace.event_id,
                        trace.schema_version,
                        trace.status.value,
                        trace.orchestrator_version,
                        trace.started_at.isoformat(),
                        trace.completed_at.isoformat(),
                        trace_json,
                        trace_hash,
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO processed_events(event_id, cycle_id, processed_at, outcome)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        trace.cycle_id,
                        trace.completed_at.isoformat(),
                        trace.decision.outcome.value,
                    ),
                )
                if trace.selected_action is not None:
                    if trace.execution_result is None:
                        raise ValueError("selected action is missing execution result")
                    action_json = canonical_json(trace.selected_action.model_dump(mode="json"))
                    language_json = (
                        canonical_json(trace.language_generation.model_dump(mode="json"))
                        if trace.language_generation is not None
                        else None
                    )
                    execution_json = canonical_json(trace.execution_result.model_dump(mode="json"))
                    await connection.execute(
                        """
                        INSERT INTO outbound_actions(
                            action_id,
                            cycle_id,
                            idempotency_key,
                            action_type,
                            action_json,
                            action_sha256,
                            language_json,
                            execution_json,
                            execution_status,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trace.selected_action.action_id,
                            trace.cycle_id,
                            trace.selected_action.idempotency_key,
                            trace.selected_action.action_type.value,
                            action_json,
                            sha256_text(action_json),
                            language_json,
                            execution_json,
                            trace.execution_result.status.value,
                            trace.selected_action.created_at.isoformat(),
                        ),
                    )
                if trace.memory_write_set is not None:
                    for record in trace.memory_write_set.records:
                        cursor = await connection.execute(
                            "SELECT record_json FROM memory_records WHERE memory_id = ?",
                            (record.memory_id,),
                        )
                        existing_row = await cursor.fetchone()
                        persisted_record = record
                        if existing_row is not None:
                            existing = MemoryRecord.model_validate_json(
                                str(existing_row["record_json"])
                            )
                            persisted_record = MemoryRecord.model_validate(
                                {
                                    **record.model_dump(mode="python"),
                                    "source_event_ids": tuple(
                                        sorted(
                                            {
                                                *existing.source_event_ids,
                                                *record.source_event_ids,
                                            }
                                        )
                                    ),
                                    "created_at": min(existing.created_at, record.created_at),
                                    "updated_at": max(existing.updated_at, record.updated_at),
                                }
                            )
                        record_json = canonical_json(persisted_record.model_dump(mode="json"))
                        await connection.execute(
                            """
                            INSERT INTO memory_records(
                                memory_id,
                                category,
                                scope_id,
                                canonical_source_type,
                                canonical_source_id,
                                validation_status,
                                importance,
                                confidence,
                                source_event_ids_json,
                                record_json,
                                record_sha256,
                                created_at,
                                updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(memory_id) DO UPDATE SET
                                scope_id = excluded.scope_id,
                                validation_status = excluded.validation_status,
                                importance = excluded.importance,
                                confidence = excluded.confidence,
                                source_event_ids_json = excluded.source_event_ids_json,
                                record_json = excluded.record_json,
                                record_sha256 = excluded.record_sha256,
                                created_at = excluded.created_at,
                                updated_at = excluded.updated_at
                            """,
                            (
                                persisted_record.memory_id,
                                persisted_record.category.value,
                                persisted_record.scope_id,
                                persisted_record.canonical_source_type,
                                persisted_record.canonical_source_id,
                                persisted_record.validation_status.value,
                                persisted_record.importance,
                                persisted_record.confidence,
                                canonical_json(list(persisted_record.source_event_ids)),
                                record_json,
                                sha256_text(record_json),
                                persisted_record.created_at.isoformat(),
                                persisted_record.updated_at.isoformat(),
                            ),
                        )
                if trace.outcome_evaluation is not None:
                    outcome_json = canonical_json(trace.outcome_evaluation.model_dump(mode="json"))
                    await connection.execute(
                        """
                        INSERT INTO cycle_outcomes(
                            cycle_id,
                            status,
                            payload_json,
                            payload_sha256,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            trace.cycle_id,
                            trace.outcome_evaluation.status.value,
                            outcome_json,
                            sha256_text(outcome_json),
                            trace.completed_at.isoformat(),
                        ),
                    )
                for proposal in trace.learning_proposals:
                    proposal_json = canonical_json(proposal.model_dump(mode="json"))
                    await connection.execute(
                        """
                        INSERT INTO learning_proposals(
                            proposal_id,
                            cycle_id,
                            target,
                            target_id,
                            status,
                            requires_validation,
                            payload_json,
                            payload_sha256,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            proposal.proposal_id,
                            trace.cycle_id,
                            proposal.target.value,
                            proposal.target_id,
                            proposal.status.value,
                            int(proposal.requires_validation),
                            proposal_json,
                            sha256_text(proposal_json),
                            trace.completed_at.isoformat(),
                        ),
                    )
                for trigger in trace.reflection_triggers:
                    trigger_json = canonical_json(trigger.model_dump(mode="json"))
                    await connection.execute(
                        """
                        INSERT INTO reflection_triggers(
                            trigger_id,
                            cycle_id,
                            trigger_type,
                            requires_validation,
                            payload_json,
                            payload_sha256,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trigger.trigger_id,
                            trace.cycle_id,
                            trigger.trigger_type.value,
                            int(trigger.requires_validation),
                            trigger_json,
                            sha256_text(trigger_json),
                            trace.completed_at.isoformat(),
                        ),
                    )
                if trace.autonomy_evaluation is not None:
                    autonomy = trace.autonomy_evaluation
                    for autonomy_trigger in autonomy.triggers:
                        trigger_json = canonical_json(autonomy_trigger.model_dump(mode="json"))
                        await connection.execute(
                            """
                            INSERT INTO internal_triggers(
                                trigger_id,
                                cycle_id,
                                trigger_type,
                                source_event_id,
                                payload_json,
                                payload_sha256,
                                created_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                autonomy_trigger.trigger_id,
                                trace.cycle_id,
                                autonomy_trigger.trigger_type.value,
                                autonomy_trigger.source_event_id,
                                trigger_json,
                                sha256_text(trigger_json),
                                autonomy_trigger.created_at.isoformat(),
                            ),
                        )
                    for initiative_proposal in autonomy.proposals:
                        proposal_json = canonical_json(initiative_proposal.model_dump(mode="json"))
                        await connection.execute(
                            """
                            INSERT INTO initiative_proposals(
                                proposal_id,
                                cycle_id,
                                trigger_id,
                                target_actor_id,
                                target_conversation_id,
                                risk_class,
                                estimated_cost,
                                payload_json,
                                payload_sha256,
                                created_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                initiative_proposal.proposal_id,
                                trace.cycle_id,
                                initiative_proposal.trigger_id,
                                initiative_proposal.target_actor_id,
                                initiative_proposal.target_conversation_id,
                                initiative_proposal.risk_class.value,
                                initiative_proposal.estimated_cost,
                                proposal_json,
                                sha256_text(proposal_json),
                                initiative_proposal.created_at.isoformat(),
                            ),
                        )
                    for decision in autonomy.decisions:
                        decision_json = canonical_json(decision.model_dump(mode="json"))
                        await connection.execute(
                            """
                            INSERT INTO guardrail_decisions(
                                decision_id,
                                cycle_id,
                                proposal_id,
                                outcome,
                                payload_json,
                                payload_sha256,
                                evaluated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                decision.decision_id,
                                trace.cycle_id,
                                decision.proposal_id,
                                decision.outcome.value,
                                decision_json,
                                sha256_text(decision_json),
                                decision.evaluated_at.isoformat(),
                            ),
                        )
                    for audit in autonomy.audit_records:
                        audit_json = canonical_json(audit.model_dump(mode="json"))
                        await connection.execute(
                            """
                            INSERT INTO autonomy_audit_log(
                                audit_id,
                                cycle_id,
                                source_event_id,
                                trigger_id,
                                proposal_id,
                                decision_id,
                                target_actor_id,
                                target_conversation_id,
                                outcome,
                                estimated_cost,
                                proactive_action_materialized,
                                payload_json,
                                payload_sha256,
                                recorded_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                audit.audit_id,
                                trace.cycle_id,
                                audit.source_event_id,
                                audit.trigger_id,
                                audit.proposal_id,
                                audit.decision_id,
                                audit.target_actor_id,
                                audit.target_conversation_id,
                                audit.outcome.value,
                                audit.estimated_cost,
                                int(audit.proactive_action_materialized),
                                audit_json,
                                sha256_text(audit_json),
                                audit.recorded_at.isoformat(),
                            ),
                        )

                for artifact_type, artifact_version, value in artifacts:
                    payload_json = canonical_json(value.model_dump(mode="json"))
                    await connection.execute(
                        """
                        INSERT INTO cycle_artifacts(
                            cycle_id,
                            artifact_type,
                            artifact_version,
                            payload_json,
                            payload_sha256,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trace.cycle_id,
                            artifact_type,
                            artifact_version,
                            payload_json,
                            sha256_text(payload_json),
                            trace.completed_at.isoformat(),
                        ),
                    )

                await connection.execute(
                    """
                    INSERT INTO conversation_state(conversation_id, version, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                        version = excluded.version,
                        updated_at = excluded.updated_at
                    """,
                    (
                        event.conversation_id,
                        trace.state_version_after,
                        trace.completed_at.isoformat(),
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO conversation_buffer(
                        conversation_id,
                        position,
                        event_id,
                        actor_id,
                        occurred_at,
                        channel_type,
                        content,
                        reply_to_event_id,
                        reply_to_actor_id,
                        mentions_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.conversation_id,
                        trace.state_version_after,
                        event.event_id,
                        event.actor_id,
                        event.occurred_at.isoformat(),
                        event.channel_type.value,
                        event.content,
                        event.reply_to.event_id if event.reply_to is not None else None,
                        event.reply_to.actor_id if event.reply_to is not None else None,
                        canonical_json(list(event.mentions)),
                    ),
                )
                if event.reply_to is not None:
                    await connection.execute(
                        """
                        INSERT INTO reply_graph_edges(
                            conversation_id,
                            event_id,
                            reply_to_event_id,
                            reply_to_actor_id,
                            position
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            event.conversation_id,
                            event.event_id,
                            event.reply_to.event_id,
                            event.reply_to.actor_id,
                            trace.state_version_after,
                        ),
                    )
                await connection.execute(
                    """
                    INSERT INTO conversation_participation(
                        conversation_id,
                        position,
                        event_id,
                        cycle_id,
                        outcome,
                        score,
                        policy_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.conversation_id,
                        trace.state_version_after,
                        event.event_id,
                        trace.cycle_id,
                        trace.decision.outcome.value,
                        trace.decision.score_breakdown.total,
                        trace.decision.policy_version,
                    ),
                )

                prune_before = trace.state_version_after - self.conversation_buffer_limit
                if prune_before > 0:
                    await connection.execute(
                        """
                        DELETE FROM conversation_buffer
                        WHERE conversation_id = ? AND position <= ?
                        """,
                        (event.conversation_id, prune_before),
                    )
                participation_prune_before = (
                    trace.state_version_after - self.recent_participation_limit
                )
                if participation_prune_before > 0:
                    await connection.execute(
                        """
                        DELETE FROM conversation_participation
                        WHERE conversation_id = ? AND position <= ?
                        """,
                        (event.conversation_id, participation_prune_before),
                    )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

        return FoundationIngestResult(trace=trace, duplicate=False)

    @staticmethod
    def _decode_mentions(raw: str) -> tuple[str, ...]:
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
            raise ValueError("stored mentions_json is not a list of strings")
        return tuple(decoded)

    async def get_event(self, event_id: str) -> InboundEvent:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT payload_json FROM inbound_events WHERE event_id = ?",
                (event_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError(f"event not found: {event_id}")
        return InboundEvent.model_validate_json(str(row["payload_json"]))

    async def get_cycle(self, cycle_id: str) -> CycleTrace:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT trace_json FROM cycles WHERE cycle_id = ?",
                (cycle_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError(f"cycle not found: {cycle_id}")
        return CycleTrace.model_validate_json(str(row["trace_json"]))

    async def get_cycle_for_event(self, event_id: str) -> CycleTrace:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT trace_json FROM cycles WHERE event_id = ?",
                (event_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError(f"cycle not found for event: {event_id}")
        return CycleTrace.model_validate_json(str(row["trace_json"]))
