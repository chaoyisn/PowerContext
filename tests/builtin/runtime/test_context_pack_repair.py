from __future__ import annotations

import json
import subprocess
import sys
from itertools import pairwise
from types import SimpleNamespace
from typing import Any, cast

import pytest

from powercontext.builtin.runtime.application import ScopedContextApplication
from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)


@pytest.mark.parametrize(
    "before,after",
    [
        ("", "first"),
        ("same", "same"),
        ("A" * 128, "A" * 128 + "tail"),
        ("A" * 64 + "B" * 64, "A" * 64 + "new" + "B" * 64),
        ("A" * 64 + "B" * 64 + "C" * 64, "A" * 64 + "C" * 64),
        ("A" * 64 + "B" * 64, "A" * 64 + "X" * 64),
        ("A" * 64 + "B" * 64, "B" * 64 + "A" * 64),
        ("text citation:revision=1", "text citation:revision=2"),
        ("text citation:id=1", "text citation:id=2"),
        ('海🙂\\"\n', '海🙂\\"\n更新'),
        ("not empty", ""),
        ("a" * 64, "a" * 65),
    ],
)
def test_repair_matrix(before: str, after: str) -> None:
    base = ContextPack.from_content(before, chunk_bytes=64)
    target = ContextPack.from_content(after, chunk_bytes=64)
    delta = ContextPackDelta.from_bytes(ContextPackDelta.between(base, target).to_bytes())
    assert b"".join(apply_context_pack_delta(ContextPack.from_bytes(base.to_bytes()), delta).items).decode() == after


@pytest.mark.asyncio
async def test_public_keyword_and_partial_chunk_reuse() -> None:
    class Context:
        async def prepare(self, request):
            return SimpleNamespace(content=request)

    context = Context()
    prepare = cast(Any, ScopedContextApplication.prepare_incremental)
    before = "a" * 400 + "old" + "b" * 1000
    after = "a" * 400 + "new" + "b" * 1000
    base = await prepare(context, request=before)
    delta = await prepare(context, request=after, base_pack=base)
    assert isinstance(base, ContextPack) and isinstance(delta, ContextPackDelta)
    assert delta.prefix_items == 6
    assert len(delta.to_bytes()) < len(
        ContextPackDelta.between(ContextPack.from_content(before), ContextPack.from_content(after)).to_bytes()
    )
    assert b"".join(apply_context_pack_delta(base, delta).items).decode() == after


def test_independent_process_replays_five_rounds(tmp_path) -> None:
    contents = ["海🙂" * 150, "海🙂" * 150 + "x", "海🙂" * 100 + "new", "", "end"]
    packs = [ContextPack.from_content(value, chunk_bytes=64) for value in contents]
    wires = [json.loads(packs[0].to_bytes())] + [
        json.loads(ContextPackDelta.between(a, b).to_bytes()) for a, b in pairwise(packs)
    ]
    path = tmp_path / "wire.json"
    path.write_text(json.dumps(wires), encoding="utf-8")
    code = """import json,sys
from powercontext.builtin.runtime.context_pack import ContextPack,ContextPackDelta,apply_context_pack_delta
w=json.load(open(sys.argv[1],encoding='utf-8'))
p=ContextPack.from_bytes(json.dumps(w[0]).encode())
out=[b''.join(p.items).decode()]
for d in w[1:]:
 p=apply_context_pack_delta(p,ContextPackDelta.from_bytes(json.dumps(d).encode()))
 out.append(b''.join(p.items).decode())
print(json.dumps(out,ensure_ascii=True))
"""
    result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == contents


def test_missing_or_corrupt_base_fails() -> None:
    base = ContextPack.from_content("base")
    delta = ContextPackDelta.between(base, ContextPack.from_content("target"))
    with pytest.raises(ContextPackError):
        apply_context_pack_delta(ContextPack.from_content("wrong"), delta)
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(b"not json")
