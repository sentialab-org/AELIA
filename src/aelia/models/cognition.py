from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from aelia.contracts.common import NonEmptyId, Provenance, StrictModel


class AppraisalResult(StrictModel):
    policy_version: str
    goal_relevance: Annotated[float, Field(ge=0.0, le=1.0)]
    goal_congruence: Annotated[float, Field(ge=-1.0, le=1.0)]
    value_alignment: Annotated[float, Field(ge=-1.0, le=1.0)]
    novelty: Annotated[float, Field(ge=0.0, le=1.0)]
    certainty: Annotated[float, Field(ge=0.0, le=1.0)]
    controllability: Annotated[float, Field(ge=0.0, le=1.0)]
    social_relevance: Annotated[float, Field(ge=0.0, le=1.0)]
    agency: Annotated[float, Field(ge=-1.0, le=1.0)]
    responsibility: Annotated[float, Field(ge=0.0, le=1.0)]
    expectedness: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: tuple[str, ...]
    provenance: Provenance


class DriveState(StrictModel):
    autonomy: Annotated[float, Field(ge=0.0, le=1.0)]
    social_connection: Annotated[float, Field(ge=0.0, le=1.0)]
    curiosity: Annotated[float, Field(ge=0.0, le=1.0)]
    consistency: Annotated[float, Field(ge=0.0, le=1.0)]
    uncertainty_reduction: Annotated[float, Field(ge=0.0, le=1.0)]
    safety: Annotated[float, Field(ge=0.0, le=1.0)]


class AffectState(StrictModel):
    valence: Annotated[float, Field(ge=-1.0, le=1.0)]
    arousal: Annotated[float, Field(ge=0.0, le=1.0)]
    frustration: Annotated[float, Field(ge=0.0, le=1.0)]
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    control: Annotated[float, Field(ge=-1.0, le=1.0)]
    attachment: Annotated[float, Field(ge=0.0, le=1.0)]
    approach: Annotated[float, Field(ge=-1.0, le=1.0)]


class InternalState(StrictModel):
    state_id: NonEmptyId
    version: Annotated[int, Field(ge=0)]
    drives: DriveState
    affect: AffectState
    last_event_id: NonEmptyId | None = None

    @classmethod
    def initial(cls, state_id: str) -> InternalState:
        return cls(
            state_id=state_id,
            version=0,
            drives=DriveState(
                autonomy=0.3,
                social_connection=0.3,
                curiosity=0.3,
                consistency=0.3,
                uncertainty_reduction=0.4,
                safety=0.3,
            ),
            affect=AffectState(
                valence=0.0,
                arousal=0.2,
                frustration=0.0,
                uncertainty=0.5,
                control=0.0,
                attachment=0.0,
                approach=0.0,
            ),
        )


class DriveDelta(StrictModel):
    autonomy: Annotated[float, Field(ge=-1.0, le=1.0)]
    social_connection: Annotated[float, Field(ge=-1.0, le=1.0)]
    curiosity: Annotated[float, Field(ge=-1.0, le=1.0)]
    consistency: Annotated[float, Field(ge=-1.0, le=1.0)]
    uncertainty_reduction: Annotated[float, Field(ge=-1.0, le=1.0)]
    safety: Annotated[float, Field(ge=-1.0, le=1.0)]


class AffectDelta(StrictModel):
    valence: Annotated[float, Field(ge=-2.0, le=2.0)]
    arousal: Annotated[float, Field(ge=-1.0, le=1.0)]
    frustration: Annotated[float, Field(ge=-1.0, le=1.0)]
    uncertainty: Annotated[float, Field(ge=-1.0, le=1.0)]
    control: Annotated[float, Field(ge=-2.0, le=2.0)]
    attachment: Annotated[float, Field(ge=-1.0, le=1.0)]
    approach: Annotated[float, Field(ge=-2.0, le=2.0)]


class InternalDelta(StrictModel):
    version_before: Annotated[int, Field(ge=0)]
    version_after: Annotated[int, Field(ge=1)]
    drives: DriveDelta
    affect: AffectDelta
    reason_codes: tuple[str, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def validate_versions(self) -> InternalDelta:
        if self.version_after != self.version_before + 1:
            raise ValueError("internal delta must advance state by one version")
        return self


class InternalTransition(StrictModel):
    policy_version: str
    before: InternalState
    delta: InternalDelta
    after: InternalState

    @model_validator(mode="after")
    def validate_state_versions(self) -> InternalTransition:
        if self.before.state_id != self.after.state_id:
            raise ValueError("internal transition state ids must match")
        if self.before.version != self.delta.version_before:
            raise ValueError("internal before version does not match delta")
        if self.after.version != self.delta.version_after:
            raise ValueError("internal after version does not match delta")
        return self


class InternalParticipationInfluence(StrictModel):
    policy_version: str
    score: Annotated[float, Field(ge=-1.0, le=1.0)]
    reason_codes: tuple[str, ...]
