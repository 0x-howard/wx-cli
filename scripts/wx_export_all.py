#!/usr/bin/env python3
"""批量精简导出所有私聊和群聊到 exports/群聊、exports/私聊，并生成 exports/索引.md。

用法:
    python3 scripts/wx_export_all.py [--force] [--types group,private]
已存在的文件默认跳过（可断点续跑），--force 全部重导。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wx_export_md import ROOT, WX, build_markdown, export_json  # noqa: E402

DIRS = {"group": "群聊", "private": "私聊"}


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', "_", name).strip(" .")
    return name[:80] or "unnamed"


def fs_key(path: Path) -> str:
    return unicodedata.normalize("NFD", str(path)).casefold()


def list_sessions(types: set[str]) -> list[dict]:
    out = subprocess.run(
        [str(WX), "sessions", "-n", "100000", "--json"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    return [s for s in json.loads(out)["sessions"] if s["chat_type"] in types]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--types", default="group,private")
    args = ap.parse_args()

    sessions = list_sessions(set(args.types.split(",")))
    used: set[str] = set()
    index: list[tuple[str, str, int, str, str]] = []
    total = len(sessions)

    for i, s in enumerate(sessions, 1):
        sub = DIRS[s["chat_type"]]
        path = ROOT / "exports" / sub / f"{safe_name(s['chat'])}.md"
        if fs_key(path) in used:
            path = path.with_name(f"{path.stem}_{safe_name(s['username'])}.md")
        used.add(fs_key(path))
        rel = path.relative_to(ROOT / "exports")

        if path.exists() and not args.force:
            first = path.read_text(encoding="utf-8").split("\n", 4)
            m = re.search(r"精简导出 (\d+) 条", "\n".join(first))
            index.append((sub, s["chat"], int(m.group(1)) if m else 0, s.get("time", ""), str(rel)))
            continue

        try:
            data = export_json(s["username"], None, None)
        except subprocess.CalledProcessError as e:
            print(f"[{i}/{total}] 失败 {s['chat']}: {e}", file=sys.stderr)
            continue
        md, kept = build_markdown(data)
        if kept == 0:
            print(f"[{i}/{total}] 跳过（无文字消息） {s['chat']}", file=sys.stderr)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
        index.append((sub, s["chat"], kept, s.get("time", ""), str(rel)))
        print(f"[{i}/{total}] {kept:>6} 条  {rel}", file=sys.stderr)

    lines = ["# 聊天导出索引", "", f"> 共 {len(index)} 个会话", ""]
    for sub in DIRS.values():
        rows = sorted((r for r in index if r[0] == sub), key=lambda r: -r[2])
        lines += [f"## {sub}（{len(rows)}）", "", "| 会话 | 条数 | 最近 |", "|---|---:|---|"]
        for _, chat, kept, t, rel in rows:
            label = chat.replace("|", "\\|")
            lines.append(f"| [{label}](<{rel}>) | {kept} | {t} |")
        lines.append("")
    (ROOT / "exports" / "索引.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"完成：{len(index)} 个会话，索引 exports/索引.md", file=sys.stderr)


if __name__ == "__main__":
    main()
