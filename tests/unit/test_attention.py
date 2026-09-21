from __future__ import annotations

from polyverse.cognition.attention import AttentionPolicy
from polyverse.contracts.events import ChannelType, ReplyReference
from polyverse.contracts.observation import ObservationSnapshot, RecentParticipation
from polyverse.contracts.participation import (
    AttentionLevel,
    ParticipationOutcome,
    ProcessingMode,
)
from polyverse.models.cognition import InternalState
from tests.helpers import make_event

AGENT_ID = "agent-001"


def _snapshot(
    *,
    participation: tuple[RecentParticipation, ...] = (),
) -> ObservationSnapshot:
    return ObservationSnapshot(
        conversation_id="conversation-001",
        agent_actor_id=AGENT_ID,
        state_version=len(participation),
        recent_participation=participation,
    )


def test_direct_mention_triggers_full_attention_with_traceable_score() -> None:
    event = make_event(content="can you look at this?", mentions=(AGENT_ID,))

    result = AttentionPolicy().evaluate(event, _snapshot())

    assert result.level is AttentionLevel.HIGH
    assert result.processing_mode is ProcessingMode.FULL
    assert result.score_breakdown.direct_mention == 0.85
    assert result.score_breakdown.total == 0.85
    assert "direct_mention" in result.reason_codes
    assert "no_goal_domain_relevance_signal" in result.reason_codes


def test_ambient_group_message_stays_lightweight() -> None:
    event = make_event(content="the build finished")

    result = AttentionPolicy().evaluate(event, _snapshot())

    assert result.level is AttentionLevel.LOW
    assert result.processing_mode is ProcessingMode.LIGHTWEIGHT
    assert result.score_breakdown.total == 0.0


def test_dm_and_reply_to_agent_are_explicit_positive_signals() -> None:
    dm = make_event(channel_type=ChannelType.DM, content="can we talk?")
    reply = make_event(
        event_id="event-reply",
        content="following up",
        reply_to=ReplyReference(event_id="agent-message", actor_id=AGENT_ID),
    )

    dm_result = AttentionPolicy().evaluate(dm, _snapshot())
    reply_result = AttentionPolicy().evaluate(reply, _snapshot())

    assert dm_result.score_breakdown.direct_message == 0.70
    assert dm_result.processing_mode is ProcessingMode.FULL
    assert reply_result.score_breakdown.reply_to_agent == 0.80
    assert reply_result.processing_mode is ProcessingMode.FULL


def test_recent_replies_penalize_repeated_participation() -> None:
    recent = tuple(
        RecentParticipation(
            position=index,
            event_id=f"prior-{index}",
            outcome=ParticipationOutcome.REPLY,
        )
        for index in range(1, 4)
    )
    event = make_event(content="another thing", mentions=(AGENT_ID,))

    result = AttentionPolicy().evaluate(event, _snapshot(participation=recent))

    assert result.score_breakdown.recent_participation_penalty == -0.45
    assert result.score_breakdown.total == 0.40
    assert result.level is AttentionLevel.MEDIUM
    assert result.processing_mode is ProcessingMode.LIGHTWEIGHT


def test_reply_chain_owned_by_others_is_deprioritized() -> None:
    event = make_event(
        content="yeah I agree",
        reply_to=ReplyReference(event_id="other-message", actor_id="other-user"),
    )

    result = AttentionPolicy().evaluate(event, _snapshot())

    assert result.score_breakdown.conversation_owned_by_others == -0.65
    assert result.level is AttentionLevel.LOW
    assert "conversation_owned_by_others" in result.reason_codes


def test_prior_internal_state_causally_modulates_attention() -> None:
    event = make_event(content="can you look at this?", mentions=(AGENT_ID,))
    baseline = InternalState.initial("persona:ryuuko")
    defensive = baseline.model_copy(
        update={
            "drives": baseline.drives.model_copy(update={"safety": 1.0}),
            "affect": baseline.affect.model_copy(update={"frustration": 1.0}),
        }
    )

    baseline_result = AttentionPolicy().evaluate(
        event,
        _snapshot(),
        internal=baseline,
    )
    defensive_result = AttentionPolicy().evaluate(
        event,
        _snapshot(),
        internal=defensive,
    )

    assert baseline_result.score_breakdown.internal_dynamics > 0.0
    assert defensive_result.score_breakdown.internal_dynamics < 0.0
    assert defensive_result.score_breakdown.total < baseline_result.score_breakdown.total
    assert "prior_internal_state_modulates_attention" in defensive_result.reason_codes
