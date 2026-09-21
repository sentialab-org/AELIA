from __future__ import annotations

import hashlib
from datetime import datetime
from typing import ClassVar

from polyverse.contracts.actions import (
    ActionSelection,
    CandidateActionType,
    ExecutionResult,
    ExecutionStatus,
)
from polyverse.contracts.common import Provenance, ProvenanceKind
from polyverse.contracts.events import ChannelType, InboundEvent
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.models.cognition import InternalState
from polyverse.models.goals import (
    Goal,
    GoalChange,
    GoalSource,
    GoalStatus,
    GoalTransition,
)

GOAL_POLICY_VERSION = "goal-policy-v1"


class GoalManager:
    _ALLOWED_TRANSITIONS: ClassVar[dict[GoalStatus, frozenset[GoalStatus]]] = {
        GoalStatus.ACTIVE: frozenset(
            {
                GoalStatus.PAUSED,
                GoalStatus.COMPLETED,
                GoalStatus.CANCELLED,
                GoalStatus.SUPERSEDED,
            }
        ),
        GoalStatus.PAUSED: frozenset(
            {
                GoalStatus.ACTIVE,
                GoalStatus.CANCELLED,
                GoalStatus.SUPERSEDED,
            }
        ),
        GoalStatus.COMPLETED: frozenset(),
        GoalStatus.CANCELLED: frozenset(),
        GoalStatus.SUPERSEDED: frozenset(),
    }

    def propose(
        self,
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        before: tuple[Goal, ...],
        owner: str,
        internal: InternalState | None = None,
    ) -> GoalTransition:
        addressed = (
            event.channel_type is ChannelType.DM
            or observation.agent_actor_id in event.mentions
            or (
                event.reply_to is not None and event.reply_to.actor_id == observation.agent_actor_id
            )
        )
        request_like = bool((event.content or "").strip()) and (
            "?" in (event.content or "") or addressed
        )
        if not addressed or not request_like:
            return GoalTransition(
                policy_version=GOAL_POLICY_VERSION,
                before=before,
                after=before,
                changes=(),
            )

        goal_hash = hashlib.sha256(f"{owner}\x1f{event.event_id}".encode()).hexdigest()[:24]
        priority = (
            round(
                min(
                    1.0,
                    0.55
                    + internal.drives.uncertainty_reduction * 0.20
                    + max(0.0, internal.drives.safety - 0.3) * 0.15,
                ),
                6,
            )
            if internal is not None
            else 0.7
        )
        urgency = (
            round(min(1.0, 0.50 + internal.affect.arousal * 0.20), 6)
            if internal is not None
            else 0.6
        )
        goal = Goal(
            goal_id=f"goal:{goal_hash}",
            source=GoalSource.USER_REQUEST,
            description=f"Resolve whether and how to respond to event {event.event_id}.",
            success_condition="A policy-selected participation outcome is handled.",
            priority=priority,
            urgency=urgency,
            status=GoalStatus.ACTIVE,
            progress=0.0,
            owner=owner,
            conflict_set=(),
            allowed_actions=(
                CandidateActionType.REPLY,
                CandidateActionType.WAIT,
                CandidateActionType.SILENT,
                CandidateActionType.NO_ACTION,
            ),
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=GOAL_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
            created_at=event.occurred_at,
            updated_at=event.occurred_at,
        )
        return GoalTransition(
            policy_version=GOAL_POLICY_VERSION,
            before=before,
            after=(*before, goal),
            changes=(
                GoalChange(
                    goal_id=goal.goal_id,
                    status_before=None,
                    status_after=GoalStatus.ACTIVE,
                    reason_code="direct_request_goal_created",
                ),
            ),
        )

    def resolve(
        self,
        *,
        transition: GoalTransition,
        selection: ActionSelection,
        selected_action_type: CandidateActionType | None,
        occurred_at: datetime,
        execution: ExecutionResult | None = None,
    ) -> GoalTransition:
        created_ids = {
            change.goal_id for change in transition.changes if change.status_before is None
        }
        if not created_ids:
            return transition
        if (
            selected_action_type in {CandidateActionType.REPLY, CandidateActionType.JOIN}
            and execution is not None
            and execution.status is not ExecutionStatus.FAILED
        ):
            target_status = GoalStatus.COMPLETED
            progress = 1.0
            reason = f"communicative_execution_{execution.status.value}"
        elif selected_action_type in {
            CandidateActionType.REPLY,
            CandidateActionType.JOIN,
        }:
            target_status = GoalStatus.ACTIVE
            progress = 0.0
            reason = (
                "communicative_execution_failed"
                if execution is not None
                else "communicative_execution_pending"
            )
        elif selected_action_type is CandidateActionType.WAIT:
            target_status = GoalStatus.PAUSED
            progress = 0.2
            reason = "wait_action_selected"
        else:
            target_status = GoalStatus.CANCELLED
            progress = 0.0
            reason = (
                "no_eligible_action"
                if selection.selected_candidate_id is None
                else "non_progress_action_selected"
            )

        after: list[Goal] = []
        changes = list(transition.changes)
        for goal in transition.after:
            if goal.goal_id not in created_ids:
                after.append(goal)
                continue
            updated = (
                goal.model_copy(update={"progress": progress, "updated_at": occurred_at})
                if target_status is goal.status
                else self.change_status(
                    goal,
                    target_status,
                    occurred_at=occurred_at,
                    progress=progress,
                )
            )
            after.append(updated)
            changes.append(
                GoalChange(
                    goal_id=goal.goal_id,
                    status_before=goal.status,
                    status_after=updated.status,
                    reason_code=reason,
                )
            )
        return transition.model_copy(update={"after": tuple(after), "changes": tuple(changes)})

    def change_status(
        self,
        goal: Goal,
        status: GoalStatus,
        *,
        occurred_at: datetime,
        progress: float | None = None,
    ) -> Goal:
        if status not in self._ALLOWED_TRANSITIONS[goal.status]:
            raise ValueError(f"invalid goal transition: {goal.status.value} -> {status.value}")
        return goal.model_copy(
            update={
                "status": status,
                "progress": goal.progress if progress is None else progress,
                "updated_at": occurred_at,
            }
        )

    def merge(
        self,
        goals: tuple[Goal, ...],
        *,
        occurred_at: datetime,
    ) -> GoalTransition:
        if len(goals) < 2:
            raise ValueError("goal merge requires at least two goals")
        if len({goal.goal_id for goal in goals}) != len(goals):
            raise ValueError("goal merge requires unique goal ids")
        if len({goal.owner for goal in goals}) != 1:
            raise ValueError("goal merge requires one owner")
        if any(goal.status not in {GoalStatus.ACTIVE, GoalStatus.PAUSED} for goal in goals):
            raise ValueError("only active or paused goals can be merged")

        primary = sorted(
            goals,
            key=lambda goal: (
                0 if goal.status is GoalStatus.ACTIVE else 1,
                -goal.priority,
                -goal.urgency,
                goal.created_at,
                goal.goal_id,
            ),
        )[0]
        merged_goal_ids = {goal.goal_id for goal in goals}
        merged_primary = primary.model_copy(
            update={
                "priority": max(goal.priority for goal in goals),
                "urgency": max(goal.urgency for goal in goals),
                "progress": max(goal.progress for goal in goals),
                "conflict_set": tuple(
                    sorted(
                        {
                            conflict_id
                            for goal in goals
                            for conflict_id in goal.conflict_set
                            if conflict_id not in merged_goal_ids
                        }
                    )
                ),
                "allowed_actions": tuple(
                    sorted(
                        {action for goal in goals for action in goal.allowed_actions},
                        key=lambda action: action.value,
                    )
                ),
                "updated_at": occurred_at,
            }
        )
        after = []
        changes = []
        for goal in goals:
            if goal.goal_id == primary.goal_id:
                after.append(merged_primary)
                continue
            superseded = self.change_status(
                goal,
                GoalStatus.SUPERSEDED,
                occurred_at=occurred_at,
            )
            after.append(superseded)
            changes.append(
                GoalChange(
                    goal_id=goal.goal_id,
                    status_before=goal.status,
                    status_after=GoalStatus.SUPERSEDED,
                    reason_code=f"merged_into:{primary.goal_id}",
                )
            )
        return GoalTransition(
            policy_version=GOAL_POLICY_VERSION,
            before=goals,
            after=tuple(after),
            changes=tuple(changes),
        )
