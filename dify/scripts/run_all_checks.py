"""一条命令跑完《记仇小镇》的全部验收。

    python scripts/run_all_checks.py --email ... --password ...

真实集成测试（需要真实服务）与 Mock 单元测试**分开报告**，
不混在一起 —— 单元测试通过不等于端到端验收通过。

退出码：全部通过返回 0；只要有一项真实集成测试失败就返回 1。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EVIDENCE = ROOT / "evidence"

#: 证据文件里**不许**出现的东西。
#:
#: 汇总文件会记下每条命令的原文，用来证明"跑的是哪条命令"。
#: 但命令里有 ``--password`` —— 把密码原样写进仓库里的证据文件
#: 等于把凭据交出去。所以这里把密码**脱敏**后再记录：
#: 保留"确实传了密码"这个事实，但不保留密码本身。
SECRET_FLAGS = ("--password", "--token", "--api-key")


def _redact(argv: list[str]) -> str:
    """Render a command line with its secrets masked out."""

    parts: list[str] = []
    mask_next = False
    for item in argv:
        if mask_next:
            parts.append("***")
            mask_next = False
            continue
        if item in SECRET_FLAGS:
            parts.append(item)
            mask_next = True
            continue
        parts.append(item)
    return " ".join(parts)


def run(label: str, argv: list[str], kind: str) -> dict:
    print(f"\n{'=' * 72}\n== {label}（{kind}）\n{'=' * 72}")
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    sys.stdout.write(proc.stdout or "")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return {
        "label": label,
        "kind": kind,
        "command": _redact(argv),
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="《记仇小镇》全部验收")
    parser.add_argument("--email", required=True, help="Dify Console 账号")
    parser.add_argument("--password", required=True, help="Dify Console 密码")
    parser.add_argument("--json", dest="json_out", default="")
    parser.add_argument("--skip-integration", action="store_true",
                        help="只跑单元测试（不需要任何服务）")
    parser.add_argument("--suffix", default="",
                        help="证据文件名后缀。V2 用 '_v2'，避免覆盖 V1 的历史证据")
    args = parser.parse_args()

    if not args.json_out:
        args.json_out = str(EVIDENCE / f"all_checks{args.suffix}.json")

    py = sys.executable
    results: list[dict] = []

    def evidence(name: str) -> str:
        return str(EVIDENCE / f"{name}{args.suffix}.json")

    # ---- Mock 单元测试（不需要任何服务）--------------------------------
    results.append(run(
        "规则单元测试",
        [py, str(HERE / ".." / "tests" / "test_rules.py")],
        "mock 单元测试",
    ))

    if not args.skip_integration:
        # ---- 真实集成测试（需要真实服务）--------------------------------
        results.append(run(
            "seekdb 数据层验收",
            [py, str(HERE / "verify_seekdb.py"), "--json", evidence("seekdb_verify")],
            "真实集成测试",
        ))
        results.append(run(
            "后端 API 验收",
            [py, str(HERE / "verify_backend_api.py"), "--json", evidence("backend_api_verify")],
            "真实集成测试",
        ))
        results.append(run(
            "PowerContext 记忆验收",
            [py, str(HERE / "verify_memory.py"), "--json", evidence("memory_verify")],
            "真实集成测试",
        ))
        results.append(run(
            "Dify 全链路 T1–T9 验收",
            [py, str(HERE / "verify_dify_e2e.py"),
             "--email", args.email, "--password", args.password,
             "--json", evidence("dify_e2e")],
            "真实集成测试",
        ))

    print(f"\n{'=' * 72}\n== 汇总\n{'=' * 72}")
    integration = [r for r in results if r["kind"] == "真实集成测试"]
    mock = [r for r in results if r["kind"] == "mock 单元测试"]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['kind']:12s} {r['label']}")

    print(f"\n真实集成测试: {sum(r['passed'] for r in integration)}/{len(integration)} 通过")
    print(f"Mock 单元测试: {sum(r['passed'] for r in mock)}/{len(mock)} 通过")

    all_passed = all(r["passed"] for r in results)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "results": results,
            "integration_passed": sum(r["passed"] for r in integration),
            "integration_total": len(integration),
            "mock_passed": sum(r["passed"] for r in mock),
            "mock_total": len(mock),
            "all_passed": all_passed,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {out}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
