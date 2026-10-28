# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Row-level CSV source ingestion, stable identity, and evidence projection."""

# ruff: noqa: TRY003

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TextEvidence


class CSVRowError(ValueError):
    """Raised when CSV document or row data fails validation or parsing."""


class CSVDocumentInput(BaseModel):
    """Input payload representing an offline CSV document for row-level parsing."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """Normalized row input carrying identity, schema, and column values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """Captured row-level Source retaining exact columns and values."""

    source_id: str
    name: str = ""
    definition_version: str = "1"
    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    description: str | None = None
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def _ensure_identity_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "source_id" in data and not data.get("name"):
                data["name"] = data["source_id"]
            elif "name" in data and not data.get("source_id"):
                data["source_id"] = data["name"]
        return data

    @model_validator(mode="after")
    def _validate_identity(self) -> CSVRowSource:
        if not self.name:
            self.name = self.source_id
        if self.name != self.source_id:
            raise CSVRowError("CSVRowSource name and source_id must be identical")
        return self


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id:
        raise CSVRowError("document_id must be a non-empty string")
    if document_id != document_id.strip():
        raise CSVRowError("document_id must not contain leading or trailing whitespace")


def _validate_primary_key(primary_key: str) -> None:
    if not isinstance(primary_key, str) or not primary_key:
        raise CSVRowError("primary_key must be a non-empty string")


def _decode_csv_content(content: bytes) -> str:
    raw = content
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise CSVRowError("CSV document content is not valid UTF-8") from err

    if not text:
        raise CSVRowError("CSV document content is empty")

    return text


def _parse_csv_header(reader: Iterator[list[str]], primary_key: str) -> tuple[tuple[str, ...], int]:
    try:
        header_row = next(reader, None)
    except csv.Error as err:
        raise CSVRowError(f"Malformed CSV header: {err}") from err

    if header_row is None or len(header_row) == 0:
        raise CSVRowError("CSV header is missing or empty")

    for col in header_row:
        if not col or not col.strip():
            raise CSVRowError("CSV header columns cannot be empty or pure whitespace")

    if len(set(header_row)) != len(header_row):
        raise CSVRowError("CSV header columns must be unique")

    if primary_key not in header_row:
        raise CSVRowError(f"primary_key {primary_key!r} not found in CSV header")

    pk_index = header_row.index(primary_key)
    return tuple(header_row), pk_index


def _parse_csv_records(
    reader: Iterator[list[str]],
    document_id: str,
    primary_key: str,
    columns: tuple[str, ...],
    pk_index: int,
) -> tuple[CSVRowInput, ...]:
    seen_pks: set[str] = set()
    rows: list[CSVRowInput] = []

    try:
        for record in reader:
            if len(record) == 0:
                continue
            if len(record) != len(columns):
                raise CSVRowError(f"Row field count {len(record)} does not match header width {len(columns)}")

            pk_val = record[pk_index]
            if not pk_val or not pk_val.strip():
                raise CSVRowError("Primary key value cannot be empty or pure whitespace")

            if pk_val in seen_pks:
                raise CSVRowError(f"Duplicate primary key value {pk_val!r} in document {document_id!r}")
            seen_pks.add(pk_val)

            csv_row_source_id(document_id, pk_val)

            rows.append(
                CSVRowInput(
                    document_id=document_id,
                    primary_key=primary_key,
                    primary_key_value=pk_val,
                    columns=columns,
                    values=tuple(record),
                )
            )
    except csv.Error as err:
        raise CSVRowError(f"Malformed CSV record: {err}") from err

    return tuple(rows)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Generate a stable percent-encoded row-level source identity."""

    _validate_document_id(document_id)

    if not isinstance(primary_key_value, str) or not primary_key_value or not primary_key_value.strip():
        raise CSVRowError("primary_key_value must not be empty or pure whitespace")

    quoted_doc = quote(document_id, safe="")
    quoted_pk = quote(primary_key_value, safe="")
    identity = f"csv:{quoted_doc}:{quoted_pk}"

    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise CSVRowError(f"source_id length {len(identity)} exceeds limit of {MAX_SOURCE_ID_LENGTH}")

    return identity


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse an offline CSV document into validated row-level inputs."""

    _validate_document_id(value.document_id)
    _validate_primary_key(value.primary_key)
    text = _decode_csv_content(value.content)

    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=",",
        quotechar='"',
        doublequote=True,
        strict=True,
    )

    columns, pk_index = _parse_csv_header(reader, value.primary_key)
    return _parse_csv_records(reader, value.document_id, value.primary_key, columns, pk_index)


@dataclass(frozen=True, slots=True)
class CSVRowTextEvidenceProjection:
    """Project one CSVRowSource into standard text-evidence representation."""

    name: str = "powercontext.text-evidence"
    version: str = "1"
    source_class: type[CSVRowSource] = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        content = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=content,
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


@dataclass(frozen=True, slots=True)
class CSVRowSourceDefinition:
    """Source Definition for row-level CSV ingestion and evidence lookup."""

    name: str = "csv-row"
    version: str = "1"
    input_class: type[CSVRowInput] = CSVRowInput
    source_class: type[CSVRowSource] = CSVRowSource
    projections: tuple[SourceProjection[CSVRowSource], ...] = (CSVRowTextEvidenceProjection(),)

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            definition_version="1",
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = CSVRowSourceDefinition()

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowError",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
