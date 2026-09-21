from __future__ import annotations

from dataclasses import dataclass

import aiosqlite


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        name="foundation_event_log_and_cycles",
        statements=(
            """
            CREATE TABLE inbound_events (
                event_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                platform TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX idx_inbound_events_conversation_time
            ON inbound_events(conversation_id, occurred_at)
            """,
            """
            CREATE TABLE cycles (
                cycle_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                schema_version TEXT NOT NULL,
                status TEXT NOT NULL,
                orchestrator_version TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                trace_sha256 TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES inbound_events(event_id)
            )
            """,
            """
            CREATE TABLE processed_events (
                event_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL UNIQUE,
                processed_at TEXT NOT NULL,
                outcome TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES inbound_events(event_id),
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
            """
            CREATE TABLE cycle_artifacts (
                cycle_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(cycle_id, artifact_type),
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
        ),
    ),
    Migration(
        version=2,
        name="observation_buffer_reply_graph_and_participation",
        statements=(
            """
            CREATE TABLE conversation_state (
                conversation_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL CHECK(version >= 0),
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE conversation_buffer (
                conversation_id TEXT NOT NULL,
                position INTEGER NOT NULL CHECK(position >= 1),
                event_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                content TEXT,
                reply_to_event_id TEXT,
                reply_to_actor_id TEXT,
                mentions_json TEXT NOT NULL,
                PRIMARY KEY(conversation_id, position),
                FOREIGN KEY(event_id) REFERENCES inbound_events(event_id)
            )
            """,
            """
            CREATE INDEX idx_conversation_buffer_recent
            ON conversation_buffer(conversation_id, position DESC)
            """,
            """
            CREATE TABLE reply_graph_edges (
                conversation_id TEXT NOT NULL,
                event_id TEXT PRIMARY KEY,
                reply_to_event_id TEXT NOT NULL,
                reply_to_actor_id TEXT,
                position INTEGER NOT NULL CHECK(position >= 1),
                FOREIGN KEY(event_id) REFERENCES inbound_events(event_id)
            )
            """,
            """
            CREATE INDEX idx_reply_graph_conversation
            ON reply_graph_edges(conversation_id, position DESC)
            """,
            """
            CREATE TABLE conversation_participation (
                conversation_id TEXT NOT NULL,
                position INTEGER NOT NULL CHECK(position >= 1),
                event_id TEXT NOT NULL UNIQUE,
                cycle_id TEXT NOT NULL UNIQUE,
                outcome TEXT NOT NULL,
                score REAL NOT NULL,
                policy_version TEXT NOT NULL,
                PRIMARY KEY(conversation_id, position),
                FOREIGN KEY(event_id) REFERENCES inbound_events(event_id),
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
            """
            CREATE INDEX idx_conversation_participation_recent
            ON conversation_participation(conversation_id, position DESC)
            """,
        ),
    ),
    Migration(
        version=3,
        name="canonical_social_relationship_state",
        statements=(
            """
            CREATE TABLE social_relationships (
                relationship_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version >= 0),
                state_json TEXT NOT NULL,
                state_sha256 TEXT NOT NULL,
                last_event_id TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(platform, actor_id)
            )
            """,
            """
            CREATE INDEX idx_social_relationship_actor
            ON social_relationships(platform, actor_id)
            """,
        ),
    ),
    Migration(
        version=4,
        name="beliefs_and_internal_cognitive_state",
        statements=(
            """
            CREATE TABLE beliefs (
                belief_id TEXT PRIMARY KEY,
                scope_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX idx_beliefs_scope
            ON beliefs(scope_id, predicate, updated_at DESC)
            """,
            """
            CREATE TABLE internal_states (
                state_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL CHECK(version >= 0),
                state_json TEXT NOT NULL,
                state_sha256 TEXT NOT NULL,
                last_event_id TEXT,
                updated_at TEXT NOT NULL
            )
            """,
        ),
    ),
    Migration(
        version=5,
        name="goals_and_idempotent_outbound_actions",
        statements=(
            """
            CREATE TABLE goals (
                goal_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                priority REAL NOT NULL,
                urgency REAL NOT NULL,
                goal_json TEXT NOT NULL,
                goal_sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX idx_goals_owner_status
            ON goals(owner, status, priority DESC, urgency DESC)
            """,
            """
            CREATE TABLE outbound_actions (
                action_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL UNIQUE,
                action_type TEXT NOT NULL,
                action_json TEXT NOT NULL,
                action_sha256 TEXT NOT NULL,
                language_json TEXT,
                execution_json TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
        ),
    ),
    Migration(
        version=6,
        name="canonical_memory_outcomes_and_learning_proposals",
        statements=(
            """
            CREATE TABLE memory_records (
                memory_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                canonical_source_type TEXT NOT NULL,
                canonical_source_id TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                importance REAL NOT NULL,
                confidence REAL NOT NULL,
                source_event_ids_json TEXT NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(category, canonical_source_type, canonical_source_id)
            )
            """,
            """
            CREATE INDEX idx_memory_records_scope_category
            ON memory_records(scope_id, category, importance DESC, updated_at DESC)
            """,
            """
            CREATE TABLE cycle_outcomes (
                cycle_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
            """
            CREATE TABLE learning_proposals (
                proposal_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                target TEXT NOT NULL,
                target_id TEXT NOT NULL,
                status TEXT NOT NULL,
                requires_validation INTEGER NOT NULL CHECK(requires_validation IN (0, 1)),
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
            """
            CREATE INDEX idx_learning_proposals_status
            ON learning_proposals(status, target, created_at)
            """,
            """
            CREATE TABLE reflection_triggers (
                trigger_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                requires_validation INTEGER NOT NULL CHECK(requires_validation IN (0, 1)),
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
        ),
    ),
    Migration(
        version=7,
        name="initiative_guardrails_opt_outs_and_audit",
        statements=(
            """
            CREATE TABLE autonomy_opt_outs (
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                opted_out INTEGER NOT NULL CHECK(opted_out IN (0, 1)),
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(scope_type, scope_id)
            )
            """,
            """
            CREATE TABLE internal_triggers (
                trigger_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id),
                FOREIGN KEY(source_event_id) REFERENCES inbound_events(event_id)
            )
            """,
            """
            CREATE INDEX idx_internal_triggers_type_time
            ON internal_triggers(trigger_type, created_at)
            """,
            """
            CREATE TABLE initiative_proposals (
                proposal_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                trigger_id TEXT NOT NULL,
                target_actor_id TEXT NOT NULL,
                target_conversation_id TEXT NOT NULL,
                risk_class TEXT NOT NULL,
                estimated_cost REAL NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id),
                FOREIGN KEY(trigger_id) REFERENCES internal_triggers(trigger_id)
            )
            """,
            """
            CREATE TABLE guardrail_decisions (
                decision_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                proposal_id TEXT NOT NULL UNIQUE,
                outcome TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id),
                FOREIGN KEY(proposal_id) REFERENCES initiative_proposals(proposal_id)
            )
            """,
            """
            CREATE TABLE autonomy_audit_log (
                audit_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                trigger_id TEXT NOT NULL,
                proposal_id TEXT NOT NULL,
                decision_id TEXT NOT NULL UNIQUE,
                target_actor_id TEXT NOT NULL,
                target_conversation_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                estimated_cost REAL NOT NULL,
                proactive_action_materialized INTEGER NOT NULL
                    CHECK(proactive_action_materialized = 0),
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id),
                FOREIGN KEY(source_event_id) REFERENCES inbound_events(event_id),
                FOREIGN KEY(trigger_id) REFERENCES internal_triggers(trigger_id),
                FOREIGN KEY(proposal_id) REFERENCES initiative_proposals(proposal_id),
                FOREIGN KEY(decision_id) REFERENCES guardrail_decisions(decision_id)
            )
            """,
            """
            CREATE INDEX idx_autonomy_audit_actor_time
            ON autonomy_audit_log(target_actor_id, outcome, recorded_at)
            """,
            """
            CREATE INDEX idx_autonomy_audit_conversation_time
            ON autonomy_audit_log(target_conversation_id, outcome, recorded_at)
            """,
        ),
    ),
    Migration(
        version=8,
        name="adapter_ingress_and_transactional_dispatch_outbox",
        statements=(
            """
            CREATE TABLE adapter_ingress (
                delivery_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                envelope_sha256 TEXT NOT NULL,
                envelope_json TEXT NOT NULL,
                event_id TEXT NOT NULL,
                cycle_id TEXT NOT NULL,
                kernel_duplicate INTEGER NOT NULL CHECK(kernel_duplicate IN (0, 1)),
                recorded_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES inbound_events(event_id),
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
            """
            CREATE TABLE adapter_dispatches (
                command_id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL UNIQUE,
                cycle_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                target_conversation_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                outcome TEXT NOT NULL,
                state TEXT NOT NULL,
                command_json TEXT NOT NULL,
                command_sha256 TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                receipt_json TEXT,
                delivery_status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(action_id) REFERENCES outbound_actions(action_id),
                FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
            )
            """,
            """
            CREATE INDEX idx_adapter_dispatch_conversation_time
            ON adapter_dispatches(
                target_conversation_id,
                delivery_status,
                updated_at
            )
            """,
            """
            CREATE INDEX idx_adapter_dispatch_pending
            ON adapter_dispatches(state, created_at)
            """,
        ),
    ),
)


async def apply_migrations(connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    await connection.commit()

    cursor = await connection.execute("SELECT version FROM schema_migrations")
    applied = {int(row[0]) for row in await cursor.fetchall()}

    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        await connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in migration.statements:
                await connection.execute(statement)
            await connection.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at)
                VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (migration.version, migration.name),
            )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
