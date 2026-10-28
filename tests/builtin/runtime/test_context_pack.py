from __future__ import annotations

import base64
import hashlib
import json

import pytest

from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)


def test_pack_wire_digest_and_byte_count_are_canonical() -> None:
    items = (b"alpha\n", "海洋".encode())
    unsigned = {
        "schema": "powercontext.context-pack.v1",
        "items": [base64.b64encode(item).decode("ascii") for item in items],
    }
    pack = ContextPack.build(items)
    wire = pack.to_bytes()
    payload = json.loads(wire)
    expected_digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    assert set(payload) == {"schema", "items", "digest", "byte_count"}
    assert payload["digest"] == f"sha256:{expected_digest}"
    assert pack.byte_count == len(wire) == payload["byte_count"]
    assert wire == json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    restored = ContextPack.from_bytes(wire)
    assert restored == pack
    assert restored is not pack


def test_content_chunks_are_bounded_valid_utf8_and_lossless() -> None:
    content = "海洋🙂e\u0301\nPowerContext"
    pack = ContextPack.from_content(content, chunk_bytes=7)

    assert all(0 < len(item) <= 7 for item in pack.items)
    assert all(item.decode("utf-8").encode("utf-8") == item for item in pack.items)
    assert b"".join(pack.items).decode("utf-8") == content
    assert ContextPack.from_content("").items == ()
    with pytest.raises(ContextPackError):
        ContextPack.from_content("海", chunk_bytes=2)
    with pytest.raises(ContextPackError):
        ContextPack.from_content("text", chunk_bytes=True)


def test_any_common_prefix_rebuilds_after_independent_serialization() -> None:
    base = ContextPack.build((b"start", b"middle", b"old"))
    target = ContextPack.build((b"start", b"middle", b"new", b"tail"))

    for prefix in range(3):
        delta = ContextPackDelta(base.digest, target.digest, prefix, target.items[prefix:])
        restored_delta = ContextPackDelta.from_bytes(delta.to_bytes())
        assert restored_delta is not delta
        rebuilt = apply_context_pack_delta(ContextPack.from_bytes(base.to_bytes()), restored_delta)
        assert rebuilt == target


@pytest.mark.parametrize(
    "target_items",
    [(b"changed", b"middle", b"old"), (b"start", b"changed", b"old"), (b"start", b"middle", b"new"), ()],
)
def test_delta_rebuilds_changes_at_each_position(target_items: tuple[bytes, ...]) -> None:
    base = ContextPack.build((b"start", b"middle", b"old"))
    target = ContextPack.build(target_items)
    delta = ContextPackDelta.from_bytes(ContextPackDelta.between(base, target).to_bytes())

    assert apply_context_pack_delta(ContextPack.from_bytes(base.to_bytes()), delta) == target
    assert delta.byte_count == len(delta.to_bytes())


def test_decoders_reject_unknown_fields_bad_encoding_and_tampering() -> None:
    pack = ContextPack.build((b"alpha",))
    payload = json.loads(pack.to_bytes())
    for invalid in (
        {**payload, "extra": True},
        {**payload, "byte_count": payload["byte_count"] + 1},
        {**payload, "items": ["%%%"]},
    ):
        with pytest.raises(ContextPackError):
            ContextPack.from_bytes(json.dumps(invalid).encode())
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(pack.to_bytes().replace(b'"schema":', b'"schema":"unknown","schema":', 1))

    target = ContextPack.build((b"alpha", b"beta"))
    delta_payload = json.loads(ContextPackDelta.between(pack, target).to_bytes())
    for invalid in (
        {**delta_payload, "extra": True},
        {**delta_payload, "prefix_items": True},
        {**delta_payload, "appended": ["%%%"]},
    ):
        with pytest.raises(ContextPackError):
            ContextPackDelta.from_bytes(json.dumps(invalid).encode())
    with pytest.raises(ContextPackError):
        apply_context_pack_delta(ContextPack.build((b"wrong base",)), ContextPackDelta.between(pack, target))
