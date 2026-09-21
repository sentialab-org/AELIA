from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polyverse.cognition.action_policy import ActionPolicy, TurnTakingPolicy
from polyverse.cognition.conversation import ConversationPolicy
from polyverse.cognition.goals import GoalManager
from polyverse.contracts.actions import (
    ActionCandidate,
    ActionTarget,
    CandidateActionType,
    DeliberationResult,
    TurnTakingOutcome,
)
from polyverse.contracts.events import ChannelType
from polyverse.contracts.observation import ObservationSnapshot, RecentParticipation
from polyverse.contracts.participation import ParticipationOutcome
from polyverse.models.cognition import InternalState
from polyverse.models.goals import GoalStatus
from tests.helpers import make_event


def _observation() -> ObservationSnapshot:
    return ObservationSnapshot(
        conversation_id="conversation-001",
        agent_actor_id="agent-001",
        state_version=0,
    )


def test_goal_lifecycle_supports_pause_resume_complete_cancel_and_supersede() -> None:
    event = make_event(
        event_id="goal-source",
        content="can you help?",
        channel_type=ChannelType.DM,
    )
    manager = GoalManager()
    proposed = manager.propose(
        event=event,
        observation=_observation(),
        before=(),
        owner="ryuuko",
    )
    active = proposed.after[0]
    timestamp = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)

    paused = manager.change_status(active, GoalStatus.PAUSED, occurred_at=timestamp)
    resumed = manager.change_status(paused, GoalStatus.ACTIVE, occurred_at=timestamp)
    completed = manager.change_status(
        resumed,
        GoalStatus.COMPLETED,
        occurred_at=timestamp,
        progress=1.0,
    )
    cancelled = manager.change_status(active, GoalStatus.CANCELLED, occurred_at=timestamp)
    superseded = manager.change_status(active, GoalStatus.SUPERSEDED, occurred_at=timestamp)

    assert paused.status is GoalStatus.PAUSED
    assert resumed.status is GoalStatus.ACTIVE
    assert completed.status is GoalStatus.COMPLETED
    assert completed.progress == 1.0
    assert cancelled.status is GoalStatus.CANCELLED
    assert superseded.status is GoalStatus.SUPERSEDED
    with pytest.raises(ValueError, match="invalid goal transition"):
        manager.change_status(completed, GoalStatus.ACTIVE, occurred_at=timestamp)


def test_goal_merge_preserves_strongest_constraints_and_supersedes_duplicates() -> None:
    event = make_event(
        event_id="goal-merge-source",
        content="can you help?",
        channel_type=ChannelType.DM,
    )
    manager = GoalManager()
    first = manager.propose(
        event=event,
        observation=_observation(),
        before=(),
        owner="ryuuko",
    ).after[0]
    second = first.model_copy(
        update={
            "goal_id": "goal:merge-second",
            "priority": 0.9,
            "urgency": 0.4,
            "progress": 0.3,
            "allowed_actions": (
                CandidateActionType.REPLY,
                CandidateActionType.WAIT,
            ),
        }
    )
    timestamp = datetime(2026, 7, 30, 2, 0, tzinfo=UTC)

    transition = manager.merge((first, second), occurred_at=timestamp)
    active = next(goal for goal in transition.after if goal.status is GoalStatus.ACTIVE)
    superseded = next(goal for goal in transition.after if goal.status is GoalStatus.SUPERSEDED)

    assert active.goal_id == second.goal_id
    assert active.priority == 0.9
    assert active.urgency == first.urgency
    assert active.progress == 0.3
    assert superseded.goal_id == first.goal_id
    assert transition.changes[0].reason_code == f"merged_into:{second.goal_id}"


def test_action_policy_records_explainable_scores_and_blocks_permission() -> None:
    event = make_event(
        content="please answer",
        mentions=("agent-001",),
        can_reply=False,
    )
    reply = ActionCandidate(
        candidate_id="candidate-reply",
        action_type=CandidateActionType.REPLY,
        target=ActionTarget(
            conversation_id=event.conversation_id,
            reply_to_event_id=event.event_id,
        ),
        expected_utility=0.9,
        risk=0.1,
        cost=0.1,
        reversibility=0.3,
        social_impact=0.4,
        privacy_impact=0.0,
        goal_fit=0.9,
        drive_effect=0.2,
        value_fit=0.5,
        confidence=0.9,
        required_permission="send_message",
        explanation="Reply candidate.",
    )
    no_action = ActionCandidate(
        candidate_id="candidate-none",
        action_type=CandidateActionType.NO_ACTION,
        target=ActionTarget(conversation_id=event.conversation_id),
        expected_utility=0.1,
        risk=0.0,
        cost=0.0,
        reversibility=1.0,
        social_impact=0.0,
        privacy_impact=0.0,
        goal_fit=0.0,
        drive_effect=0.0,
        value_fit=0.1,
        confidence=1.0,
        explanation="No action fallback.",
    )
    deliberation = DeliberationResult(
        policy_version="test",
        candidates=(reply, no_action),
        proposer="rule_based",
        model_proposals_enabled=False,
    )

    selection = ActionPolicy().select(event=event, deliberation=deliberation)

    score_by_id = {score.candidate_id: score for score in selection.scores}
    assert score_by_id["candidate-reply"].eligible is False
    assert score_by_id["candidate-reply"].total == -1.0
    assert "required_permission_unavailable" in score_by_id["candidate-reply"].reason_codes
    assert selection.selected_candidate_id == "candidate-none"


def test_turn_taking_waits_after_recent_speaking_saturation() -> None:
    event = make_event(content="another direct question", mentions=("agent-001",))
    recent = tuple(
        RecentParticipation(
            position=index,
            event_id=f"prior-{index}",
            outcome=ParticipationOutcome.REPLY,
        )
        for index in range(1, 4)
    )
    observation = ObservationSnapshot(
        conversation_id=event.conversation_id,
        agent_actor_id="agent-001",
        state_version=3,
        recent_participation=recent,
    )
    candidate = ActionCandidate(
        candidate_id="reply",
        action_type=CandidateActionType.REPLY,
        target=ActionTarget(
            conversation_id=event.conversation_id,
            reply_to_event_id=event.event_id,
        ),
        expected_utility=0.8,
        risk=0.1,
        cost=0.2,
        reversibility=0.3,
        social_impact=0.3,
        privacy_impact=0.0,
        goal_fit=0.8,
        drive_effect=0.0,
        value_fit=0.0,
        confidence=0.9,
        required_permission="send_message",
        explanation="reply",
    )

    decision = TurnTakingPolicy().decide(
        event=event,
        observation=observation,
        candidate=candidate,
    )

    assert decision.outcome is TurnTakingOutcome.WAIT
    assert "recent_speaking_saturation" in decision.reason_codes


def test_internal_dynamics_modulate_goal_priority_and_urgency() -> None:
    event = make_event(
        event_id="goal-internal-state",
        content="can you help?",
        channel_type=ChannelType.DM,
    )
    baseline = InternalState.initial("persona:ryuuko")
    pressured = baseline.model_copy(
        update={
            "drives": baseline.drives.model_copy(
                update={"uncertainty_reduction": 1.0, "safety": 1.0}
            ),
            "affect": baseline.affect.model_copy(update={"arousal": 1.0}),
        }
    )
    manager = GoalManager()

    baseline_goal = manager.propose(
        event=event,
        observation=_observation(),
        before=(),
        owner="ryuuko",
        internal=baseline,
    ).after[0]
    pressured_goal = manager.propose(
        event=event,
        observation=_observation(),
        before=(),
        owner="ryuuko",
        internal=pressured,
    ).after[0]

    assert pressured_goal.priority > baseline_goal.priority
    assert pressured_goal.urgency > baseline_goal.urgency


def test_internal_safety_can_defer_an_otherwise_valid_group_join() -> None:
    event = make_event(content="Mọi người có ai biết cách sửa lỗi này không?")
    observation = _observation()
    conversation = ConversationPolicy().project(
        event=event,
        observation=observation,
    )
    baseline = InternalState.initial("persona:ryuuko")
    high_safety = baseline.model_copy(
        update={"drives": baseline.drives.model_copy(update={"safety": 0.9})}
    )
    candidate = ActionCandidate(
        candidate_id="join",
        action_type=CandidateActionType.JOIN,
        target=ActionTarget(conversation_id=event.conversation_id),
        expected_utility=0.8,
        risk=0.1,
        cost=0.2,
        reversibility=0.4,
        social_impact=0.3,
        privacy_impact=0.0,
        goal_fit=0.2,
        drive_effect=0.0,
        value_fit=0.0,
        confidence=0.9,
        required_permission="send_message",
        explanation="join",
    )

    decision = TurnTakingPolicy().decide(
        event=event,
        observation=observation,
        candidate=candidate,
        conversation=conversation,
        internal=high_safety,
    )

    assert decision.outcome is TurnTakingOutcome.WAIT
    assert "internal_safety_or_avoidance_defers_group_join" in decision.reason_codes
