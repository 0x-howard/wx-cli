#!/usr/bin/env python3
"""精简版微信聊天导出：只保留文字信息，输出紧凑 Markdown。

在放有 wx / config.json / all_keys.json 的目录下运行：
    python3 path/to/scripts/wx_export_md.py <聊天名或username> [-o 输出.md] [--since YYYY-MM-DD] [--until YYYY-MM-DD]

wx 查找顺序：环境变量 WX_BIN > 当前目录 ./wx（Windows 为 wx.exe）> PATH 中的 wx。输出默认写到 ./exports/。
macOS / Linux / Windows 通用，文件一律 UTF-8。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except AttributeError:
        pass


def find_wx() -> Path:
    candidates = [
        os.environ.get("WX_BIN"),
        str(ROOT / "wx"),
        str(ROOT / "wx.exe"),
        shutil.which("wx"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    sys.exit("找不到 wx：请在 wx 所在目录运行，或设置 WX_BIN=/path/to/wx")


WX = find_wx()

DROP_TYPE_CODES = {3, 34, 43, 47, 48, 50, 10000, 10002}  # 图片 语音 视频 表情 位置 通话 系统 撤回
DROP_APPMSG_TYPES = {8, 62}  # 表情包附件 拍一拍
QUOTE_MAX = 60


def xml_text(content: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", content, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def xml_attr(content: str, attr: str) -> str:
    m = re.search(rf'\b{attr}="([^"]*)"', content)
    return html.unescape(m.group(1)).strip() if m else ""


def squash(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def unescape_all(text: str) -> str:
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def summarize_quoted(quoted: str) -> str:
    quoted = unescape_all(quoted)
    sender, sep, body = quoted.partition(": ")
    if not sep:
        sender, body = "", quoted
    body = re.sub(r"^\[引用\] ", "", body.strip())
    body = re.sub(r"^[\w\-@]+:\s*(?=<)", "", body)
    if body.startswith("<"):
        if "<img" in body:
            body = "[图片]"
        elif "<videomsg" in body:
            body = "[视频]"
        elif "<emoji" in body:
            body = "[表情]"
        elif "<voicemsg" in body:
            body = "[语音]"
        else:
            title = xml_text(body, "title")
            body = f"[链接] {title}" if title else "[消息]"
    body = squash(body, QUOTE_MAX)
    return f"{sender}: {body}" if sender else body


XML_LEAK = re.compile(r"<\?xml|</?(?:msg|appmsg|refermsg|content|sysmsg|img)\b|&lt;/?\w+&gt;|aeskey=")


def render(msg: dict) -> str | None:
    text = render_raw(msg)
    if text:
        leak = XML_LEAK.search(text)
        if leak:
            text = text[: leak.start()].rstrip()
    return text or None


def render_raw(msg: dict) -> str | None:
    code = msg.get("type_code")
    content = (msg.get("content") or "").strip()
    if content.startswith("&lt;"):
        content = html.unescape(content)
    if code == 1:
        content = unescape_all(content)
    if code in DROP_TYPE_CODES:
        return None
    if code == 42:
        name = xml_attr(content, "nickname")
        return f"[名片] {name}" if name else None
    if code == 49:
        app = msg.get("appmsg_type")
        if app in DROP_APPMSG_TYPES:
            return None
        if app == 87:
            text = xml_text(content, "textannouncement")
            return f"[群公告]\n{text}" if text else None
        if content.startswith("<"):
            notice = xml_text(content, "textannouncement")
            if notice:
                return f"[群公告]\n{notice}"
            title = xml_text(content, "title")
            return f"[链接] {title}" if title else None
    if not content or content.startswith("<"):
        return None

    if content.startswith("[引用] "):
        body, _, quoted = content[len("[引用] "):].partition("\n  ↳ ")
        quoted = quoted.strip()
        return f"{body.strip()}（回复 {summarize_quoted(quoted)}）" if quoted else body.strip()
    return content


def export_json(chat: str, since: str | None, until: str | None) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out = tmp.name
    cmd = [str(WX), "export", chat, "-n", "10000000", "--format", "json", "-o", out]
    if since:
        cmd += ["--since", since]
    if until:
        cmd += ["--until", until]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    data = json.loads(Path(out).read_text(encoding="utf-8"))
    Path(out).unlink(missing_ok=True)
    return data


def build_markdown(data: dict) -> tuple[str, int]:
    lines = [f"# {data.get('chat', '')}", ""]
    kept, day = 0, None
    for msg in data.get("messages", []):
        text = render(msg)
        if not text:
            continue
        date, _, hm = (msg.get("time") or "").partition(" ")
        if date != day:
            day = date
            lines += ["", f"## {date}", ""]
        sender = msg.get("sender") or "?"
        first, *rest = text.splitlines()
        lines.append(f"- {hm} **{sender}**：{first}")
        lines += [f"  {r}" for r in rest if r.strip()]
        kept += 1
    lines.insert(1, f"\n> 精简导出 {kept} 条（原始 {len(data.get('messages', []))} 条）")
    return "\n".join(lines) + "\n", kept


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("-o", "--output")
    ap.add_argument("--since")
    ap.add_argument("--until")
    args = ap.parse_args()

    data = export_json(args.chat, args.since, args.until)
    md, kept = build_markdown(data)
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", data.get("chat") or args.chat)
    out = Path(args.output) if args.output else ROOT / "exports" / f"{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"{out}  保留 {kept}/{len(data.get('messages', []))} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
