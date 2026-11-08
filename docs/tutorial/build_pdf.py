#!/usr/bin/env python3
"""把新手教程 Markdown 按「书籍模版」风格（黑白灰、宋体正文 + 黑体标题、封面 / 目录 / 章节页）
渲染成 HTML，再用 Chromium 内核浏览器打印成 PDF。目录页码通过两遍渲染回填。

    pip install markdown pypdf
    python3 docs/tutorial/build_pdf.py [新手图文教程.md]
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import markdown
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
REPO_BLOB = "https://github.com/0x-howard/wx-cli/blob/main/docs/tutorial/"

COVER = {
    "title": "微信聊天记录导出",
    "subtitle": "零基础图文教程",
    "tagline": "复制、粘贴、回车，约 30～40 分钟，把全部群聊和私聊导出成文字文档",
    "meta": ["作者：Howard", "账号：@哎哟不想上早八啊", "资料核验：2026-11", "版本：v1.0"],
}
HEADER_LEFT = "微信聊天记录导出｜零基础图文教程"
HEADER_RIGHT = "@哎哟不想上早八啊"

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2705\u26D4\u26A0\uFE0F]")
PDF_WORDING = [
    ("左上角  →", "左上角苹果图标 →"),
    ("第三部分", "第 3 章"),
    ("第四部分", "第 4 章"),
    ("「五、给 AI 助手的执行说明」", "「第 5 章 给 AI 助手的执行说明」"),
]

BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("chromium") or "",
    shutil.which("google-chrome") or "",
    shutil.which("msedge") or "",
]

CSS = """
:root {
  --serif: "Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", "SimSun", serif;
  --sans: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  --mono: "SF Mono", Menlo, Consolas, monospace;
}
@page {
  size: A4;
  margin: 20mm 22.5mm 19mm;
  @top-left   { content: "%(hl)s"; font: 8.5pt var(--sans); color: #505050;
                vertical-align: bottom; margin-bottom: 6mm; border-bottom: 0.5pt solid #888; }
  @top-center { content: ""; margin-bottom: 6mm; border-bottom: 0.5pt solid #888; }
  @top-right  { content: "%(hr)s"; font: 8.5pt var(--sans); color: #505050;
                vertical-align: bottom; margin-bottom: 6mm; border-bottom: 0.5pt solid #888; }
  @bottom-center { content: "—   " counter(page) "   —"; font: 9pt var(--sans); color: #4B4B4B; }
}
@page :first {
  @top-left { content: none; } @top-center { content: none; } @top-right { content: none; }
  @bottom-center { content: none; }
}
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font-family: var(--serif); font-size: 10.5pt; color: #262626; line-height: 1.58; }

.cover { height: 252mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.cover-title { font: 30pt var(--sans); color: #111; margin-bottom: 18pt; letter-spacing: 1pt; }
.cover-sub { font-size: 14.5pt; color: #4B4B4B; margin-bottom: 8pt; }
.cover-tagline { font-size: 11.5pt; color: #646464; margin-bottom: 60pt; }
.cover-meta { font-size: 10.5pt; color: #333; margin-bottom: 8pt; }

.toc, .chapter { break-before: page; }
.chapter-title, .toc-title { font: 700 22pt var(--sans); color: #111; text-align: center; margin: 0 0 22pt; }
.chapter-number { font: 24pt var(--sans); color: #111; text-align: center; margin: 14mm 0 16pt; }
.toc-title { margin-top: 14mm; }
.toc-row { display: flex; align-items: baseline; }
.toc-row .dots { flex: 1; border-bottom: 0.6pt dotted #aaa; margin: 0 6pt; }
.toc-1 { font: 700 10.5pt var(--sans); color: #222; margin: 10pt 0 5pt; }
.toc-2 { font-size: 9.5pt; color: #444; margin: 0 0 3pt 17pt; }
.toc a { color: inherit; text-decoration: none; }

h3 { font: 700 15.5pt var(--sans); color: #111; margin: 18pt 0 10pt; break-after: avoid; }
p { margin: 0 0 5pt; text-indent: 2em; text-align: justify; }
li p, td p, th p, blockquote p, .figure p { text-indent: 0; }
ul, ol { margin: 4pt 0 8pt; padding-left: 1.6em; }
li { margin-bottom: 3pt; }
li::marker { color: #777; }
strong { color: #111; }
a { color: #333; text-decoration: underline; text-decoration-color: #999; }

blockquote.note { font: 9.5pt/1.4 var(--sans); color: #666; margin: 8pt 0 10pt; padding: 0; }
blockquote.note p { margin-bottom: 3pt; }
blockquote.note strong { color: #444; }
blockquote.insight { font: 700 11pt/1.45 var(--sans); color: #222; background: #F1F1F1;
                     border-left: 2.25pt solid #666; margin: 10pt 6pt 10pt 10pt; padding: 8pt 12pt; }

code { font: 8.8pt var(--mono); background: #F1F1F1; padding: 0.5pt 3pt; color: #222; }
pre { background: #F6F6F6; border-left: 1.5pt solid #BBB; padding: 7pt 10pt; margin: 6pt 0 10pt;
      white-space: pre-wrap; word-break: break-all; break-inside: avoid; line-height: 1.45; }
pre code { background: none; padding: 0; font-size: 8.5pt; }

table { width: 100%%; border-collapse: collapse; margin: 8pt 0 12pt; break-inside: avoid; font-size: 9pt; }
th { font: 700 9.5pt var(--sans); color: #222; background: #F2F2F2; text-align: left;
     border-top: 1pt solid #666; border-bottom: 0.4pt solid #CCC; padding: 5pt 7pt; }
td { border-bottom: 0.4pt solid #CCC; padding: 5pt 7pt; vertical-align: top; line-height: 1.5; }
tr:last-child td { border-bottom: 1pt solid #666; }

.figure { text-align: center; margin: 10pt 0 4pt; break-inside: avoid; }
.figure img { width: 13.5cm; max-width: 100%%; filter: grayscale(100%%); border: 0.4pt solid #C9C9C9; }
.caption { font-size: 8.5pt; color: #777; text-align: center; text-indent: 0; margin: 4pt 0 10pt; }
.source { font-size: 8.5pt; color: #777; text-indent: 0; text-align: left; margin-top: 18pt;
          border-top: 0.4pt solid #CCC; padding-top: 6pt; }
"""


def github_slug(value: str, separator: str) -> str:
    """Match GitHub's heading anchors so in-page links work both on GitHub and in the PDF."""
    value = re.sub(r"[^\w\- ]", "", value.strip().lower())
    return value.replace(" ", separator)


def find_browser() -> str:
    for b in BROWSERS:
        if b and Path(b).exists():
            return b
    sys.exit("未找到 Chrome / Edge / Chromium，无法打印 PDF")


def plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def prepare_markdown(text: str) -> str:
    text = re.sub(r"\A# .+\n+(?:>.*\n)+", "", text)
    text = EMOJI.sub("", text)
    for old, new in PDF_WORDING:
        text = text.replace(old, new)
    return text


def render_body(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": github_slug}},
    )
    missing = set(re.findall(r'href="#([^"]+)"', body)) - set(re.findall(r'id="([^"]+)"', body))
    if missing:
        print(f"警告：找不到锚点 {missing}", file=sys.stderr)
    body = re.sub(r'<a href="([^"#:][^"]*\.md)"', rf'<a href="{REPO_BLOB}\1"', body)
    body = re.sub(r"<hr />\s*<p><em>(.*?)</em></p>", r'<p class="source">\1</p>', body, flags=re.S)
    body = re.sub(r"<hr />", "", body)

    def quote(m: re.Match) -> str:
        inner = m.group(1).strip()
        only_bold = re.fullmatch(r"<p><strong>[^<]*</strong></p>", inner)
        return f'<blockquote class="{"insight" if only_bold else "note"}">{inner}</blockquote>'

    body = re.sub(r"<blockquote>(.*?)</blockquote>", quote, body, flags=re.S)

    fig = 0

    def figure(m: re.Match) -> str:
        nonlocal fig
        fig += 1
        alt, src = m.groups()
        return (f'<div class="figure"><img src="{src}" alt="{alt}"></div>'
                f'<p class="caption">图 {fig}  {alt}</p>')

    body = re.sub(r'<p><img alt="([^"]*)" src="([^"]*)" /></p>', figure, body)

    toc: list[tuple[int, str, str]] = []
    parts = re.split(r'(<h2 id="[^"]+">.*?</h2>)', body)
    out = [parts[0]]
    for i in range(1, len(parts), 2):
        hid, title = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', parts[i]).groups()
        m = re.match(r"([一二三四五六七八九])、(.*)", title)
        label = f"第 {CN_NUM[m.group(1)]} 章" if m else "附录"
        name = m.group(2) if m else title
        toc.append((1, hid, f"{label}  {plain(name)}"))
        content = parts[i + 1]
        for h3id, h3 in re.findall(r'<h3 id="([^"]+)">(.*?)</h3>', content):
            toc.append((2, h3id, plain(h3)))
        out.append(f'<section class="chapter"><div class="chapter-number">{label}</div>'
                   f'<h2 class="chapter-title" id="{hid}">{name}</h2>{content}</section>')
    return "".join(out), toc


def cover_html() -> str:
    meta = "".join(f'<div class="cover-meta">{html.escape(x)}</div>' for x in COVER["meta"])
    return (f'<section class="cover"><div class="cover-title">{COVER["title"]}</div>'
            f'<div class="cover-sub">{COVER["subtitle"]}</div>'
            f'<div class="cover-tagline">{COVER["tagline"]}</div>{meta}</section>')


def toc_html(toc: list[tuple[int, str, str]], pages: dict[str, int]) -> str:
    rows = "".join(
        f'<div class="toc-row toc-{lvl}"><a href="#{hid}">{html.escape(t)}</a>'
        f'<span class="dots"></span><span>{pages.get(hid, 0)}</span></div>'
        for lvl, hid, t in toc
    )
    return f'<section class="toc"><div class="toc-title">目录</div>{rows}</section>'


def print_pdf(browser: str, html_path: Path, pdf_path: Path) -> None:
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", html_path.as_uri()],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def locate(pdf_path: Path, toc: list[tuple[int, str, str]]) -> dict[str, int]:
    reader = PdfReader(str(pdf_path))
    pages = {unquote(name.lstrip("/")): reader.get_destination_page_number(dest) + 1
             for name, dest in reader.named_destinations.items()}
    for _, hid, title in toc:
        if hid not in pages:
            print(f"警告：目录项未定位到页码：{title}", file=sys.stderr)
    return pages


def main() -> None:
    src = HERE / (sys.argv[1] if len(sys.argv) > 1 else "新手图文教程.md")
    body, toc = render_body(prepare_markdown(src.read_text(encoding="utf-8")))
    css = CSS % {"hl": HEADER_LEFT, "hr": HEADER_RIGHT}
    html_path, pdf_path = src.with_suffix(".html"), src.with_suffix(".pdf")
    browser = find_browser()

    def build(pages: dict[str, int]) -> None:
        html_path.write_text(
            f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<title>{COVER["title"]}：{COVER["subtitle"]}</title><style>{css}</style></head>'
            f"<body>{cover_html()}{toc_html(toc, pages)}{body}</body></html>",
            encoding="utf-8",
        )
        print_pdf(browser, html_path, pdf_path)

    build({})
    build(locate(pdf_path, toc))
    html_path.unlink()
    print(f"PDF → {pdf_path}（{len(PdfReader(str(pdf_path)).pages)} 页）")


if __name__ == "__main__":
    main()
