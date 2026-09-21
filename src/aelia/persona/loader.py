from __future__ import annotations

import hashlib
from pathlib import Path

from aelia.persona.models import (
    PersonaIntegrityItem,
    PersonaIntegrityReport,
    PersonaScenarioCatalog,
    PersonaSourceEntry,
    PersonaSourceManifest,
    PersonaSpecification,
    SourceReference,
)


class PersonaIntegrityError(RuntimeError):
    pass


class PersonaSourceLoader:
    def __init__(self, manifest_path: Path, repository_root: Path | None = None) -> None:
        self.manifest_path = manifest_path
        self.repository_root = (
            repository_root.resolve() if repository_root else self._find_repository_root()
        )

    def load_manifest(self) -> PersonaSourceManifest:
        raw = self.manifest_path.read_text(encoding="utf-8")
        return PersonaSourceManifest.model_validate_json(raw)

    def verify_sources(self) -> PersonaIntegrityReport:
        manifest = self.load_manifest()
        items = tuple(self._verify_source(source) for source in manifest.sources)
        return PersonaIntegrityReport(
            persona_id=manifest.persona_id,
            manifest_version=manifest.manifest_version,
            valid=all(item.matches for item in items),
            items=items,
        )

    def load_active_source(self) -> str:
        manifest = self.load_manifest()
        source = next(
            source for source in manifest.sources if source.source_id == manifest.active_source_id
        )
        item = self._verify_source(source)
        if not item.matches:
            raise PersonaIntegrityError(
                f"persona source integrity check failed for {source.source_id}"
            )
        return self._resolve_source_path(source).read_text(encoding="utf-8")

    def load_specification(self) -> PersonaSpecification:
        manifest = self.load_manifest()
        path = self._resolve_repository_path(manifest.specification_path)
        specification = PersonaSpecification.model_validate_json(path.read_text(encoding="utf-8"))
        if specification.persona_id != manifest.persona_id:
            raise PersonaIntegrityError("persona specification persona_id does not match manifest")
        if specification.active_source_id != manifest.active_source_id:
            raise PersonaIntegrityError(
                "persona specification active_source_id does not match manifest"
            )

        source_by_id = {source.source_id: source for source in manifest.sources}
        for rule in specification.all_rules():
            for source_ref in rule.source_refs:
                if source_ref.source_id != manifest.active_source_id:
                    raise PersonaIntegrityError(
                        f"persona rule {rule.rule_id} does not reference the active source"
                    )
                self._verify_source_reference(source_ref, source_by_id)
        return specification

    def load_scenario_catalog(self) -> PersonaScenarioCatalog:
        manifest = self.load_manifest()
        path = self._resolve_repository_path(manifest.scenario_catalog_path)
        catalog = PersonaScenarioCatalog.model_validate_json(path.read_text(encoding="utf-8"))
        if catalog.persona_id != manifest.persona_id:
            raise PersonaIntegrityError(
                "persona scenario catalog persona_id does not match manifest"
            )

        specification = self.load_specification()
        rule_ids = {rule.rule_id for rule in specification.all_rules()}
        for scenario in catalog.scenarios:
            unknown_rule_ids = set(scenario.expected.required_rule_ids) - rule_ids
            if unknown_rule_ids:
                unknown = ", ".join(sorted(unknown_rule_ids))
                raise PersonaIntegrityError(
                    f"persona scenario {scenario.scenario_id} references unknown rules: {unknown}"
                )
        return catalog

    def _verify_source(self, source: PersonaSourceEntry) -> PersonaIntegrityItem:
        path = self._resolve_source_path(source)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        return PersonaIntegrityItem(
            source_id=source.source_id,
            path=source.path,
            expected_sha256=source.sha256,
            actual_sha256=actual,
            matches=actual == source.sha256,
        )

    def _verify_source_reference(
        self,
        source_ref: SourceReference,
        source_by_id: dict[str, PersonaSourceEntry],
    ) -> None:
        source = source_by_id.get(source_ref.source_id)
        if source is None:
            raise PersonaIntegrityError(
                f"persona source reference is unknown: {source_ref.source_id}"
            )

        integrity = self._verify_source(source)
        if not integrity.matches:
            raise PersonaIntegrityError(
                f"persona source integrity check failed for {source.source_id}"
            )

        lines = self._resolve_source_path(source).read_bytes().splitlines(keepends=True)
        if source_ref.line_end > len(lines):
            raise PersonaIntegrityError(
                f"persona source reference exceeds {source.source_id}: "
                f"{source_ref.line_start}-{source_ref.line_end}"
            )
        passage = b"".join(lines[source_ref.line_start - 1 : source_ref.line_end])
        actual_sha256 = hashlib.sha256(passage).hexdigest()
        if actual_sha256 != source_ref.passage_sha256:
            raise PersonaIntegrityError(
                f"persona passage hash mismatch for {source.source_id}:"
                f"{source_ref.line_start}-{source_ref.line_end}"
            )

    def _resolve_source_path(self, source: PersonaSourceEntry) -> Path:
        return self._resolve_repository_path(source.path)

    def _resolve_repository_path(self, relative_path: str) -> Path:
        path = (self.repository_root / relative_path).resolve()
        try:
            path.relative_to(self.repository_root)
        except ValueError as exc:
            raise PersonaIntegrityError(
                f"persona path escapes repository root: {relative_path}"
            ) from exc
        if not path.is_file():
            raise PersonaIntegrityError(f"persona path does not exist: {relative_path}")
        return path

    def _find_repository_root(self) -> Path:
        start = self.manifest_path.resolve().parent
        for directory in (start, *start.parents):
            is_v2_root = (directory / "pyproject.toml").is_file() and (
                directory / "src" / "aelia" / "persona" / "source"
            ).is_dir()
            is_legacy_root = (directory / "Cargo.toml").is_file() and (
                directory / "prompts" / "persona"
            ).is_dir()
            if is_v2_root or is_legacy_root:
                return directory
        raise PersonaIntegrityError("could not locate AELIA repository root")
