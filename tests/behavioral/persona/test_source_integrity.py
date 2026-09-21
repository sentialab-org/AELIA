from __future__ import annotations

from pathlib import Path

from aelia.persona.loader import PersonaSourceLoader

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "src/aelia/persona/source/manifest.json"


def test_loader_derives_repository_root_without_an_explicit_hint() -> None:
    """The production path: every call site omits ``repository_root``.

    The suite otherwise passes the root explicitly everywhere, which would keep
    the suite green even if the derivation walked to the wrong directory.
    """
    loader = PersonaSourceLoader(MANIFEST_PATH)

    assert loader.repository_root == PROJECT_ROOT
    assert loader.verify_sources().valid is True


def test_all_persona_sources_match_recorded_hashes() -> None:
    loader = PersonaSourceLoader(MANIFEST_PATH, repository_root=PROJECT_ROOT)

    report = loader.verify_sources()

    assert report.valid is True
    assert len(report.items) == 4
    assert all(item.matches for item in report.items)


def test_v2_archive_is_byte_for_byte_equal_to_v1_sources() -> None:
    source_pairs = (
        (
            "legacy/v1-rust/prompts/persona/base.txt",
            "src/aelia/persona/source/archive/base.v1.txt",
        ),
        (
            "legacy/v1-rust/prompts/persona/base.v2.txt",
            "src/aelia/persona/source/archive/base.v2.txt",
        ),
        (
            "legacy/v1-rust/prompts/persona/base.v3.txt",
            "src/aelia/persona/source/archive/base.v3.txt",
        ),
        (
            "legacy/v1-rust/prompts/persona/fallback_short.txt",
            "src/aelia/persona/source/archive/fallback.short.txt",
        ),
    )

    for original_path, archive_path in source_pairs:
        assert (PROJECT_ROOT / archive_path).read_bytes() == (
            PROJECT_ROOT / original_path
        ).read_bytes()


def test_active_persona_is_archived_base_v3_without_transformation() -> None:
    loader = PersonaSourceLoader(MANIFEST_PATH, repository_root=PROJECT_ROOT)

    active_source = loader.load_active_source()
    canonical_source = (PROJECT_ROOT / "legacy/v1-rust/prompts/persona/base.v3.txt").read_text(
        encoding="utf-8"
    )

    assert active_source == canonical_source
    assert active_source.startswith("Mày là Ryuuko.")


def test_structured_rules_are_hash_bound_to_active_source_passages() -> None:
    loader = PersonaSourceLoader(MANIFEST_PATH, repository_root=PROJECT_ROOT)

    specification = loader.load_specification()

    assert specification.persona_id == "ryuuko"
    assert specification.active_source_id == "base.v3"
    assert len(specification.all_rules()) >= 15
    assert all(rule.source_refs for rule in specification.all_rules())
    assert all(
        source_ref.source_id == specification.active_source_id
        for rule in specification.all_rules()
        for source_ref in rule.source_refs
    )
