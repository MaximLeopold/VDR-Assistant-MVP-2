"""Manifest v2: original-source inventory and worksheet search artifacts."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from src.ingestion.paths import safe_relative_path


class RemoteState(BaseModel):
    openai_file_id: str | None = None
    upload_status: Literal["not_uploaded", "uploading", "uploaded", "failed"] = (
        "not_uploaded"
    )
    indexing_status: Literal["not_started", "in_progress", "completed", "failed"] = (
        "not_started"
    )
    upload_attempts: int = Field(default=0, ge=0)
    last_error: str | None = None

    def is_neutral(self) -> bool:
        return (
            self.openai_file_id is None
            and self.upload_status == "not_uploaded"
            and self.indexing_status == "not_started"
            and self.upload_attempts == 0
            and self.last_error is None
        )


class WorksheetCoverage(BaseModel):
    worksheet_name: str = Field(min_length=1)
    worksheet_index: int = Field(ge=1)
    outcome: Literal["included", "excluded"]
    reason: str


class ExcelPreprocessing(BaseModel):
    status: Literal["pending", "processing", "completed", "failed", "excluded"] = (
        "pending"
    )
    source_sha256: str | None = None
    transformation_version: str | None = None
    generation_id: str | None = None
    last_error: str | None = None
    exclusion_reason: str | None = None
    worksheets: list[WorksheetCoverage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lifecycle(self):
        if self.status == "excluded" and not (self.exclusion_reason or "").strip():
            raise ValueError("Excluded workbook requires a nonblank exclusion reason.")
        if self.status == "completed":
            if not all(
                (self.source_sha256, self.transformation_version, self.generation_id)
            ):
                raise ValueError(
                    "Completed preprocessing requires source and generation identity."
                )
            indices = [s.worksheet_index for s in self.worksheets]
            names = [s.worksheet_name for s in self.worksheets]
            if (
                not indices
                or indices != list(range(1, len(indices) + 1))
                or len(set(names)) != len(names)
            ):
                raise ValueError(
                    "Completed preprocessing requires complete ordered worksheet coverage."
                )
        return self


class WorksheetSearchArtifact(RemoteState):
    artifact_id: str = Field(min_length=1)
    worksheet_name: str = Field(min_length=1)
    worksheet_index: int = Field(ge=1)
    proxy_relative_path: str
    size_bytes: int = Field(ge=0)
    artifact_sha256: str = Field(min_length=1)
    _safe_path = field_validator("proxy_relative_path")(safe_relative_path)


class VDRFileRecord(RemoteState):
    relative_path: str
    filename: str
    extension: str
    size_bytes: int = Field(ge=0)
    classification_status: Literal[
        "supported", "preprocess", "unsupported", "ignored", "error"
    ]
    classification_reason: str
    excel_preprocessing: ExcelPreprocessing | None = None
    derived_artifacts: list[WorksheetSearchArtifact] = Field(default_factory=list)
    _safe_path = field_validator("relative_path")(safe_relative_path)

    @model_validator(mode="after")
    def validate_excel(self):
        if self.classification_status != "preprocess":
            if self.excel_preprocessing is not None or self.derived_artifacts:
                raise ValueError(
                    "Only preprocess workbooks may contain Excel generation data."
                )
            if (
                self.classification_status == "supported"
                and self.extension.lower() == ".xlsx"
            ):
                raise ValueError("An xlsx workbook must never be directly uploaded.")
            return self
        if self.extension.lower() != ".xlsx" or not self.is_neutral():
            raise ValueError(
                "Preprocess parent must be xlsx with neutral direct remote state."
            )
        prep = self.excel_preprocessing
        if prep is None or prep.status != "completed":
            if self.derived_artifacts:
                raise ValueError(
                    "Incomplete or excluded preprocessing cannot have upload artifacts."
                )
            return self
        included = {
            (s.worksheet_index, s.worksheet_name)
            for s in prep.worksheets
            if s.outcome == "included"
        }
        actual = [(a.worksheet_index, a.worksheet_name) for a in self.derived_artifacts]
        if len(actual) != len(set(actual)) or set(actual) != included:
            raise ValueError(
                "Included worksheet must have exactly one artifact; excluded must have none."
            )
        for artifact in self.derived_artifacts:
            expected = f"derived/excel/{prep.generation_id}/sheet_{artifact.worksheet_index:03d}.md"
            if artifact.proxy_relative_path != expected:
                raise ValueError(
                    "Artifact path must identify the completed generation."
                )
        return self


class VDRManifest(BaseModel):
    schema_version: Literal[2]
    case_name: str
    root_path: str | None = None
    vector_store_id: str | None = None
    snapshot_state: Literal["preparing", "sealed"] = "preparing"
    created_at: datetime
    updated_at: datetime
    files: list[VDRFileRecord]

    @model_validator(mode="after")
    def validate_identity(self):
        paths = [f.relative_path.casefold() for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate original relative paths.")
        artifacts = [a for f in self.files for a in f.derived_artifacts]
        ids = [a.artifact_id for a in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate artifact IDs.")
        remote_ids = [
            r.openai_file_id.strip()
            for r in [*self.files, *artifacts]
            if r.openai_file_id and r.openai_file_id.strip()
        ]
        if len(remote_ids) != len(set(remote_ids)):
            raise ValueError("Duplicate OpenAI file IDs.")
        return self

    @property
    def total_files(self):
        return len(self.files)

    def count(self, status: str) -> int:
        return sum(f.classification_status == status for f in self.files)

    supported_files = property(lambda self: self.count("supported"))
    preprocess_files = property(lambda self: self.count("preprocess"))
    unsupported_files = property(lambda self: self.count("unsupported"))
    ignored_files = property(lambda self: self.count("ignored"))
    error_files = property(lambda self: self.count("error"))
