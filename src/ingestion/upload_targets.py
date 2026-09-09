"""Runtime-only direct and worksheet upload targets with exact state ownership."""

from dataclasses import dataclass
from pathlib import Path
from src.ingestion.manifest import VDRManifest, VDRFileRecord, WorksheetSearchArtifact
from src.ingestion.manifest_persistence import derive_manifest_paths
from src.ingestion.paths import resolve_relative, managed_path
from src.ingestion.excel_preprocessing import file_sha256


@dataclass(frozen=True)
class UploadTargetKey:
    source_relative_path: str
    artifact_id: str | None = None


@dataclass(frozen=True)
class UploadTarget:
    key: UploadTargetKey
    source: VDRFileRecord
    artifact: WorksheetSearchArtifact | None
    local_path: Path
    display_label: str

    @property
    def state_owner(self):
        return self.artifact if self.artifact is not None else self.source


def enumerate_upload_targets(manifest: VDRManifest, root) -> tuple[UploadTarget, ...]:
    paths = derive_manifest_paths(root)
    targets = []
    for source in sorted(
        manifest.files, key=lambda f: (f.relative_path.casefold(), f.relative_path)
    ):
        if source.classification_status == "supported":
            targets.append(
                UploadTarget(
                    UploadTargetKey(source.relative_path),
                    source,
                    None,
                    resolve_relative(paths.vdr_folder, source.relative_path),
                    source.relative_path,
                )
            )
        elif (
            source.classification_status == "preprocess"
            and source.excel_preprocessing
            and source.excel_preprocessing.status == "completed"
        ):
            for artifact in sorted(
                source.derived_artifacts,
                key=lambda a: (a.worksheet_index, a.artifact_id),
            ):
                targets.append(
                    UploadTarget(
                        UploadTargetKey(source.relative_path, artifact.artifact_id),
                        source,
                        artifact,
                        managed_path(
                            paths.vdr_folder,
                            paths.assistant_folder,
                            artifact.proxy_relative_path,
                        ),
                        f"{source.relative_path} → {artifact.worksheet_name}",
                    )
                )
    return tuple(targets)


def target_for_key(manifest, root, key):
    matches = [t for t in enumerate_upload_targets(manifest, root) if t.key == key]
    if len(matches) != 1:
        raise ValueError("Upload target is missing or ambiguous.")
    return matches[0]


def preflight_target(root, target):
    if target.artifact is None:
        from src.ingestion.upload_workflow import preflight_manifest_record

        return preflight_manifest_record(root, target.source)
    try:
        artifact = target.artifact
        paths = derive_manifest_paths(root)
        path = managed_path(
            paths.vdr_folder, paths.assistant_folder, artifact.proxy_relative_path
        )
        prep = target.source.excel_preprocessing
        expected = f"derived/excel/{prep.generation_id}/sheet_{artifact.worksheet_index:03d}.md"
        if (
            prep.status != "completed"
            or artifact.proxy_relative_path != expected
            or "/.attempts/" in artifact.proxy_relative_path
        ):
            return None, "Artifact is not in its completed generation."
        if not path.is_file():
            return None, "Worksheet proxy is missing or not a regular file."
        if (
            path.stat().st_size != artifact.size_bytes
            or file_sha256(path) != artifact.artifact_sha256
        ):
            return None, "Worksheet proxy integrity check failed."
        return path, None
    except (OSError, ValueError):
        return None, "Worksheet proxy is unsafe or unreadable."
