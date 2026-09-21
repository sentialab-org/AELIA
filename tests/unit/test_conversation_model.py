from __future__ import annotations

from polyverse.cognition.conversation import ConversationPolicy
from polyverse.contracts.events import ReplyReference
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.models.conversation import TurnOwnership
from tests.helpers import make_event


def _observation() -> ObservationSnapshot:
    return ObservationSnapshot(
        conversation_id="conversation-001",
        agent_actor_id="agent-001",
        state_version=0,
    )


def test_open_group_question_is_distinct_from_direct_address() -> None:
    event = make_event(content="Mọi người có ai biết cách sửa lỗi này không?")

    model = ConversationPolicy().project(event=event, observation=_observation())

    assert model.current_event_is_question is True
    assert model.open_invitation is True
    assert model.directed_to_agent is False
    assert model.directed_to_other is False
    assert model.turn_ownership is TurnOwnership.OPEN
    assert model.agent_expected_to_respond is True
    assert model.another_participant_better_positioned is False
    assert model.provenance.source_id == event.event_id


def test_question_directed_to_another_participant_is_not_an_open_invitation() -> None:
    event = make_event(
        content="Có ai biết không?",
        reply_to=ReplyReference(event_id="other-message", actor_id="other-user"),
    )

    model = ConversationPolicy().project(event=event, observation=_observation())

    assert model.open_invitation is False
    assert model.directed_to_other is True
    assert model.turn_ownership is TurnOwnership.OTHER
    assert model.agent_expected_to_respond is False
    assert model.another_participant_better_positioned is True
