"""Render the acceptance report as a human readable document.

The JSON report written by ``verify.py`` is the machine readable source of
truth. This script renders it into a Markdown document so a reviewer can read
what was run, what it returned and where the evidence lives without parsing
JSON.

Every row carries the test name, the command that was actually executed, its
real exit code, the git version the result belongs to and the repository
relative path of the evidence file. A check that was never executed is
reported as ``BLOCKED`` — it is never written down as a pass.

Run it with::

    python minimax/scripts/render_acceptance_report.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.config import load_settings  # noqa: E402

STATUS_MARK = {"PASS": "PASS", "FAIL": "FAIL", "BLOCKED": "BLOCKED"}


def _escape(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _render_commands(commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for command in commands:
        scope = command.get("scope")
        prefix = f"{scope} — " if scope else ""
        extra = ""
        if command.get("log"):
            extra = f" (日志 `{command['log']}`)"
        lines.append(
            f"- {prefix}`{_escape(command.get('command'))}` → 退出码 "
            f"`{command.get('exit_code')}`{extra}"
        )
    return lines


def _render(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines: list[str] = [
        "# 验收报告 — MiniMax SDD 上下文管理模块",
        "",
        f"- 总体结果：**{report.get('overall')}**",
        f"- 通过 / 失败 / 阻塞：{summary.get('pass')} / {summary.get('fail')} / "
        f"{summary.get('blocked')}（共 {summary.get('total')} 项）",
        f"- Git 分支：`{report.get('branch')}`",
        f"- Git 版本：`{report.get('commit')}`",
        f"- Python：`{report.get('python')}`",
        f"- 生成命令：`{report.get('reproduce_with')}`",
        f"- 模块路径：`{report.get('module_root_relative')}`",
        "",
        "## 六项官方验收",
        "",
        "| 编号 | 名称 | 结果 | Git 版本 | 证据路径 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report.get("results", []):
        paths = "<br>".join(f"`{path}`" for path in item.get("evidence_paths", [])) or "—"
        lines.append(
            f"| {item.get('item')} | {_escape(item.get('title'))} | "
            f"**{STATUS_MARK.get(item.get('status'), item.get('status'))}** | "
            f"`{str(item.get('git_version'))[:8]}` | {paths} |"
        )

    lines.append("")
    for item in report.get("results", []):
        lines.append(f"### {item.get('item')} — {item.get('title')}")
        lines.append("")
        lines.append(f"- 结果：**{item.get('status')}**")
        lines.append(f"- 说明：{_escape(item.get('detail'))}")
        lines.append(f"- Git 版本：`{item.get('git_version')}`")
        commands = item.get("commands", [])
        if commands:
            lines.append("- 实际执行的命令：")
            lines.extend(_render_commands(commands))
        paths = item.get("evidence_paths", [])
        if paths:
            lines.append("- 证据路径：")
            lines.extend(f"  - `{path}`" for path in paths)
        lines.append("")

    lines.append("## 判定口径")
    lines.append("")
    lines.append(
        "- `PASS`：该项的检查全部为真，且其证据来自本报告记录的 git 版本对应的真实执行。"
    )
    lines.append(
        "- `FAIL`：检查执行了但未通过，例如补丁重放后目标测试未通过，或哈希与提交不一致。"
    )
    lines.append(
        "- `BLOCKED`：依赖不可用或证据缺失，该项**没有**被执行，因此不计入通过。"
    )
    lines.append("")
    lines.append(
        "TEST-02 是**离线历史证据审计**，它不发起新的模型调用；"
        "需要一次真实在线调用时使用 `minimax/scripts/live_minimax_check.py`，"
        "其结果单独记录在 `minimax/evidence/minimax_live_check.json`。"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the acceptance report")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    arguments = parser.parse_args(argv)

    settings = load_settings()
    evidence_dir = settings.evidence_dir
    source = Path(arguments.input) if arguments.input else evidence_dir / "acceptance_report.json"
    if not source.is_file():
        print(f"缺少验收报告 {source}，请先运行 python minimax/scripts/verify.py --all")
        return 1

    report = json.loads(source.read_text(encoding="utf-8"))
    document = _render(report)

    output = (
        Path(arguments.output)
        if arguments.output
        else evidence_dir / "acceptance_report.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    print(f"报告已写入 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
