from __future__ import annotations

from polyverse.contracts.connector import (
    ConnectorCapabilities,
    ConnectorReadinessCheck,
    ConnectorReadinessReport,
)

CONNECTOR_READINESS_POLICY_VERSION = "connector-readiness-v1"


class ConnectorReadinessPolicy:
    """Static gate; behavioral canary evidence is still required by the runbook."""

    def evaluate(
        self,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorReadinessReport:
        declared_checks = (
            (
                "idempotency_lookup",
                capabilities.supports_idempotency_lookup,
                "Connector can reconcile a command by idempotency key.",
            ),
            (
                "canary_allowlist",
                capabilities.supports_canary_allowlist,
                "Connector can constrain live delivery to an explicit allowlist.",
            ),
            (
                "kill_switch",
                capabilities.supports_kill_switch,
                "Connector can disable external delivery without changing the kernel.",
            ),
            (
                "reconnect_cursor",
                capabilities.supports_reconnect_cursor,
                "Connector persists or recovers its inbound cursor.",
            ),
            (
                "permission_probe",
                capabilities.supports_permission_probe,
                "Connector checks current platform permissions before delivery.",
            ),
            (
                "rate_limit_observation",
                capabilities.supports_rate_limit_observation,
                "Connector exposes platform rate-limit state to its boundary.",
            ),
            (
                "secret_redaction",
                capabilities.redacts_secrets,
                "Connector excludes credentials from errors, logs, and receipts.",
            ),
        )
        checks = tuple(
            ConnectorReadinessCheck(
                code=code,
                passed=passed,
                evidence=evidence,
            )
            for code, passed, evidence in declared_checks
        )
        return ConnectorReadinessReport(
            policy_version=CONNECTOR_READINESS_POLICY_VERSION,
            connector_id=capabilities.connector_id,
            platform=capabilities.platform,
            ready_for_authorized_canary=all(check.passed for check in checks),
            checks=checks,
        )
