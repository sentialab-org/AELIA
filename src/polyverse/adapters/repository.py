from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from polyverse.contracts.adapter import (
    AdapterDeliveryReceipt,
    AdapterDispatchDecision,
    AdapterDispatchRecord,
    AdapterInboundEnvelope,
    AdapterIngressRecord,
    AdapterOutboundCommand,
    DispatchOutcome,
    DispatchState,
)
from polyverse.contracts.connector import ExternalDeliveryReceipt
from polyverse.storage.database import Database
from polyverse.storage.repositories import canonical_json, sha256_text


class AdapterConflictError(RuntimeError):
    """Raised when an adapter idempotency key is reused with different data."""


class AdapterConcurrentStateError(RuntimeError):
    """Raised when a dispatch decision used a stale rate-limit snapshot."""


@dataclass(frozen=True)
class DispatchReservation:
    record: AdapterDispatchRecord
    created: bool


class SqliteAdapterRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def initialize(self) -> None:
        await self.database.initialize()

    async def get_ingress(
        self,
        delivery_id: str,
    ) -> AdapterIngressRecord | None:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT
                    delivery_id,
                    envelope_sha256,
                    event_id,
                    cycle_id,
                    kernel_duplicate,
                    recorded_at
                FROM adapter_ingress
                WHERE delivery_id = ?
                """,
                (delivery_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._ingress_from_row(row)

    async def preflight_ingress(
        self,
        envelope: AdapterInboundEnvelope,
    ) -> AdapterIngressRecord | None:
        envelope_hash = sha256_text(canonical_json(envelope.model_dump(mode="json")))
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT
                    delivery_id,
                    envelope_sha256,
                    event_id,
                    cycle_id,
                    kernel_duplicate,
                    recorded_at
                FROM adapter_ingress
                WHERE delivery_id = ? OR idempotency_key = ?
                """,
                (envelope.delivery_id, envelope.idempotency_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        if (
            str(row["delivery_id"]) != envelope.delivery_id
            or str(row["envelope_sha256"]) != envelope_hash
        ):
            raise AdapterConflictError(
                "adapter delivery/idempotency key was reused with a different envelope"
            )
        return self._ingress_from_row(row)

    async def record_ingress(
        self,
        *,
        envelope: AdapterInboundEnvelope,
        cycle_id: str,
        kernel_duplicate: bool,
    ) -> tuple[AdapterIngressRecord, bool]:
        envelope_json = canonical_json(envelope.model_dump(mode="json"))
        envelope_hash = sha256_text(envelope_json)
        async with self.database.connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    """
                    SELECT
                        delivery_id,
                        envelope_sha256,
                        event_id,
                        cycle_id,
                        kernel_duplicate,
                        recorded_at
                    FROM adapter_ingress
                    WHERE delivery_id = ? OR idempotency_key = ?
                    """,
                    (envelope.delivery_id, envelope.idempotency_key),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    if (
                        str(existing["delivery_id"]) != envelope.delivery_id
                        or str(existing["envelope_sha256"]) != envelope_hash
                    ):
                        raise AdapterConflictError(
                            "adapter delivery/idempotency key was reused with a different envelope"
                        )
                    await connection.rollback()
                    return self._ingress_from_row(existing), False

                record = AdapterIngressRecord(
                    delivery_id=envelope.delivery_id,
                    envelope_sha256=envelope_hash,
                    event_id=envelope.event.event_id,
                    cycle_id=cycle_id,
                    kernel_duplicate=kernel_duplicate,
                    recorded_at=envelope.received_at,
                )
                await connection.execute(
                    """
                    INSERT INTO adapter_ingress(
                        delivery_id,
                        idempotency_key,
                        envelope_sha256,
                        envelope_json,
                        event_id,
                        cycle_id,
                        kernel_duplicate,
                        recorded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        envelope.delivery_id,
                        envelope.idempotency_key,
                        envelope_hash,
                        envelope_json,
                        record.event_id,
                        record.cycle_id,
                        int(record.kernel_duplicate),
                        record.recorded_at.isoformat(),
                    ),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
        return record, True

    async def recent_canary_dispatch_count(
        self,
        *,
        conversation_id: str,
        window_start: datetime,
    ) -> int:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT count(*)
                FROM adapter_dispatches
                WHERE target_conversation_id = ?
                  AND outcome IN (?, ?)
                  AND created_at >= ?
                """,
                (
                    conversation_id,
                    DispatchOutcome.SIMULATE_CANARY.value,
                    DispatchOutcome.QUEUE_EXTERNAL_CANARY.value,
                    window_start.isoformat(),
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("adapter dispatch count query returned no row")
        return int(row[0])

    async def reserve_dispatch(
        self,
        *,
        command: AdapterOutboundCommand,
        decision: AdapterDispatchDecision,
    ) -> DispatchReservation:
        command_json = canonical_json(command.model_dump(mode="json"))
        command_hash = sha256_text(command_json)
        decision_json = canonical_json(decision.model_dump(mode="json"))
        async with self.database.connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    """
                    SELECT *
                    FROM adapter_dispatches
                    WHERE command_id = ? OR idempotency_key = ?
                    """,
                    (command.command_id, command.idempotency_key),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    if (
                        str(existing["command_id"]) != command.command_id
                        or str(existing["command_sha256"]) != command_hash
                    ):
                        raise AdapterConflictError(
                            "adapter command/idempotency key was reused with different data"
                        )
                    await connection.rollback()
                    return DispatchReservation(
                        record=self._dispatch_from_row(existing),
                        created=False,
                    )
                if decision.outcome in {
                    DispatchOutcome.SIMULATE_CANARY,
                    DispatchOutcome.QUEUE_EXTERNAL_CANARY,
                }:
                    cursor = await connection.execute(
                        """
                        SELECT count(*)
                        FROM adapter_dispatches
                        WHERE target_conversation_id = ?
                          AND outcome IN (?, ?)
                          AND created_at >= ?
                        """,
                        (
                            command.target_conversation_id,
                            DispatchOutcome.SIMULATE_CANARY.value,
                            DispatchOutcome.QUEUE_EXTERNAL_CANARY.value,
                            (decision.decided_at - timedelta(hours=1)).isoformat(),
                        ),
                    )
                    count_row = await cursor.fetchone()
                    if count_row is None:
                        raise RuntimeError("adapter reservation count query returned no row")
                    current_count = int(count_row[0])
                    if current_count != decision.recent_conversation_dispatches:
                        raise AdapterConcurrentStateError(
                            "adapter rate-limit state changed before reservation"
                        )

                record = AdapterDispatchRecord(
                    command=command,
                    decision=decision,
                    state=DispatchState.RESERVED,
                    receipt=None,
                    created_at=decision.decided_at,
                    updated_at=decision.decided_at,
                )
                await connection.execute(
                    """
                    INSERT INTO adapter_dispatches(
                        command_id,
                        action_id,
                        cycle_id,
                        idempotency_key,
                        target_conversation_id,
                        mode,
                        outcome,
                        state,
                        command_json,
                        command_sha256,
                        decision_json,
                        receipt_json,
                        delivery_status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                    """,
                    (
                        command.command_id,
                        command.action_id,
                        command.cycle_id,
                        command.idempotency_key,
                        command.target_conversation_id,
                        decision.mode.value,
                        decision.outcome.value,
                        record.state.value,
                        command_json,
                        command_hash,
                        decision_json,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                    ),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
        return DispatchReservation(record=record, created=True)

    async def finalize_dispatch(
        self,
        receipt: AdapterDeliveryReceipt,
    ) -> AdapterDispatchRecord:
        return await self._finalize_dispatch(receipt)

    async def finalize_external_dispatch(
        self,
        receipt: ExternalDeliveryReceipt,
    ) -> AdapterDispatchRecord:
        return await self._finalize_dispatch(receipt)

    async def _finalize_dispatch(
        self,
        receipt: AdapterDeliveryReceipt | ExternalDeliveryReceipt,
    ) -> AdapterDispatchRecord:
        async with self.database.connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "SELECT * FROM adapter_dispatches WHERE command_id = ?",
                    (receipt.command_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise AdapterConflictError(f"adapter dispatch not found: {receipt.command_id}")
                existing = self._dispatch_from_row(row)
                if existing.state is DispatchState.FINALIZED:
                    if existing.receipt != receipt:
                        raise AdapterConflictError(
                            "finalized dispatch received a conflicting receipt"
                        )
                    await connection.rollback()
                    return existing
                if receipt.idempotency_key != existing.command.idempotency_key:
                    raise AdapterConflictError(
                        "delivery receipt idempotency key does not match command"
                    )
                if isinstance(receipt, ExternalDeliveryReceipt):
                    if existing.decision.outcome is not DispatchOutcome.QUEUE_EXTERNAL_CANARY:
                        raise AdapterConflictError(
                            "external receipt requires a queued external dispatch"
                        )
                    if receipt.platform is not existing.command.platform:
                        raise AdapterConflictError(
                            "external receipt platform does not match command"
                        )
                elif existing.decision.outcome is DispatchOutcome.QUEUE_EXTERNAL_CANARY:
                    raise AdapterConflictError(
                        "queued external dispatch requires an external receipt"
                    )
                finalized = AdapterDispatchRecord(
                    command=existing.command,
                    decision=existing.decision,
                    state=DispatchState.FINALIZED,
                    receipt=receipt,
                    created_at=existing.created_at,
                    updated_at=receipt.completed_at,
                )
                await connection.execute(
                    """
                    UPDATE adapter_dispatches
                    SET state = ?,
                        receipt_json = ?,
                        delivery_status = ?,
                        updated_at = ?
                    WHERE command_id = ? AND state = ?
                    """,
                    (
                        finalized.state.value,
                        canonical_json(receipt.model_dump(mode="json")),
                        receipt.status.value,
                        finalized.updated_at.isoformat(),
                        receipt.command_id,
                        DispatchState.RESERVED.value,
                    ),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
        return finalized

    async def get_dispatch_for_action(
        self,
        action_id: str,
    ) -> AdapterDispatchRecord | None:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM adapter_dispatches WHERE action_id = ?",
                (action_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else self._dispatch_from_row(row)

    async def list_pending_dispatches(
        self,
        *,
        limit: int = 100,
    ) -> tuple[AdapterDispatchRecord, ...]:
        if limit < 1 or limit > 1_000:
            raise ValueError("pending dispatch limit must be between 1 and 1000")
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM adapter_dispatches
                WHERE state = ?
                ORDER BY created_at, command_id
                LIMIT ?
                """,
                (DispatchState.RESERVED.value, limit),
            )
            rows = tuple(await cursor.fetchall())
        return tuple(self._dispatch_from_row(row) for row in rows)

    @staticmethod
    def _ingress_from_row(row: sqlite3.Row) -> AdapterIngressRecord:
        return AdapterIngressRecord(
            delivery_id=str(row["delivery_id"]),
            envelope_sha256=str(row["envelope_sha256"]),
            event_id=str(row["event_id"]),
            cycle_id=str(row["cycle_id"]),
            kernel_duplicate=bool(row["kernel_duplicate"]),
            recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
        )

    @staticmethod
    def _dispatch_from_row(row: sqlite3.Row) -> AdapterDispatchRecord:
        receipt_json = row["receipt_json"]
        receipt: AdapterDeliveryReceipt | ExternalDeliveryReceipt | None = None
        if receipt_json is not None:
            raw_receipt = str(receipt_json)
            parsed_receipt = json.loads(raw_receipt)
            if parsed_receipt.get("schema_version") == "2.0.0":
                receipt = ExternalDeliveryReceipt.model_validate(parsed_receipt)
            else:
                receipt = AdapterDeliveryReceipt.model_validate(parsed_receipt)
        return AdapterDispatchRecord(
            command=AdapterOutboundCommand.model_validate_json(str(row["command_json"])),
            decision=AdapterDispatchDecision.model_validate_json(str(row["decision_json"])),
            state=DispatchState(str(row["state"])),
            receipt=receipt,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
