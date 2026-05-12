#!/usr/bin/env python3
"""
MCA – Legal Report PDF Generator
Converts Markdown + YAML frontmatter to a professional A4 PDF.

Usage:
    python generate_pdf.py input.md              # saves input.pdf next to input.md
    python generate_pdf.py input.md output.pdf

Citation syntax in Markdown:
    [display text](dejure:DOCUMENT_ID)   →  https://app.dejure.ai/dokuman/ID
    [display text](https://...)          →  standard hyperlink

Requirements:
    pip install reportlab
"""

import os, re, sys

# ── ReportLab imports ─────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, HRFlowable, PageBreak, KeepTogether, Image
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.lib.utils import ImageReader


# ── Brand colours ─────────────────────────────────────────────────────────────
BRAND_DARK   = colors.HexColor("#0F172A")   # slate-900
BRAND_ACCENT = colors.HexColor("#475569")   # slate-600
BRAND_LIGHT  = colors.HexColor("#F8FAFC")   # slate-50 (table header bg)
TEXT_COLOR   = colors.HexColor("#1A1A1A")
LINK_COLOR   = colors.HexColor("#1A56A8")
RULE_COLOR   = BRAND_DARK

PAGE_W, PAGE_H = A4
MARGIN_L, MARGIN_R = 2.5 * cm, 2.5 * cm
MARGIN_T, MARGIN_B = 3.2 * cm, 2.8 * cm
USABLE_W = PAGE_W - MARGIN_L - MARGIN_R

# ── Logo path resolution ───────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGO_CANDIDATES = [
    os.path.join(_SCRIPT_DIR, "logo.png"),
    os.path.join(_SCRIPT_DIR, "..", "logo.png"),
]
LOGO_PATH: str | None = next((p for p in _LOGO_CANDIDATES if os.path.isfile(p)), None)
COVER_LOGO_HEIGHT = 1.8 * cm
HEADER_LOGO_HEIGHT = 0.55 * cm
LOGO_HORIZONTAL_STRETCH = 1.9


# ── Font registration ─────────────────────────────────────────────────────────
def _register_fonts():
    """Register a Unicode font that supports Turkish. Returns (normal, bold, italic)."""

    # 1) Liberation Sans — common on Linux
    lib_paths = [
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
        ("/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
         "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
    ]
    for reg, bold, italic, bi in lib_paths:
        d = os.path.dirname(reg)
        if os.path.isfile(reg):
            try:
                pdfmetrics.registerFont(TTFont("DocSans",            reg))
                pdfmetrics.registerFont(TTFont("DocSans-Bold",       os.path.join(d, bold)))
                pdfmetrics.registerFont(TTFont("DocSans-Italic",     os.path.join(d, italic)))
                pdfmetrics.registerFont(TTFont("DocSans-BoldItalic", os.path.join(d, bi)))
                registerFontFamily("DocSans", normal="DocSans", bold="DocSans-Bold",
                                   italic="DocSans-Italic", boldItalic="DocSans-BoldItalic")
                return "DocSans", "DocSans-Bold", "DocSans-Italic"
            except Exception:
                pass

    # 2) Arial — macOS / Windows / some Linux (full Turkish support)
    arial_candidates = [
        # macOS
        ("/System/Library/Fonts/Supplemental/Arial.ttf",
         "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
        # macOS alternate location
        ("/Library/Fonts/Arial.ttf",
         "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
        # Windows
        (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
         "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
        # Linux msttcorefonts
        ("/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
         "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    ]
    for reg, bold, italic, bi in arial_candidates:
        d = os.path.dirname(reg)
        if os.path.isfile(reg):
            try:
                b_path  = os.path.join(d, bold)
                it_path = os.path.join(d, italic)
                bi_path = os.path.join(d, bi)
                pdfmetrics.registerFont(TTFont("DocSans",            reg))
                pdfmetrics.registerFont(TTFont("DocSans-Bold",       b_path  if os.path.isfile(b_path)  else reg))
                pdfmetrics.registerFont(TTFont("DocSans-Italic",     it_path if os.path.isfile(it_path) else reg))
                pdfmetrics.registerFont(TTFont("DocSans-BoldItalic", bi_path if os.path.isfile(bi_path) else reg))
                registerFontFamily("DocSans", normal="DocSans", bold="DocSans-Bold",
                                   italic="DocSans-Italic", boldItalic="DocSans-BoldItalic")
                return "DocSans", "DocSans-Bold", "DocSans-Italic"
            except Exception:
                pass

    # 3) Last resort: built-in Helvetica (no ğ, ı, ş, ö, ü, ç)
    print("⚠  Warning: Turkish-capable font not found. Output may have missing characters.")
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


FONT_N, FONT_B, FONT_I = _register_fonts()


# ── Styles ────────────────────────────────────────────────────────────────────
def build_styles():
    s = {}

    def ps(name, **kw):
        base = kw.pop("parent", None)
        defaults = dict(fontName=FONT_N, fontSize=10, leading=15,
                        textColor=TEXT_COLOR, spaceAfter=4, spaceBefore=2)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    s["cover_firm"]    = ps("cover_firm",    fontName=FONT_B, fontSize=11, textColor=BRAND_ACCENT,
                             alignment=TA_CENTER, spaceAfter=6)
    s["cover_title"]   = ps("cover_title",   fontName=FONT_B, fontSize=22, textColor=BRAND_DARK,
                             alignment=TA_CENTER, leading=28, spaceAfter=10)
    s["cover_konu"]    = ps("cover_konu",    fontName=FONT_I, fontSize=12, textColor=TEXT_COLOR,
                             alignment=TA_CENTER, spaceAfter=20)
    s["cover_meta"]    = ps("cover_meta",    fontName=FONT_N, fontSize=9,  textColor=TEXT_COLOR,
                             alignment=TA_CENTER, spaceAfter=4)
    s["cover_gizli"]   = ps("cover_gizli",   fontName=FONT_B, fontSize=9,  textColor=BRAND_ACCENT,
                             alignment=TA_CENTER, spaceAfter=4)

    s["toc_title"]     = ps("toc_title",     fontName=FONT_B, fontSize=13, textColor=BRAND_DARK,
                             spaceAfter=12)
    s["toc_item"]      = ps("toc_item",      fontName=FONT_N, fontSize=10, spaceAfter=5)

    s["h1"]            = ps("h1",            fontName=FONT_B, fontSize=14, textColor=BRAND_DARK,
                             spaceBefore=18, spaceAfter=6, leading=18)
    s["h2"]            = ps("h2",            fontName=FONT_B, fontSize=12, textColor=BRAND_DARK,
                             spaceBefore=12, spaceAfter=4, leading=16)
    s["h3"]            = ps("h3",            fontName=FONT_B, fontSize=10.5, textColor=BRAND_DARK,
                             spaceBefore=8,  spaceAfter=3, leading=14)
    s["body"]          = ps("body",          alignment=TA_JUSTIFY, spaceAfter=6, leading=15)
    s["bullet"]        = ps("bullet",        leftIndent=14, spaceAfter=4)
    s["numbered"]      = ps("numbered",      leftIndent=14, spaceAfter=4)
    s["quote"]         = ps("quote",         fontName=FONT_I, fontSize=9.5, leftIndent=18,
                             rightIndent=10, spaceAfter=8, textColor=colors.HexColor("#444444"),
                             leading=14)
    s["table_hdr"]     = ps("table_hdr",     fontName=FONT_B, fontSize=8.5, textColor=BRAND_DARK,
                             alignment=TA_CENTER, leading=12)
    s["table_cell"]    = ps("table_cell",    fontName=FONT_N, fontSize=8.5, leading=12, spaceAfter=2)
    s["caption"]       = ps("caption",       fontName=FONT_I, fontSize=8, textColor=colors.grey,
                             spaceAfter=10, alignment=TA_CENTER)
    return s


# ── Anchor helpers ────────────────────────────────────────────────────────────
_anchor_seen:  dict = {}
_valid_anchors: set = set()   # populated before rendering; used by fmt()

def heading_anchor(text: str) -> str:
    """Generate a GitHub-style anchor ID from heading text (handles duplicates)."""
    # Strip inline markdown before computing ID
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links → text
    clean = re.sub(r"[*_`]", "", clean)
    anchor = clean.lower()
    anchor = re.sub(r"\s+", "-", anchor)
    # Keep unicode word chars (covers Turkish letters) and hyphens
    anchor = re.sub(r"[^\w\-]", "", anchor, flags=re.UNICODE)
    anchor = re.sub(r"-+", "-", anchor).strip("-")
    base = anchor or "section"
    if base in _anchor_seen:
        _anchor_seen[base] += 1
        anchor = f"{base}-{_anchor_seen[base]}"
    else:
        _anchor_seen[base] = 0
    return anchor


# ── Inline text formatter ─────────────────────────────────────────────────────
def fmt(text: str) -> str:
    """Convert inline Markdown to ReportLab Paragraph XML."""
    # 1. Escape bare ampersands not already part of an entity
    text = re.sub(r"&(?!#?\w+;)", "&amp;", text)
    # 2. Links: [text](dejure:ID), [text](#anchor), [text](https://...)
    def repl_link(m):
        link_text = m.group(1)
        url = m.group(2).strip()
        if url.startswith("#"):
            # Internal PDF anchor — only emit if the destination heading exists
            if url[1:] in _valid_anchors:
                return f'<link href="{url}" color="{LINK_COLOR.hexval()}">{link_text}</link>'
            return link_text  # destination not in document, keep as plain text
        if url.startswith("dejure:"):
            url = f"https://app.dejure.ai/dokuman/{url[7:]}"
        elif url.startswith("jurix:"):
            url = f"https://www.jurix.com.tr/article/{url[6:]}"
        if not url.startswith("http"):
            return link_text  # unrecognised scheme — plain text
        return f'<link href="{url}" color="{LINK_COLOR.hexval()}">{link_text}</link>'
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", repl_link, text)
    # 3. Bold-italic, bold, italic, code (use [^*]+ to avoid catastrophic backtracking)
    text = re.sub(r"\*\*\*([^*]+)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*([^*]+)\*\*",     r"<b>\1</b>",         text)
    text = re.sub(r"\*([^*]+)\*",         r"<i>\1</i>",          text)
    text = re.sub(r"`([^`]+)`",           r'<font face="Courier">\1</font>', text)
    return text


# ── Frontmatter parser ────────────────────────────────────────────────────────
def parse_frontmatter(text: str):
    """Return (meta_dict, body_str). Handles optional --- delimiters."""
    meta, body = {}, text
    if text.lstrip().startswith("---"):
        parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()
    return meta, body


# ── Markdown block parser ─────────────────────────────────────────────────────
def parse_blocks(body: str):
    """State-machine parser. Returns list of (kind, content) tuples."""
    blocks = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Explicit page break
        if stripped.lower() in ("<pagebreak>", "<!-- pagebreak -->", "\\pagebreak"):
            blocks.append(("pagebreak", None))
            i += 1
            continue

        # Headings (H1–H6; H4+ rendered as h3)
        if stripped.startswith("#### ") or stripped.startswith("##### ") or stripped.startswith("###### "):
            blocks.append(("h3", re.sub(r"^#{4,6}\s+", "", stripped)))
            i += 1; continue
        if stripped.startswith("### "):
            blocks.append(("h3", stripped[4:]))
            i += 1; continue
        if stripped.startswith("## "):
            blocks.append(("h2", stripped[3:]))
            i += 1; continue
        if stripped.startswith("# "):
            blocks.append(("h1", stripped[2:]))
            i += 1; continue

        # Horizontal rule  (--- alone on a line, not frontmatter)
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            blocks.append(("hr", None))
            i += 1; continue

        # Blockquote — collect consecutive > lines
        if line.startswith("> ") or stripped == ">":
            q_lines = []
            while i < len(lines) and (lines[i].startswith("> ") or lines[i].strip() == ">"):
                q_lines.append(lines[i][2:] if lines[i].startswith("> ") else "")
                i += 1
            blocks.append(("quote", " ".join(q_lines).strip()))
            continue

        # Table — collect consecutive | lines
        if stripped.startswith("|"):
            tbl_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i])
                i += 1
            blocks.append(("table", tbl_lines))
            continue

        # Bullet list
        if re.match(r"^[-*+] ", stripped):
            items = []
            while i < len(lines) and re.match(r"^[-*+] ", lines[i].strip()):
                items.append(lines[i].strip()[2:])
                i += 1
            blocks.append(("bullets", items))
            continue

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            blocks.append(("numbered", items))
            continue

        # Paragraph — collect until blank line or block-level marker
        para_lines = []
        while i < len(lines):
            ln = lines[i]
            s  = ln.strip()
            if not s:
                break
            if (re.match(r"^#{1,6}\s", s) or s.startswith("|") or s.startswith(">")
                    or re.match(r"^[-*+] ", s) or re.match(r"^\d+\.\s", s)
                    or re.match(r"^(-{3,}|\*{3,}|_{3,})$", s)
                    or s.lower() in ("<pagebreak>", "<!-- pagebreak -->")):
                break
            para_lines.append(ln)
            i += 1
        if para_lines:
            blocks.append(("para", " ".join(para_lines)))
        else:
            # Safety: advance past an unrecognised line to prevent infinite loop
            i += 1
        continue

    return blocks


# ── Table builder ─────────────────────────────────────────────────────────────
def build_table(md_lines, styles):
    rows = []
    for line in md_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(re.match(r"^[-:]+$", c) for c in cells if c):
            continue  # skip separator row
        rows.append(cells)

    if not rows:
        return None

    n_cols = max(len(r) for r in rows)
    col_w  = USABLE_W / n_cols

    data = []
    for idx, row in enumerate(rows):
        # Pad short rows
        while len(row) < n_cols:
            row.append("")
        if idx == 0:
            data.append([Paragraph(f"<b>{fmt(c)}</b>", styles["table_hdr"]) for c in row])
        else:
            data.append([Paragraph(fmt(c), styles["table_cell"]) for c in row])

    tbl = Table(data, colWidths=[col_w] * n_cols, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_LIGHT),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  BRAND_DARK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F9F9F9")]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


# ── Flowable helpers ──────────────────────────────────────────────────────────
def section_rule():
    return HRFlowable(width="100%", thickness=1.5, color=BRAND_DARK,
                      spaceAfter=4, spaceBefore=16)

def thin_rule():
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC"),
                      spaceAfter=4, spaceBefore=4)

def accent_rule():
    return HRFlowable(width="100%", thickness=3, color=BRAND_ACCENT,
                      spaceAfter=6, spaceBefore=2)


# ── Blocks → Flowables ────────────────────────────────────────────────────────
def blocks_to_story(blocks, styles):
    story   = []
    h1_list = []  # for TOC
    # Reset per-document anchor seen-set so duplicate headings get unique IDs
    _anchor_seen.clear()

    for kind, content in blocks:

        if kind == "pagebreak":
            story.append(PageBreak())

        elif kind == "h1":
            anchor = heading_anchor(content)
            story.append(section_rule())
            p = Paragraph(f'<a name="{anchor}"/>{fmt(content)}', styles["h1"])
            story.append(KeepTogether([p, Spacer(1, 4)]))
            h1_list.append(content)

        elif kind == "h2":
            anchor = heading_anchor(content)
            p = Paragraph(f'<a name="{anchor}"/>{fmt(content)}', styles["h2"])
            story.append(KeepTogether([Spacer(1, 6), p, Spacer(1, 2)]))

        elif kind == "h3":
            anchor = heading_anchor(content)
            story.append(Paragraph(f'<a name="{anchor}"/>{fmt(content)}', styles["h3"]))

        elif kind == "hr":
            story.append(thin_rule())

        elif kind == "quote":
            story.append(Paragraph(fmt(content), styles["quote"]))

        elif kind == "para":
            story.append(Paragraph(fmt(content), styles["body"]))

        elif kind == "bullets":
            items = [Paragraph(f"• &nbsp;{fmt(it)}", styles["bullet"]) for it in content]
            story.extend(items)

        elif kind == "numbered":
            for n, it in enumerate(content, 1):
                story.append(Paragraph(f"{n}. &nbsp;{fmt(it)}", styles["numbered"]))

        elif kind == "table":
            tbl = build_table(content, styles)
            if tbl:
                story.append(Spacer(1, 4))
                story.append(tbl)
                story.append(Spacer(1, 6))

    return story, h1_list


# ── Cover page ────────────────────────────────────────────────────────────────
def build_cover(meta, styles):
    story = []

    story.append(Spacer(1, 2.5 * cm))
    story.append(accent_rule())
    story.append(Spacer(1, 0.6 * cm))

    logo_path = meta.get("logo", LOGO_PATH)
    if logo_path and os.path.isfile(str(logo_path)):
        logo_img = Image(logo_path)
        logo_img.drawHeight = COVER_LOGO_HEIGHT
        logo_img.drawWidth = (
            logo_img.drawHeight
            * (logo_img.imageWidth / logo_img.imageHeight)
            * LOGO_HORIZONTAL_STRETCH
        )
        logo_img.hAlign = "CENTER"
        story.append(logo_img)
        story.append(Spacer(1, 0.4 * cm))
    else:
        story.append(Paragraph("MCA LEGAL", styles["cover_firm"]))
        story.append(Spacer(1, 0.3 * cm))

    title = meta.get("title", "Hukuki Değerlendirme Raporu")
    story.append(Paragraph(fmt(title), styles["cover_title"]))

    konu = meta.get("konu", "")
    if konu:
        story.append(Paragraph(fmt(konu), styles["cover_konu"]))

    story.append(Spacer(1, 0.8 * cm))
    story.append(accent_rule())
    story.append(Spacer(1, 1.5 * cm))

    meta_rows = [
        ("Dosya",       meta.get("dosya", "")),
        ("Muhatap",     meta.get("muhatap", "")),
        ("Hazırlayan",  meta.get("hazirlayan", "mca")),
        ("Tarih",       meta.get("tarih", "")),
    ]
    for label, value in meta_rows:
        if value:
            story.append(Paragraph(f"<b>{label}:</b>  {fmt(value)}", styles["cover_meta"]))

    gizli = meta.get("gizlilik", "")
    if gizli:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(f"— {gizli} —", styles["cover_gizli"]))

    story.append(PageBreak())
    return story


# ── TOC ───────────────────────────────────────────────────────────────────────
def build_toc(h1_list, styles):
    if not h1_list:
        return []
    story = []
    story.append(Paragraph("İÇİNDEKİLER", styles["toc_title"]))
    story.append(thin_rule())
    story.append(Spacer(1, 6))
    for i, heading in enumerate(h1_list, 1):
        story.append(Paragraph(f"{i}.  {fmt(heading)}", styles["toc_item"]))
    story.append(PageBreak())
    return story


# ── Header / Footer canvas ────────────────────────────────────────────────────
class LegalCanvas(BaseDocTemplate):
    def __init__(self, filename, meta, **kw):
        super().__init__(filename, **kw)
        self.meta = meta

    def handle_pageBegin(self):
        super().handle_pageBegin()

    def afterPage(self):
        c   = self.canv
        w   = PAGE_W
        num = c.getPageNumber()

        # Skip header/footer on cover (page 1) and TOC (page 2)
        if num <= 2:
            return

        c.saveState()

        # Header line
        c.setStrokeColor(BRAND_DARK)
        c.setLineWidth(0.5)
        c.line(MARGIN_L, PAGE_H - 1.8 * cm, w - MARGIN_R, PAGE_H - 1.8 * cm)

        # Header: logo (or firm name) left, document title right
        logo_path = self.meta.get("logo", LOGO_PATH)
        if logo_path and os.path.isfile(str(logo_path)):
            img_reader = ImageReader(logo_path)
            iw, ih = img_reader.getSize()
            logo_h = HEADER_LOGO_HEIGHT
            logo_w = logo_h * (iw / ih) * LOGO_HORIZONTAL_STRETCH
            c.drawImage(logo_path, MARGIN_L, PAGE_H - 1.65 * cm,
                        width=logo_w, height=logo_h, preserveAspectRatio=True, mask="auto")
        else:
            c.setFont(FONT_N, 8)
            c.setFillColor(BRAND_DARK)
            c.drawString(MARGIN_L, PAGE_H - 1.5 * cm, "MCA Legal")
        doc_title = self.meta.get("dosya", self.meta.get("title", ""))
        c.setFont(FONT_N, 8)
        c.setFillColor(BRAND_DARK)
        c.drawRightString(w - MARGIN_R, PAGE_H - 1.5 * cm, doc_title[:80])

        # Footer line
        c.line(MARGIN_L, 1.8 * cm, w - MARGIN_R, 1.8 * cm)

        # Footer text: gizlilik left, page number right
        gizli = self.meta.get("gizlilik", "")
        c.setFont(FONT_N, 7.5)
        c.setFillColor(colors.HexColor("#555555"))
        if gizli:
            c.drawString(MARGIN_L, 1.2 * cm, gizli)
        tarih = self.meta.get("tarih", "")
        if tarih:
            c.drawCentredString(w / 2, 1.2 * cm, tarih)
        c.drawRightString(w - MARGIN_R, 1.2 * cm, f"Sayfa {num}")

        c.restoreState()


# ── Main ──────────────────────────────────────────────────────────────────────
def generate(input_path: str, output_path: str | None = None):
    if output_path is None:
        base, _ = os.path.splitext(input_path)
        output_path = base + ".pdf"

    with open(input_path, encoding="utf-8") as f:
        raw = f.read()

    meta, body = parse_frontmatter(raw)
    styles     = build_styles()
    blocks     = parse_blocks(body)

    # Pre-pass: collect all anchor IDs that will be created on headings
    _anchor_seen.clear()
    _valid_anchors.clear()
    for kind, content in blocks:
        if kind in ("h1", "h2", "h3"):
            _valid_anchors.add(heading_anchor(content))

    body_story, h1_list = blocks_to_story(blocks, styles)

    cover  = build_cover(meta, styles)
    toc    = build_toc(h1_list, styles)
    story  = cover + toc + body_story

    frame = Frame(MARGIN_L, MARGIN_B, USABLE_W, PAGE_H - MARGIN_T - MARGIN_B,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    doc = LegalCanvas(
        output_path, meta,
        pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T,  bottomMargin=MARGIN_B,
        title=meta.get("title", ""),
        author="mca",
        subject=meta.get("konu", ""),
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])
    doc.build(story)

    print(f"✓  PDF saved: {output_path}")

    # Summary: count linkable citations
    dj_ids    = re.findall(r"\]\(dejure:([^)]+)\)", body)
    jx_ids    = re.findall(r"\]\(jurix:([^)]+)\)", body)
    if dj_ids:
        print(f"   {len(set(dj_ids))} unique DeJure citation(s) embedded as clickable links.")
    if jx_ids:
        print(f"   {len(set(jx_ids))} unique Jurix citation(s) embedded as clickable links.")
    # Warn about links that aren't a known scheme, http(s)://, or internal anchors
    no_link = re.findall(r"\]\((?!https?://|dejure:|jurix:|#)([^)]+)\)", body)
    if no_link:
        print(f"   Note: {len(no_link)} link(s) with unrecognised scheme (treated as plain text).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    generate(inp, out)
