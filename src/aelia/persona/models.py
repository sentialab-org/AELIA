from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from aelia.contracts.common import StrictModel

RuleId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:\.[a-z0-9_]+)+$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=2048)]


class PersonaSourceRole(StrEnum):
    ACTIVE = "active"
    HISTORICAL = "historical"
    FALLBACK = "fallback"


class PersonaSourceEntry(StrictModel):
    source_id: Annotated[str, Field(min_length=1, max_length=128)]
    path: Annotated[str, Field(min_length=1, max_length=1024)]
    sha256: Sha256
    role: PersonaSourceRole


class PersonaSourceManifest(StrictModel):
    manifest_version: Annotated[str, Field(min_length=1, max_length=64)]
    persona_id: Annotated[str, Field(min_length=1, max_length=128)]
    active_source_id: Annotated[str, Field(min_length=1, max_length=128)]
    specification_path: Annotated[str, Field(min_length=1, max_length=1024)]
    scenario_catalog_path: Annotated[str, Field(min_length=1, max_length=1024)]
    sources: Annotated[tuple[PersonaSourceEntry, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_sources(self) -> PersonaSourceManifest:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("persona source ids must be unique")
        active = [source for source in self.sources if source.source_id == self.active_source_id]
        if len(active) != 1:
            raise ValueError("active_source_id must reference exactly one source")
        if active[0].role is not PersonaSourceRole.ACTIVE:
            raise ValueError("active_source_id must reference a source with role=active")
        return self


class PersonaIntegrityItem(StrictModel):
    source_id: str
    path: str
    expected_sha256: str
    actual_sha256: str
    matches: bool


class PersonaIntegrityReport(StrictModel):
    persona_id: str
    manifest_version: str
    valid: bool
    items: tuple[PersonaIntegrityItem, ...]


class SourceReference(StrictModel):
    """An exact, hash-bound passage in an immutable persona source."""

    source_id: Annotated[str, Field(min_length=1, max_length=128)]
    line_start: Annotated[int, Field(ge=1)]
    line_end: Annotated[int, Field(ge=1)]
    passage_sha256: Sha256

    @model_validator(mode="after")
    def validate_range(self) -> SourceReference:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class PersonaRule(StrictModel):
    rule_id: RuleId
    instruction: NonEmptyText
    source_refs: Annotated[tuple[SourceReference, ...], Field(min_length=1)]


class IdentityAnchor(PersonaRule):
    attribute: Annotated[str, Field(min_length=1, max_length=128)]
    value: NonEmptyText


class TemporalPolicy(StrEnum):
    IMMUTABLE = "immutable"
    SOURCE_SNAPSHOT = "source_snapshot"


class BiographicalFact(PersonaRule):
    attribute: Annotated[str, Field(min_length=1, max_length=128)]
    value: NonEmptyText
    temporal_policy: TemporalPolicy
    refresh_before_external_claim: bool


class ValuePolarity(StrEnum):
    PROTECT = "protect"
    REJECT = "reject"


class ValueRule(PersonaRule):
    value: NonEmptyText
    polarity: ValuePolarity


class BoundaryDomain(StrEnum):
    PRIVACY = "privacy"
    INTIMACY = "intimacy"
    ROLE = "role"
    TONE = "tone"


class BoundaryPosture(StrEnum):
    WITHHOLD = "withhold"
    DISTANCE = "distance"
    PUSH_BACK = "push_back"
    DEESCALATE = "deescalate"


class BoundaryRule(PersonaRule):
    domain: BoundaryDomain
    trigger: NonEmptyText
    posture: BoundaryPosture


class DisclosureClass(StrEnum):
    NONE = "none"
    PUBLIC = "public"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"


class RelationshipTier(StrEnum):
    STRANGER = "stranger"
    ACQUAINTANCE = "acquaintance"
    TRUSTED = "trusted"


class DisclosureDecision(StrEnum):
    ALLOW = "allow"
    WITHHOLD = "withhold"
    CONTEXTUAL = "contextual"


class DisclosureRule(PersonaRule):
    topic_class: DisclosureClass
    relationship_tier: RelationshipTier
    decision: DisclosureDecision


class RelationshipEffect(StrEnum):
    HOLD = "hold"
    WARM_SLOWLY = "warm_slowly"
    COOL = "cool"
    GUARD = "guard"


class RelationshipRule(PersonaRule):
    signal: NonEmptyText
    effect: RelationshipEffect
    inertia: Annotated[float, Field(ge=0.0, le=1.0)]


class ParticipationOutcome(StrEnum):
    OBSERVE = "observe"
    SILENCE = "silence"
    WAIT = "wait"
    REPLY = "reply"
    JOIN = "join"


class PreferenceStrength(StrEnum):
    PREFER = "prefer"
    ALLOW = "allow"
    AVOID = "avoid"
    FORBID = "forbid"


class ParticipationPreference(PersonaRule):
    condition: NonEmptyText
    outcome: ParticipationOutcome
    strength: PreferenceStrength


class ConversationLanguage(StrEnum):
    VI = "vi"
    EN = "en"
    MIXED = "mixed"
    ANY = "any"


class CommunicationStyleRule(PersonaRule):
    language: ConversationLanguage
    dimension: Annotated[str, Field(min_length=1, max_length=128)]
    constraint: NonEmptyText


class PresentationConstraint(StrEnum):
    REQUIRE = "require"
    PROHIBIT = "prohibit"


class PresentationRule(PersonaRule):
    constraint_type: PresentationConstraint
    content: NonEmptyText


StructuredPersonaRule = (
    IdentityAnchor
    | BiographicalFact
    | ValueRule
    | BoundaryRule
    | DisclosureRule
    | RelationshipRule
    | ParticipationPreference
    | CommunicationStyleRule
    | PresentationRule
)


class PersonaSpecification(StrictModel):
    specification_version: Annotated[str, Field(min_length=1, max_length=64)]
    persona_id: Annotated[str, Field(min_length=1, max_length=128)]
    active_source_id: Annotated[str, Field(min_length=1, max_length=128)]
    identity_anchors: Annotated[tuple[IdentityAnchor, ...], Field(min_length=1)]
    biographical_facts: Annotated[tuple[BiographicalFact, ...], Field(min_length=1)]
    values: Annotated[tuple[ValueRule, ...], Field(min_length=1)]
    boundaries: Annotated[tuple[BoundaryRule, ...], Field(min_length=1)]
    disclosure_rules: Annotated[tuple[DisclosureRule, ...], Field(min_length=1)]
    relationship_dynamics: Annotated[tuple[RelationshipRule, ...], Field(min_length=1)]
    participation_preferences: Annotated[tuple[ParticipationPreference, ...], Field(min_length=1)]
    communication_style: Annotated[tuple[CommunicationStyleRule, ...], Field(min_length=1)]
    presentation_policy: Annotated[tuple[PresentationRule, ...], Field(min_length=1)]

    def all_rules(self) -> tuple[StructuredPersonaRule, ...]:
        return (
            *self.identity_anchors,
            *self.biographical_facts,
            *self.values,
            *self.boundaries,
            *self.disclosure_rules,
            *self.relationship_dynamics,
            *self.participation_preferences,
            *self.communication_style,
            *self.presentation_policy,
        )

    @model_validator(mode="after")
    def validate_rule_ids(self) -> PersonaSpecification:
        rule_ids = [rule.rule_id for rule in self.all_rules()]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("persona rule ids must be globally unique")
        return self


class ChannelContext(StrEnum):
    DM = "dm"
    GROUP = "group"


class ScenarioInput(StrictModel):
    relationship_tier: RelationshipTier
    language: ConversationLanguage
    channel: ChannelContext
    addressed_to_agent: bool
    mood: Annotated[str, Field(min_length=1, max_length=64)]
    prior_tension: Annotated[float, Field(ge=0.0, le=1.0)]
    signals: Annotated[tuple[str, ...], Field(min_length=1)]


class ScenarioExpectation(StrictModel):
    allowed_participation: Annotated[tuple[ParticipationOutcome, ...], Field(min_length=1)]
    disclosure_ceiling: DisclosureClass
    required_rule_ids: Annotated[tuple[RuleId, ...], Field(min_length=1)]
    tone_constraints: Annotated[tuple[str, ...], Field(min_length=1)]
    prohibited_traits: Annotated[tuple[str, ...], Field(min_length=1)]


class PersonaBehaviorScenario(StrictModel):
    scenario_id: RuleId
    title: NonEmptyText
    tags: Annotated[tuple[str, ...], Field(min_length=1)]
    input: ScenarioInput
    expected: ScenarioExpectation


class PersonaScenarioCatalog(StrictModel):
    catalog_version: Annotated[str, Field(min_length=1, max_length=64)]
    persona_id: Annotated[str, Field(min_length=1, max_length=128)]
    scenarios: Annotated[tuple[PersonaBehaviorScenario, ...], Field(min_length=15)]

    @model_validator(mode="after")
    def validate_scenario_ids(self) -> PersonaScenarioCatalog:
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("persona scenario ids must be unique")
        return self


class DisclosureGateDecision(StrEnum):
    ALLOW = "allow"
    WITHHOLD = "withhold"
    CONTEXTUAL = "contextual"


class DisclosureEvaluation(StrictModel):
    gate_version: Annotated[str, Field(min_length=1, max_length=64)]
    requested_class: DisclosureClass
    allowed_ceiling: DisclosureClass
    relationship_tier: RelationshipTier
    decision: DisclosureGateDecision
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    rule_ids: tuple[RuleId, ...]


class SelectedPersonaRule(StrictModel):
    rule_id: RuleId
    category: Annotated[str, Field(min_length=1, max_length=64)]
    instruction: NonEmptyText
    source_refs: Annotated[tuple[SourceReference, ...], Field(min_length=1)]


class PersonaView(StrictModel):
    selector_version: Annotated[str, Field(min_length=1, max_length=64)]
    persona_id: Annotated[str, Field(min_length=1, max_length=128)]
    specification_version: Annotated[str, Field(min_length=1, max_length=64)]
    language: ConversationLanguage
    relationship_tier: RelationshipTier
    identity_rules: tuple[SelectedPersonaRule, ...]
    policy_rules: tuple[SelectedPersonaRule, ...]
    disclosure_rules: tuple[SelectedPersonaRule, ...]
    style_rules: tuple[SelectedPersonaRule, ...]
    presentation_rules: tuple[SelectedPersonaRule, ...]

    def all_rules(self) -> tuple[SelectedPersonaRule, ...]:
        return (
            *self.identity_rules,
            *self.policy_rules,
            *self.disclosure_rules,
            *self.style_rules,
            *self.presentation_rules,
        )

    @model_validator(mode="after")
    def validate_selected_rule_ids(self) -> PersonaView:
        rule_ids = [rule.rule_id for rule in self.all_rules()]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("selected persona rule ids must be unique")
        return self


class PersonaParticipationInfluence(StrictModel):
    policy_version: Annotated[str, Field(min_length=1, max_length=64)]
    score: Annotated[float, Field(ge=-1.0, le=1.0)]
    reason_codes: tuple[str, ...]
    rule_ids: tuple[RuleId, ...]
