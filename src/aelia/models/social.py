from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from aelia.contracts.common import NonEmptyId, Provenance, StrictModel
from aelia.contracts.events import Platform
from aelia.persona.models import RelationshipTier


class SocialState(StrictModel):
    relationship_id: NonEmptyId
    platform: Platform
    actor_id: NonEmptyId
    version: Annotated[int, Field(ge=0)]
    familiarity: Annotated[float, Field(ge=0.0, le=1.0)]
    trust: Annotated[float, Field(ge=-1.0, le=1.0)]
    attachment: Annotated[float, Field(ge=0.0, le=1.0)]
    safety: Annotated[float, Field(ge=-1.0, le=1.0)]
    tension: Annotated[float, Field(ge=0.0, le=1.0)]
    boundary_violations: Annotated[int, Field(ge=0)]
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    interaction_count: Annotated[int, Field(ge=0)]
    last_event_id: NonEmptyId | None = None

    @property
    def tier(self) -> RelationshipTier:
        if (
            self.familiarity >= 0.4
            and self.trust >= 0.6
            and self.safety >= 0.3
            and self.tension <= 0.3
        ):
            return RelationshipTier.TRUSTED
        if self.familiarity >= 0.2 or self.trust >= 0.2:
            return RelationshipTier.ACQUAINTANCE
        return RelationshipTier.STRANGER

    @classmethod
    def unknown(cls, platform: Platform, actor_id: str) -> SocialState:
        return cls(
            relationship_id=f"{platform.value}:{actor_id}",
            platform=platform,
            actor_id=actor_id,
            version=0,
            familiarity=0.0,
            trust=0.0,
            attachment=0.0,
            safety=0.0,
            tension=0.0,
            boundary_violations=0,
            uncertainty=1.0,
            interaction_count=0,
        )


class SocialDelta(StrictModel):
    relationship_id: NonEmptyId
    version_before: Annotated[int, Field(ge=0)]
    version_after: Annotated[int, Field(ge=1)]
    familiarity_delta: Annotated[float, Field(ge=-1.0, le=1.0)]
    trust_delta: Annotated[float, Field(ge=-1.0, le=1.0)]
    attachment_delta: Annotated[float, Field(ge=-1.0, le=1.0)]
    safety_delta: Annotated[float, Field(ge=-1.0, le=1.0)]
    tension_delta: Annotated[float, Field(ge=-1.0, le=1.0)]
    boundary_violations_delta: Annotated[int, Field(ge=0)]
    uncertainty_delta: Annotated[float, Field(ge=-1.0, le=1.0)]
    reason_codes: tuple[str, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def validate_versions(self) -> SocialDelta:
        if self.version_after != self.version_before + 1:
            raise ValueError("social delta must advance state by exactly one version")
        return self


class SocialTransition(StrictModel):
    before: SocialState
    delta: SocialDelta
    after: SocialState

    @model_validator(mode="after")
    def validate_transition(self) -> SocialTransition:
        if self.before.relationship_id != self.after.relationship_id:
            raise ValueError("social transition relationship ids must match")
        if self.delta.relationship_id != self.before.relationship_id:
            raise ValueError("social delta relationship id must match state")
        if self.delta.version_before != self.before.version:
            raise ValueError("social delta before version must match state")
        if self.delta.version_after != self.after.version:
            raise ValueError("social delta after version must match state")
        return self
