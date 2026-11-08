#!/usr/bin/env python3
"""以「书籍模版.docx」为底，把新手教程 Markdown 生成可编辑的 Word 文档。
沿用模板的封面、页眉页脚和样式（Body CN / Chapter Title / Key Insight …），方便在 Word 里统一调整。

    pip install markdown python-docx
    python3 docs/tutorial/build_docx.py [--template 书籍模版.docx] [新手图文教程.md]
"""
from __future__ import annotations

import argparse
import copy
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import markdown
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pdf import (CN_NUM, COVER, HEADER_LEFT, REPO_BLOB, find_browser,  # noqa: E402
                       github_slug, prepare_markdown)

HERE = Path(__file__).resolve().parent
MONO = "Menlo"
LINK_GREY = RGBColor(0x33, 0x33, 0x33)


# ---------- 底层 XML 小工具 ----------

def set_ppr(p, tag: str, **attrs) -> None:
    ppr = p._p.get_or_add_pPr()
    for old in ppr.findall(qn(tag)):
        ppr.remove(old)
    el = OxmlElement(tag)
    for k, v in attrs.items():
        el.set(qn(f"w:{k}"), str(v))
    ppr.append(el)


def left_bar(p, color: str, size: int, fill: str) -> None:
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    for k, v in {"val": "single", "sz": size, "space": 8, "color": color}.items():
        left.set(qn(f"w:{k}"), str(v))
    bdr.append(left)
    ppr.append(bdr)
    set_ppr(p, "w:shd", val="clear", color="auto", fill=fill)


def cell_borders(cell, top: tuple[int, str] | None, bottom: tuple[int, str] | None, fill: str | None) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for side, spec in (("top", top), ("left", None), ("bottom", bottom), ("right", None)):
        el = OxmlElement(f"w:{side}")
        if spec:
            el.set(qn("w:val"), "single"), el.set(qn("w:sz"), str(spec[0])), el.set(qn("w:color"), spec[1])
        else:
            el.set(qn("w:val"), "nil")
        borders.append(el)
    tcpr.append(borders)
    if fill:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"), shd.set(qn("w:color"), "auto"), shd.set(qn("w:fill"), fill)
        tcpr.append(shd)


def add_bookmark(p, name: str, bid: int) -> None:
    start, end = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
    start.set(qn("w:id"), str(bid)), start.set(qn("w:name"), name)
    end.set(qn("w:id"), str(bid))
    p._p.insert(1 if p._p.pPr is not None else 0, start)
    p._p.append(end)


# ---------- SVG 截图 → 灰度 PNG ----------

def svg_to_png(svg: Path, out_dir: Path, browser: str) -> Path:
    root = ET.parse(svg).getroot()
    w, h = int(float(root.get("width"))), int(float(root.get("height")))
    page = out_dir / f"{svg.stem}.html"
    page.write_text(
        f'<html><body style="margin:0;background:#fff"><img src="{svg.as_uri()}" '
        f'style="width:{w}px;height:{h}px;display:block;filter:grayscale(100%)"></body></html>',
        encoding="utf-8",
    )
    png = out_dir / f"{svg.stem}.png"
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=3",
         f"--window-size={w},{h}", f"--screenshot={png}", page.as_uri()],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return png


# ---------- 文档构建 ----------

class Builder:
    def __init__(self, template: Path, md_dir: Path, img_dir: Path, browser: str):
        self.doc = Document(str(template))
        self.md_dir, self.img_dir, self.browser = md_dir, img_dir, browser
        self.anchors: dict[str, str] = {}
        self.bid = 100
        self.fig = 0
        self._prepare_template()

    def _prepare_template(self) -> None:
        body = self.doc.element.body
        blocks = [el for el in body if el.tag != qn("w:sectPr")]
        cover_end = next(i for i, el in enumerate(blocks) if el.tag == qn("w:p") and el.findall(".//" + qn("w:br")))
        for el in blocks[cover_end + 1:]:
            body.remove(el)
        texts = [COVER["title"], COVER["subtitle"], COVER["tagline"], *COVER["meta"]]
        cover = [p for p in self.doc.paragraphs if p.style.name.startswith("Cover")]
        for p, text in zip(cover, texts):
            for r in p.runs[1:]:
                r._r.getparent().remove(r._r)
            p.runs[0].text = text
        for hdr in (self.doc.sections[0].header, self.doc.sections[0].first_page_header):
            for p in hdr.paragraphs:
                for r in p.runs:
                    if "SWTer" in r.text:
                        r.text = HEADER_LEFT
                for tab in p._p.findall(".//" + qn("w:r") + "/" + qn("w:tab")):
                    ptab = OxmlElement("w:ptab")
                    ptab.set(qn("w:relativeTo"), "margin"), ptab.set(qn("w:alignment"), "right")
                    ptab.set(qn("w:leader"), "none")
                    tab.addprevious(ptab)
                    tab.getparent().remove(tab)
        self._ensure_styles()

    def _ensure_styles(self) -> None:
        styles = self.doc.styles
        code = styles.add_style("Code Book", WD_STYLE_TYPE.PARAGRAPH)
        code.base_style = styles["Normal"]
        code.font.name, code.font.size = MONO, Pt(8.5)
        code.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        rpr = code.element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{attr}"), MONO if attr != "eastAsia" else "PingFang SC")
        pf = code.paragraph_format
        pf.space_before, pf.space_after, pf.line_spacing = Pt(4), Pt(8), 1.25
        pf.left_indent = Cm(0.2)
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        ppr = code.element.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        left = OxmlElement("w:left")
        for k, v in {"val": "single", "sz": 12, "space": 6, "color": "BBBBBB"}.items():
            left.set(qn(f"w:{k}"), str(v))
        bdr.append(left)
        ppr.append(bdr)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"), shd.set(qn("w:color"), "auto"), shd.set(qn("w:fill"), "F6F6F6")
        ppr.append(shd)

        for level, base in ((1, "TOC 1 Book"), (2, "TOC 2 Book")):
            name = f"toc {level}"
            try:
                st = styles[name]
            except KeyError:
                st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            st.base_style = styles[base]
            st.paragraph_format.tab_stops.clear_all()
            ppr = st.element.get_or_add_pPr()
            tabs = OxmlElement("w:tabs")
            tab = OxmlElement("w:tab")
            tab.set(qn("w:val"), "right"), tab.set(qn("w:leader"), "dot"), tab.set(qn("w:pos"), "9354")
            tabs.append(tab)
            ppr.append(tabs)

    # ---- 段落与行内 ----

    def para(self, style: str, text: str | None = None):
        p = self.doc.add_paragraph(style=style)
        if text:
            p.add_run(text)
        return p

    def inline(self, p, node: ET.Element, bold=False, italic=False, size: Pt | None = None) -> None:
        if node.text:
            self._run(p, node.text, bold, italic, size)
        for child in node:
            tag = child.tag
            if tag in ("strong", "b"):
                self.inline(p, child, True, italic, size)
            elif tag in ("em", "i"):
                self.inline(p, child, bold, True, size)
            elif tag == "code":
                r = self._run(p, "".join(child.itertext()), bold, italic, Pt(8.8))
                r.font.name = MONO
                r._r.get_or_add_rPr().append(self._shd("F1F1F1"))
            elif tag == "a":
                self._link(p, child, bold, size)
            elif tag == "br":
                p.add_run().add_break()
            else:
                self.inline(p, child, bold, italic, size)
            if child.tail:
                self._run(p, child.tail, bold, italic, size)

    def _run(self, p, text: str, bold: bool, italic: bool, size: Pt | None):
        text = text.replace("\n", " ")
        r = p.add_run(text)
        r.bold = bold or None
        r.italic = italic or None
        if size:
            r.font.size = size
        return r

    @staticmethod
    def _shd(fill: str):
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"), shd.set(qn("w:color"), "auto"), shd.set(qn("w:fill"), fill)
        return shd

    def _link(self, p, a: ET.Element, bold: bool, size: Pt | None) -> None:
        href = a.get("href", "")
        link = OxmlElement("w:hyperlink")
        if href.startswith("#"):
            link.set(qn("w:anchor"), self.anchors.get(href[1:], ""))
        else:
            if href.endswith(".md") and "://" not in href:
                href = REPO_BLOB + href
            link.set(qn("r:id"), self.doc.part.relate_to(href, RT.HYPERLINK, is_external=True))
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        color, u = OxmlElement("w:color"), OxmlElement("w:u")
        color.set(qn("w:val"), "333333"), u.set(qn("w:val"), "single")
        rpr.append(color), rpr.append(u)
        if bold:
            rpr.append(OxmlElement("w:b"))
        if size:
            sz = OxmlElement("w:sz")
            sz.set(qn("w:val"), str(int(size.pt * 2)))
            rpr.append(sz)
        t = OxmlElement("w:t")
        t.text = "".join(a.itertext())
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(rpr), r.append(t)
        link.append(r)
        p._p.append(link)

    # ---- 块级 ----

    def toc(self) -> None:
        self.para("Chapter Title", "目录")
        p = self.doc.add_paragraph()
        for kind, text in (("begin", None), (None, 'TOC \\o "1-2" \\h \\z \\u'), ("separate", None),
                           (None, "（在 Word 中右键此处 →「更新域」生成目录与页码）"), ("end", None)):
            r = OxmlElement("w:r")
            if kind:
                fc = OxmlElement("w:fldChar")
                fc.set(qn("w:fldCharType"), kind)
                r.append(fc)
            elif text.startswith("TOC"):
                it = OxmlElement("w:instrText")
                it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                it.text = f" {text} "
                r.append(it)
            else:
                t = OxmlElement("w:t")
                t.text = text
                r.append(t)
            p._p.append(r)

    def heading(self, style: str, text_node: ET.Element, hid: str, level: int, label: str | None = None):
        if label is not None:
            num = self.para("Chapter Number", label)
            num.paragraph_format.page_break_before = True
            num.paragraph_format.keep_with_next = True
        p = self.para(style)
        self.inline(p, text_node)
        p.paragraph_format.keep_with_next = True
        set_ppr(p, "w:outlineLvl", val=level)
        self.bid += 1
        add_bookmark(p, self.anchors[hid], self.bid)
        return p

    def block(self, el: ET.Element, indent: float = 0) -> None:
        tag = el.tag
        if tag == "h2":
            hid = el.get("id")
            title = "".join(el.itertext())
            head, _, rest = title.partition("、")
            if head in CN_NUM:
                label, el = f"第 {CN_NUM[head]} 章", self._strip_prefix(el, head + "、")
            else:
                label = "附录"
            self.heading("Chapter Title", el, hid, 0, label)
        elif tag == "h3":
            self.heading("H2 Book", el, el.get("id"), 1)
        elif tag == "h4":
            p = self.para("H3 Book")
            self.inline(p, el)
        elif tag == "p":
            self._paragraph(el, indent)
        elif tag == "blockquote":
            paras = list(el)
            only_bold = len(paras) == 1 and not (paras[0].text or "").strip() and len(paras[0]) == 1 \
                and paras[0][0].tag == "strong" and not (paras[0][0].tail or "").strip()
            for child in paras:
                p = self.para("Key Insight" if only_bold else "Important Note")
                self.inline(p, child[0] if only_bold else child)
                if only_bold:
                    set_ppr(p, "w:ind", left=198, right=113)
                    left_bar(p, "666666", 18, "F1F1F1")
        elif tag == "pre":
            p = self.para("Code Book")
            lines = "".join(el.itertext()).rstrip("\n").split("\n")
            for i, line in enumerate(lines):
                if i:
                    p.add_run().add_break()
                p.add_run(line)
            if indent:
                p.paragraph_format.left_indent = Cm(0.2) + Pt(indent)
        elif tag in ("ul", "ol"):
            for n, li in enumerate(el.findall("li"), 1):
                self._list_item(li, "•" if tag == "ul" else f"{n}.", indent)
        elif tag == "table":
            self._table(el)
        elif tag == "hr":
            pass

    @staticmethod
    def _strip_prefix(el: ET.Element, prefix: str) -> ET.Element:
        el = copy.deepcopy(el)
        if el.text and el.text.startswith(prefix):
            el.text = el.text[len(prefix):]
        return el

    def _paragraph(self, el: ET.Element, indent: float) -> None:
        img = el.find("img")
        if img is not None and not (el.text or "").strip():
            self._figure(img)
            return
        if len(el) == 1 and el[0].tag == "em" and not (el.text or "").strip():
            p = self.para("Source Note")
            self.inline(p, el[0])
            return
        p = self.para("Body CN")
        self.inline(p, el)
        if indent:
            p.paragraph_format.left_indent = Pt(indent)
            p.paragraph_format.first_line_indent = Pt(0)

    def _list_item(self, li: ET.Element, marker: str, indent: float) -> None:
        step = 21.0
        p = self.para("Body CN")
        pf = p.paragraph_format
        pf.left_indent, pf.first_line_indent = Pt(indent + step), Pt(-step * 0.6)
        pf.space_after = Pt(3)
        p.add_run(f"{marker}\u2002")
        head = ET.Element("span")
        head.text = li.text
        blocks = []
        for child in li:
            if child.tag in ("p", "ul", "ol", "pre", "table", "blockquote"):
                blocks.append(child)
            elif not blocks:
                head.append(child)
            else:
                blocks.append(child)
        if not (head.text or "").strip() and len(head) == 0 and blocks and blocks[0].tag == "p":
            head = blocks.pop(0)
        self.inline(p, head)
        for b in blocks:
            self.block(b, indent + step)

    def _table(self, el: ET.Element) -> None:
        rows = el.findall(".//tr")
        ncols = max(len(list(r)) for r in rows)
        table = self.doc.add_table(rows=len(rows), cols=ncols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        tblpr = table._tbl.tblPr
        mar = OxmlElement("w:tblCellMar")
        for side, v in (("top", 70), ("left", 110), ("bottom", 70), ("right", 110)):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(v)), el.set(qn("w:type"), "dxa")
            mar.append(el)
        tblpr.append(mar)
        lengths = [max(min(len("".join(tr[c].itertext())), 40) for tr in rows if c < len(tr)) + 4
                   for c in range(ncols)]
        total_cm = 16.2
        widths = [Cm(total_cm * n / sum(lengths)) for n in lengths]
        for row in table.rows:
            for c, cell in enumerate(row.cells):
                cell.width = widths[c]
        for ri, tr in enumerate(rows):
            header = tr[0].tag == "th"
            last = ri == len(rows) - 1
            for ci, td in enumerate(tr):
                cell = table.cell(ri, ci)
                cell_borders(
                    cell,
                    top=(8, "666666") if header else None,
                    bottom=(8, "666666") if last else (3, "CCCCCC"),
                    fill="F2F2F2" if header else None,
                )
                p = cell.paragraphs[0]
                p.style = self.doc.styles["Body CN"]
                pf = p.paragraph_format
                pf.first_line_indent, pf.space_after, pf.line_spacing = Pt(0), Pt(0), 1.3
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                self.inline(p, td, bold=header, size=Pt(9.5 if header else 9))
                if header:
                    for r in p.runs:
                        r.font.name = "Noto Sans CJK SC"
                        r._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "Noto Sans CJK SC")
        self.para("Body CN").paragraph_format.space_after = Pt(2)

    def _figure(self, img: ET.Element) -> None:
        src = (self.md_dir / img.get("src")).resolve()
        if src.suffix.lower() == ".svg":
            src = svg_to_png(src, self.img_dir, self.browser)
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(6)
        p.add_run().add_picture(str(src), width=Cm(13.5))
        self.fig += 1
        self.para("Caption Book", f"图 {self.fig}  {img.get('alt', '')}")

    def build(self, html_body: str, out: Path) -> None:
        root = ET.fromstring(f"<root>{html_body}</root>")
        for n, h in enumerate(root.iter()):
            if h.tag in ("h2", "h3") and h.get("id"):
                self.anchors[h.get("id")] = f"sec_{n}"
        self.toc()
        for el in root:
            self.block(el)
        set_properties(self.doc)
        self.doc.save(str(out))


def set_properties(doc) -> None:
    props = doc.core_properties
    props.title = f"{COVER['title']}：{COVER['subtitle']}"
    props.author = props.last_modified_by = "Howard"
    props.subject = props.keywords = props.comments = props.category = ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default="新手图文教程.md")
    ap.add_argument("--template", default=str(HERE / "书籍模版.docx"))
    ap.add_argument("--props-only", metavar="DOCX", help="只重写已有 docx 的文档属性（Word 保存后会写入本机账户名）")
    args = ap.parse_args()
    if args.props_only:
        doc = Document(args.props_only)
        set_properties(doc)
        doc.save(args.props_only)
        return
    src = HERE / args.source
    template = Path(args.template)
    if not template.exists():
        sys.exit(f"找不到模板：{template}（用 --template 指定书籍模版.docx 的路径）")

    text = re.sub(r"⌘\s?(\S)", r"Command + \1", prepare_markdown(src.read_text(encoding="utf-8")))
    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": github_slug}},
    )
    out = src.with_suffix(".docx")
    with tempfile.TemporaryDirectory() as tmp:
        Builder(template, src.parent, Path(tmp), find_browser()).build(html_body, out)
    print(f"Word → {out}")


if __name__ == "__main__":
    main()
