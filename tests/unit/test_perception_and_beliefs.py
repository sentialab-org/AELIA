from __future__ import annotations

from aelia.cognition.attention import AttentionPolicy
from aelia.cognition.beliefs import BeliefPolicy
from aelia.cognition.perception import PerceptionPolicy
from aelia.contracts.events import ChannelType
from aelia.contracts.observation import ObservationSnapshot
from aelia.models.belief import BeliefSnapshot, BeliefStatus
from aelia.models.perception import EpistemicKind, PerceptionDepth
from tests.helpers import make_event


def _observation() -> ObservationSnapshot:
    return ObservationSnapshot(
        conversation_id="conversation-001",
        agent_actor_id="agent-001",
        state_version=0,
    )


def test_lightweight_observation_does_not_create_claim_or_fact() -> None:
    event = make_event(content="ambient group update")
    attention = AttentionPolicy().evaluate(event, _observation())

    perception = PerceptionPolicy().perceive(event=event, attention=attention)

    assert perception.depth is PerceptionDepth.LIGHTWEIGHT
    assert perception.observed_signals[0].kind is EpistemicKind.OBSERVATION
    assert perception.claim_candidates == ()
    assert "claims_not_promoted_to_facts" in perception.reason_codes


def test_self_report_is_a_hypothesis_not_an_observed_fact() -> None:
    event = make_event(
        content="I am 19 years old",
        channel_type=ChannelType.DM,
    )
    attention = AttentionPolicy().evaluate(event, _observation())

    perception = PerceptionPolicy().perceive(event=event, attention=attention)

    assert perception.depth is PerceptionDepth.DEEP
    assert len(perception.claim_candidates) == 1
    claim = perception.claim_candidates[0]
    assert claim.predicate == "age"
    assert claim.value == "19"
    assert claim.kind is EpistemicKind.HYPOTHESIS
    assert claim.confidence == 0.55


def test_belief_retains_evidence_provenance_and_provisional_status() -> None:
    event = make_event(
        event_id="self-report-001",
        content="I am 19 years old",
        channel_type=ChannelType.DM,
    )
    attention = AttentionPolicy().evaluate(event, _observation())
    perception = PerceptionPolicy().perceive(event=event, attention=attention)
    snapshot = BeliefSnapshot(scope_id="test:user-001", records=())

    transition = BeliefPolicy().transition(
        event=event,
        perception=perception,
        before=snapshot,
    )

    assert len(transition.upserts) == 1
    belief = transition.upserts[0]
    assert belief.status is BeliefStatus.PROVISIONAL
    assert belief.epistemic_kind is EpistemicKind.HYPOTHESIS
    assert belief.evidence[0].event_id == event.event_id
    assert belief.evidence[0].observation_id.endswith(":message_observed")
    assert belief.provenance.source_id == event.event_id
    assert belief.provenance.method == "belief-rules-v1"


def test_conflicting_self_reports_create_bidirectional_contradiction_links() -> None:
    first_event = make_event(
        event_id="age-19",
        content="I am 19 years old",
        channel_type=ChannelType.DM,
    )
    second_event = make_event(
        event_id="age-20",
        content="I am 20 years old",
        channel_type=ChannelType.DM,
    )
    observation = _observation()
    first_perception = PerceptionPolicy().perceive(
        event=first_event,
        attention=AttentionPolicy().evaluate(first_event, observation),
    )
    first = BeliefPolicy().transition(
        event=first_event,
        perception=first_perception,
        before=BeliefSnapshot(scope_id="test:user-001", records=()),
    )
    second_perception = PerceptionPolicy().perceive(
        event=second_event,
        attention=AttentionPolicy().evaluate(second_event, observation),
    )
    second = BeliefPolicy().transition(
        event=second_event,
        perception=second_perception,
        before=BeliefSnapshot(scope_id="test:user-001", records=first.upserts),
    )

    assert len(second.upserts) == 2
    by_value = {belief.value: belief for belief in second.upserts}
    assert by_value["19"].status is BeliefStatus.CONTESTED
    assert by_value["20"].status is BeliefStatus.CONTESTED
    assert by_value["20"].belief_id in by_value["19"].contradiction_links
    assert by_value["19"].belief_id in by_value["20"].contradiction_links
