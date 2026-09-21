from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import Field

from aelia.contracts.common import StrictModel
from aelia.persona.models import PersonaSpecification


class SelfIdentityAnchor(StrictModel):
    rule_id: str
    attribute: str
    value: str


class SelfValue(StrictModel):
    rule_id: str
    value: str
    polarity: str


class SelfBelief(StrictModel):
    belief_id: str
    statement: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    source_rule_ids: tuple[str, ...]


class RuntimeCapability(StrictModel):
    capability_id: str
    description: str
    available: bool
    provenance: str


class SelfModel(StrictModel):
    model_version: str
    persona_id: str
    persona_specification_version: str
    identity_fingerprint: str
    identity_anchors: tuple[SelfIdentityAnchor, ...]
    values: tuple[SelfValue, ...]
    capabilities: tuple[RuntimeCapability, ...]
    limitations: tuple[RuntimeCapability, ...]
    commitments: tuple[str, ...]
    slow_changing_beliefs: tuple[SelfBelief, ...]


class SelfModelBuilder:
    """Builds immutable self state from persona evidence and runtime facts."""

    @staticmethod
    def build(specification: PersonaSpecification) -> SelfModel:
        identity_anchors = tuple(
            SelfIdentityAnchor(
                rule_id=anchor.rule_id,
                attribute=anchor.attribute,
                value=anchor.value,
            )
            for anchor in specification.identity_anchors
        )
        values = tuple(
            SelfValue(
                rule_id=value.rule_id,
                value=value.value,
                polarity=value.polarity.value,
            )
            for value in specification.values
        )
        fingerprint_payload = {
            "persona_id": specification.persona_id,
            "specification_version": specification.specification_version,
            "identity_anchors": [anchor.model_dump(mode="json") for anchor in identity_anchors],
            "values": [value.model_dump(mode="json") for value in values],
        }
        identity_fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        return SelfModel(
            model_version="self-model-v1",
            persona_id=specification.persona_id,
            persona_specification_version=specification.specification_version,
            identity_fingerprint=identity_fingerprint,
            identity_anchors=identity_anchors,
            values=values,
            capabilities=(
                RuntimeCapability(
                    capability_id="capability.observe",
                    description="Observe and persist normalized inbound events.",
                    available=True,
                    provenance="runtime:v2-003",
                ),
                RuntimeCapability(
                    capability_id="capability.reply_plan",
                    description="Create a structured reply content plan.",
                    available=True,
                    provenance="runtime:v2-003",
                ),
            ),
            limitations=(
                RuntimeCapability(
                    capability_id="limitation.no_live_language_model",
                    description="No live language model is enabled in this phase.",
                    available=False,
                    provenance="runtime:v2-003",
                ),
                RuntimeCapability(
                    capability_id="limitation.no_external_side_effect",
                    description="Execution is simulated and cannot send a platform message.",
                    available=False,
                    provenance="runtime:v2-003",
                ),
            ),
            commitments=(),
            slow_changing_beliefs=(
                SelfBelief(
                    belief_id="self.autonomy",
                    statement="Usefulness to others is a choice, not an identity obligation.",
                    confidence=1.0,
                    source_rule_ids=("value.autonomy", "value.authenticity"),
                ),
                SelfBelief(
                    belief_id="self.trust_opens_slowly",
                    statement="Trust and openness should be earned gradually.",
                    confidence=1.0,
                    source_rule_ids=(
                        "relationship.closeness_earned",
                        "relationship.observe_first",
                    ),
                ),
            ),
        )
