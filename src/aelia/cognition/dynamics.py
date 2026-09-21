from __future__ import annotations

from aelia.contracts.common import Provenance, ProvenanceKind
from aelia.contracts.events import InboundEvent
from aelia.models.cognition import (
    AffectDelta,
    AffectState,
    AppraisalResult,
    DriveDelta,
    DriveState,
    InternalDelta,
    InternalParticipationInfluence,
    InternalState,
    InternalTransition,
)
from aelia.models.perception import PerceptionResult
from aelia.models.social import SocialTransition

INTERNAL_DYNAMICS_POLICY_VERSION = "internal-dynamics-v1"
INTERNAL_PARTICIPATION_POLICY_VERSION = "internal-participation-v1"


class InternalDynamicsPolicy:
    def transition(
        self,
        *,
        event: InboundEvent,
        before: InternalState,
        perception: PerceptionResult,
        appraisal: AppraisalResult,
        social: SocialTransition,
    ) -> InternalTransition:
        negative_alignment = max(0.0, -appraisal.value_alignment)
        low_control = 1.0 - appraisal.controllability
        drives = DriveState(
            autonomy=self._drive(
                before.drives.autonomy,
                baseline=0.3,
                stimulus=negative_alignment * 0.12,
            ),
            social_connection=self._drive(
                before.drives.social_connection,
                baseline=0.3,
                stimulus=appraisal.social_relevance * 0.02 - social.after.tension * 0.04,
            ),
            curiosity=self._drive(
                before.drives.curiosity,
                baseline=0.3,
                stimulus=appraisal.novelty * 0.05,
            ),
            consistency=self._drive(
                before.drives.consistency,
                baseline=0.3,
                stimulus=negative_alignment * 0.08,
            ),
            uncertainty_reduction=self._drive(
                before.drives.uncertainty_reduction,
                baseline=0.4,
                stimulus=perception.uncertainty * 0.06,
            ),
            safety=self._drive(
                before.drives.safety,
                baseline=0.3,
                stimulus=negative_alignment * 0.10
                + social.after.tension * 0.08
                + low_control * 0.04,
            ),
        )

        target_valence = max(-1.0, min(0.5, appraisal.value_alignment))
        target_arousal = min(1.0, appraisal.novelty * 0.6 + social.after.tension * 0.6)
        target_frustration = min(
            1.0,
            negative_alignment * 0.7 + low_control * 0.2 + social.after.tension * 0.4,
        )
        target_control = appraisal.controllability * 2.0 - 1.0
        target_approach = max(
            -1.0,
            min(
                1.0,
                social.after.trust * 0.5 + social.after.safety * 0.4 - social.after.tension * 0.8,
            ),
        )
        affect = AffectState(
            valence=self._affect(before.affect.valence, target_valence, -1.0, 1.0),
            arousal=self._affect(before.affect.arousal, target_arousal, 0.0, 1.0),
            frustration=self._affect(
                before.affect.frustration,
                target_frustration,
                0.0,
                1.0,
            ),
            uncertainty=self._affect(
                before.affect.uncertainty,
                perception.uncertainty,
                0.0,
                1.0,
            ),
            control=self._affect(before.affect.control, target_control, -1.0, 1.0),
            attachment=self._affect(
                before.affect.attachment,
                social.after.attachment,
                0.0,
                1.0,
            ),
            approach=self._affect(before.affect.approach, target_approach, -1.0, 1.0),
        )
        after = InternalState(
            state_id=before.state_id,
            version=before.version + 1,
            drives=drives,
            affect=affect,
            last_event_id=event.event_id,
        )
        delta = InternalDelta(
            version_before=before.version,
            version_after=after.version,
            drives=DriveDelta(
                **self._differences(before.drives, after.drives),
            ),
            affect=AffectDelta(
                **self._differences(before.affect, after.affect),
            ),
            reason_codes=(
                "drive_decay_and_stimulus_applied",
                "affect_inertia_applied",
                "internal_state_precedes_participation",
            ),
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=INTERNAL_DYNAMICS_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )
        return InternalTransition(
            policy_version=INTERNAL_DYNAMICS_POLICY_VERSION,
            before=before,
            delta=delta,
            after=after,
        )

    @staticmethod
    def _drive(current: float, *, baseline: float, stimulus: float) -> float:
        decayed = current + (baseline - current) * 0.05
        return round(max(0.0, min(1.0, decayed + stimulus)), 6)

    @staticmethod
    def _affect(current: float, target: float, minimum: float, maximum: float) -> float:
        updated = current * 0.85 + target * 0.15
        return round(max(minimum, min(maximum, updated)), 6)

    @staticmethod
    def _differences(
        before: DriveState | AffectState,
        after: DriveState | AffectState,
    ) -> dict[str, float]:
        return {
            key: round(float(after_value) - float(before_values[key]), 6)
            for key, after_value in after.model_dump().items()
            if isinstance(after_value, int | float)
            for before_values in (before.model_dump(),)
        }


class InternalParticipationPolicy:
    def evaluate(self, state: InternalState) -> InternalParticipationInfluence:
        score = (
            state.affect.approach * 0.10
            - state.affect.frustration * 0.15
            - state.affect.uncertainty * 0.05
            - max(0.0, state.drives.safety - 0.3) * 0.10
        )
        return InternalParticipationInfluence(
            policy_version=INTERNAL_PARTICIPATION_POLICY_VERSION,
            score=round(max(-1.0, min(1.0, score)), 6),
            reason_codes=(
                "affect_modulates_participation",
                "safety_drive_modulates_participation",
            ),
        )
