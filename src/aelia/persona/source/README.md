# Persona source package

`archive/` is the byte-for-byte V2 preservation copy of every V1 persona source.
`manifest.json` records their SHA-256 hashes, marks `base.v3` active, and points
to the structured specification and behavioral scenario catalog.

`specification.v1.json` decomposes the active source into versioned rules. Every
rule has one or more 1-indexed, inclusive line references whose exact passage is
SHA-256 bound to the archived source. `scenarios.v1.json` defines behavioral
oracles in terms of participation, disclosure ceilings, tone constraints, and
prohibited traits—not exact generated wording.

V2 code must verify the source file and every referenced passage before exposing
the specification. Treat archived text as immutable evidence: source changes
require a new source ID, specification version, and an explicit behavioral review.
