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

"""Portable full and incremental encodings for prepared context text."""

# The single public protocol error carries a specific diagnostic for each malformed field.
# ruff: noqa: TRY003

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, cast

from powercontext.errors import PowerContextError

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ContextPackError(PowerContextError, ValueError):
    """A context pack or delta does not satisfy the wire protocol."""


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _validate_items(items: object) -> tuple[bytes, ...]:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("items must be a tuple of bytes")
    return cast(tuple[bytes, ...], items)


def _encoded_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": _PACK_SCHEMA, "items": _encoded_items(items)}
    return f"sha256:{hashlib.sha256(_canonical_json(unsigned)).hexdigest()}"


def _pack_bytes(items: tuple[bytes, ...], digest: str) -> bytes:
    byte_count = 0
    while True:
        wire = _canonical_json({
            "schema": _PACK_SCHEMA,
            "items": _encoded_items(items),
            "digest": digest,
            "byte_count": byte_count,
        })
        actual_byte_count = len(wire)
        if actual_byte_count == byte_count:
            return wire
        byte_count = actual_byte_count


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ContextPackError(f"invalid JSON constant: {value}")


def _decode_object(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise ContextPackError("wire data must be bytes")
    try:
        payload = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_json_constant
        )
    except ContextPackError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("invalid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ContextPackError("wire payload must be a JSON object")
    return payload


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("items must be a JSON array")
    decoded: list[bytes] = []
    for item in value:
        if not isinstance(item, str):
            raise ContextPackError("items must contain Base64 strings")
        try:
            chunk = base64.b64decode(item.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as error:
            raise ContextPackError("invalid Base64 item") from error
        if base64.b64encode(chunk).decode("ascii") != item:
            raise ContextPackError("non-canonical Base64 item")
        decoded.append(chunk)
    return tuple(decoded)


def _validate_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ContextPackError("invalid SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete, independently serializable prepared-context payload."""

    items: tuple[bytes, ...]
    digest: str

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        chunks = _validate_items(items)
        return cls(chunks, _pack_digest(chunks))

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        if not isinstance(content, str):
            raise ContextPackError("content must be text")
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if not content:
            return cls.build(())

        chunks: list[bytes] = []
        current = bytearray()
        try:
            lines = content.splitlines(keepends=True)
            for line in lines:
                line_bytes = line.encode("utf-8")
                if len(current) + len(line_bytes) <= chunk_bytes:
                    current.extend(line_bytes)
                else:
                    if current:
                        chunks.append(bytes(current))
                        current.clear()
                    if len(line_bytes) <= chunk_bytes:
                        current.extend(line_bytes)
                    else:
                        for character in line:
                            encoded = character.encode("utf-8")
                            if len(encoded) > chunk_bytes:
                                raise ContextPackError("chunk_bytes is too small for a UTF-8 character")
                            if len(current) + len(encoded) > chunk_bytes:
                                chunks.append(bytes(current))
                                current.clear()
                            current.extend(encoded)
        except UnicodeEncodeError as error:
            raise ContextPackError("content is not valid Unicode text") from error
        if current:
            chunks.append(bytes(current))
        return cls.build(tuple(chunks))

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @property
    def content(self) -> str:
        """Reconstruct the original text context from the verified chunks."""
        return b"".join(self.items).decode("utf-8")

    @property
    def text(self) -> str:
        """Alias for content."""
        return self.content

    def to_bytes(self) -> bytes:
        chunks = _validate_items(self.items)
        digest = _validate_digest(self.digest)
        if digest != _pack_digest(chunks):
            raise ContextPackError("pack digest does not match items")
        return _pack_bytes(chunks, digest)

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _decode_object(data)
        if set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("invalid pack fields")
        if payload["schema"] != _PACK_SCHEMA:
            raise ContextPackError("unsupported pack schema")
        items = _decode_items(payload["items"])
        digest = _validate_digest(payload["digest"])
        byte_count = payload["byte_count"]
        if type(byte_count) is not int or byte_count < 0:
            raise ContextPackError("invalid pack byte_count")
        pack = cls.build(items)
        if pack.digest != digest or pack.byte_count != byte_count or len(data) != byte_count:
            raise ContextPackError("pack digest or byte_count does not match payload")
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A replacement suffix and the verified base prefix it follows."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("base and target must be context packs")
        base.to_bytes()
        target.to_bytes()
        prefix_items = 0
        for base_item, target_item in zip(base.items, target.items, strict=False):
            if base_item != target_item:
                break
            prefix_items += 1
        return cls(base.digest, target.digest, prefix_items, target.items[prefix_items:])

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _decode_object(data)
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            raise ContextPackError("invalid delta fields")
        if payload["schema"] != _DELTA_SCHEMA:
            raise ContextPackError("unsupported delta schema")
        delta = cls(
            _validate_digest(payload["base_digest"]),
            _validate_digest(payload["target_digest"]),
            payload["prefix_items"],
            _decode_items(payload["appended"]),
        )
        delta._validate()
        return delta

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        self._validate()
        return _canonical_json({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encoded_items(self.appended),
        })

    def _validate(self) -> None:
        _validate_digest(self.base_digest)
        _validate_digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        _validate_items(self.appended)


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Validate a base and delta, then rebuild the complete target pack."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("base and delta have invalid types")
    base.to_bytes()
    delta._validate()
    if delta.base_digest != base.digest:
        raise ContextPackError("delta base digest does not match pack")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("prefix_items exceeds base item count")
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match rebuilt pack")
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
