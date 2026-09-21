# ADR 0009: Use rebuildable context models and an explicit group-join path

- Status: Accepted
- Date: 2026-07-30

## Context

The V2 report requires World and Conversation Models to affect attention,
participation, and turn-taking. The existing buffer and belief tables contained
the necessary canonical evidence, but the cycle exposed no explicit projection.
The participation schema also named `join` while policy could never select or
execute it.

Adding new canonical stores would duplicate events, beliefs, permissions, and
conversation state. Treating every unaddressed question as an invitation would
also conflict with Ryuuko's observe-first behavior and create group spam.

## Decision

Build two typed, provenance-bearing projections inside the deterministic cycle:

- Conversation Model derives turn ownership, open invitation, question state,
  active speakers, and topic terms from the current event and bounded buffer.
- World Model derives entities, platform capabilities, hypotheses, belief
  references, and immediate predictions from canonical events and beliefs.

Both models are stored in the cycle trace and as artifacts, but are explicitly
rebuildable rather than new sources of truth. World capabilities inform
appraisal controllability. Conversation state informs attention, participation,
and turn-taking.

Enable `join` only when all of these are true:

- the event is a question in a group/channel/thread;
- its language marks an open invitation;
- it is not directed to the agent or another participant;
- full attention survives recent-participation penalties;
- send/reply permissions exist;
- action policy selects the join candidate; and
- turn-taking still permits speech.

`reply` and `join` have distinct action target semantics. Their action/trace
contracts are version `2.1.0`; adapter outbound command and receipt contracts are
version `1.1.0`. Inbound event/envelope versions remain `2.0.0` and `1.0.0`.

## Consequences

Group participation is now an explicit, replayable policy result without making
message count or generic question detection sufficient to speak. Questions
owned by another participant remain observed. A recent join lowers subsequent
attention, providing an early anti-spam control.

Context can later become more sophisticated without a data migration: the
projections can be rebuilt from canonical records, and contract version changes
remain isolated by direction.
