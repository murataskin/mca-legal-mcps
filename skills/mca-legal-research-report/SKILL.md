---
name: mca-legal-research-report
description: >-
  Conducts Turkish legal research using dejure, yargi, jurix, mevzuat, yoktez
  MCP tools, then produces a structured Markdown report with inline citations
  and converts it to a professional PDF. Use when asked to research
  a Turkish legal question, produce a legal memo, hukuki değerlendirme raporu,
  içtihat araştırması, or any combination of legal research + report + PDF.
---

# Turkish Legal Research & Report Generator

Author: **mca**

## Workflow Overview

```
Phase 1 → Query Analysis
Phase 2 → Research Planning & Execution (tools)
Phase 3 → NotebookLM Grounding (optional)
Phase 4 → Write Markdown Report (with citation syntax)
Phase 5 → Generate Professional PDF
```

---

## Phase 1: Query Analysis

Before touching any tool, internalize:

1. **Legal domain**: TBK, TTK, HMK, TCK, İş Hukuku, Deniz Ticareti, Sigorta, etc.
2. **Core question**: State it as a single sentence.
3. **Sub-issues**: List 2–5 discrete issues the report must address.
4. **Key statutes**: Which code articles are central?
5. **Report type**: Choose from the archetypes in [references/report-structure.md](references/report-structure.md) and adapt to the specific question.

---

## Phase 2: Research Planning & Execution

### Tool Selection

Autonomously decide which tools to query and how many searches to run based on complexity. You do **not** need to use all tools for every question.

| Signal | Prefer |
|---|---|
| Need binding case law (Yargıtay/HGK) | `dejure` + `yargi` |
| Need academic depth / doctrine | `jurix` |
| Need statute text / gerekçe | `mevzuat` |
| Need theses | `yoktez` |
| General / broad questions | all tools |

Run searches **in parallel** where possible.

### Capture IDs During Research — Per-Tool Rules

Each tool returns different fields. Apply these rules immediately when a result will be cited:

#### DeJure (`search_precedents`) — ✅ linkable
Extract `documentID` (UUID string) from each result object.
```
result.documentID  →  "8f67520f-6711-44f2-ad9e-3ea62f569cbb"
result.daire       →  "Yargıtay Hukuk Genel Kurulu"
result.esasNo      →  "2015/837"
result.kararNo     →  "2019/253"
result.kararTarihi →  "07.03.2019"
```
Citation syntax: `[{daire}, E.{esasNo}, K.{kararNo}](dejure:{documentID})`

For **central authorities**, do not cite decisions as bare strings only. Briefly state the operative rationale or holding in the sentence or the next sentence. When helpful, include a short quoted expression from the decision, but keep it brief.

#### Bedesten / Yargi (`search_bedesten_unified`) — ❌ no public URL
Extract `documentId` (integer) — use only to fetch full text via `get_bedesten_document_markdown`.
Do **not** create a link in the report. Cite as plain text: `Yargıtay 4. HD, E.2026/1742, K.2026/2195`

#### Emsal (`search_emsal_detailed_decisions`) — ❌ no public URL
Same approach as Bedesten. Use `id` field to fetch full text only. Cite as plain text.

#### Jurix (`jurix_search`) — ✅ linkable (call `jurix_ensure_pool` first)
Extract `id` from each result object. The `link` field contains the full URL but with session params — use only the clean base URL.
```
result.id      →  "22389"
result.title   →  "Müteselsil Sorumluluk ve İşçi Alacakları"
result.author  →  "Yonca BAYRAK"
result.journal →  "Bursa Barosu Dergisi"
result.issue_date → "Sayı:115 - Mart 2021"
```
Citation syntax: `[{author}, "{title}" ({journal}, {issue_date})](jurix:{id})`

#### YÖK Tez (`search_yok_tez_detailed`) — ✅ linkable via full URL
Extract `detail_page_url` — it is already a complete `https://` link to the YÖK Tez detail page.
```
result.detail_page_url  →  "https://tez.yok.gov.tr/UlusalTezMerkezi/tezDetay.jsp?id=...&no=..."
result.thesis_no        →  "123456"
result.title            →  "Türk Borçlar Hukukunda Müteselsil Sorumluluk"
result.author           →  "YILMAZ, Ayşe"
result.year             →  "2022"
result.university_info  →  "İstanbul Üniversitesi, Sosyal Bilimler Enstitüsü"
result.thesis_type      →  "Doktora"
```
Citation syntax: `[{author}, "{title}" ({thesis_type}, {university_info}, {year})]({detail_page_url})`

No custom scheme needed — `detail_page_url` is a standard `https://` link.

#### Mevzuat — no ID needed
Cite statute articles directly: `TBK m. 61/1`, `TTK m. 1062/2`

**Running list format** — maintain this while researching:
```
| Kaynak   | Künye                                                | Link / ID                                         |
|----------|------------------------------------------------------|---------------------------------------------------|
| dejure   | Yargıtay HGK, E.2015/837, K.2019/253                | dejure:8f67520f-6711-44f2-ad9e-3ea62f569cbb       |
| bedesten | Yargıtay 4. HD, E.2026/1742, K.2026/2195            | —                                                 |
| jurix    | BAYRAK, "Müteselsil Sorumluluk…", BBD 2021          | jurix:22389                                       |
| yoktez   | YILMAZ, "TBK'da Müteselsil…", Doktora, İÜ, 2022    | https://tez.yok.gov.tr/...tezDetay.jsp?id=...     |
```
DeJure (`dejure:`), Jurix (`jurix:`), and YÖK Tez (`https://`) rows become clickable links; Bedesten/Emsal do not.

### Minimum Research Checklist

- [ ] At least 3 directly relevant Yargıtay or HGK decisions
- [ ] Relevant TBK/TTK/HMK articles confirmed via `mevzuat`
- [ ] Key doctrine position (jurix or yoktez if available)
- [ ] Any lower court (BAM or ATM) decisions if needed for factual similarity

---

## Phase 3: NotebookLM Grounding (Optional)

Use NotebookLM when:
- The question is complex enough to benefit from grounded synthesis
- The user mentions an existing notebook
- You want to cross-check your analysis

### Using an Existing Notebook

Before using an existing notebook, **verify compatibility**:
1. Query the notebook with your core legal question.
2. Check if sources cover the relevant legal domains and time period.
3. If the notebook is incompatible (wrong domain, stale sources), skip it or note the limitation.

### Building a New Notebook Session

1. Download full-text documents from jurix or yoktez where available:
   - Use jurix document-download tools to fetch PDFs of key decisions.
   - Use yoktez tools to fetch relevant thesis sections.
2. Add each downloaded document as a source (`source_add` with `source_type=file`).
3. Add the statute text as a text source.
4. Query the notebook to synthesize and cross-check your conclusions.
5. Note the notebook ID in the report frontmatter.

---

## Phase 4: Write the Markdown Report

Save to `<project-dir>/<slug>-raporu.md`.

### Frontmatter (Required)

```yaml
---
title: Rapor Başlığı
konu: Tek cümle konu özeti
tarih: 13 Mart 2026
gizlilik: Çok Gizli
dosya: Dosya Adı / Referans
muhatap: Alıcı / Makam
hazirlayan: mca
---
```

### Citation Syntax

Two linkable schemes are supported:

```
[Görünen Metin](dejure:DOCUMENT_ID)   ← DeJure kararları
[Görünen Metin](jurix:ARTICLE_ID)     ← Jurix makale/doktrin
[Görünen Metin](https://...)          ← diğer URL'ler
```

**Examples:**
```markdown
Rücu hakkının kullanılabilmesi için ortada birden fazla borçlunun
bulunması yeterlidir [(Yargıtay HGK, E.2015/837, K.2019/253)](dejure:8f67520f-6711-44f2-ad9e-3ea62f569cbb).

Doktrinde de bu görüş benimsenmiştir [(BAYRAK, "Müteselsil Sorumluluk ve İşçi Alacakları")](jurix:22389).
```

For Bedesten/Emsal results (no public URL), cite as plain text:
```markdown
Yargıtay 4. HD, E.2026/1742, K.2026/2195 (Bedesten)
```

For legislation:
```markdown
TBK m. 61/1 uyarınca...
```

### Adaptive Structure

**Do not use a fixed template.** Adapt the report structure to the legal question. See [references/report-structure.md](references/report-structure.md) for archetype skeletons.

General rules:
- H1 (`#`) = major section (maps to numbered section in PDF, gets a horizontal rule)
- H2 (`##`) = subsection
- H3 (`###`) = sub-point
- `> blockquote` = statutory text, verbatim decision excerpts, key principles
- `| table |` = comparison tables, case matrices, multi-factor analyses
- `---` = visual section break (lighter than H1)
- `**bold**` = key legal terms, holdings, conclusions
- `*italic*` = latin phrases, foreign-language terms

### Drafting Style

- Prefer neutral, professional Turkish.
- When the available facts or documents are incomplete, use a concise and general formulation.
- If the report includes a section on uncertainty, exposure, or practical concerns, prefer headings such as `Başlıca Dikkat Noktaları`, `Belirsizlikler`, or integrated prose. Do **not** use scored or labeled risk categories.
- For key precedents, prefer `authority + reason` drafting. Example: instead of only citing `HGK, E..., K...`, explain in one clause what the court held and why it matters to the present issue.

### Mandatory Sections

Every report must include:

1. **Yönetici Özeti** — 3–5 bullet conclusions
2. **Olgusal Çerçeve** — facts relevant to the legal analysis
3. **Hukuki Sorun** — the primary question and sub-issues stated precisely
4. **Hukuki Analiz** — the core analysis (structure adapts to the question)
5. **Sonuç ve Stratejik Öneriler** — recommended actions and next steps
6. **Ek: Atıf Yapılan Kararlar** — table of all cited decisions

---

## Phase 5: Generate the PDF

Run the professional PDF generator against the markdown file:

```bash
python mca-legal-mcps/skills/mca-legal-research-report/scripts/generate_pdf.py <input.md> [output.pdf]
```

If `output.pdf` is omitted, the PDF is saved alongside the markdown file.

**Required Python packages** (install once):
```bash
pip install reportlab
```

The script:
- Parses YAML frontmatter → cover page metadata
- Converts H1/H2/H3 → styled headings with auto-generated TOC
- Converts `[text](dejure:ID)` → clickable link `https://app.dejure.ai/dokuman/ID`
- Converts standard `[text](URL)` → clickable hyperlink
- Converts tables, blockquotes, bullet lists, numbered lists
- Adds professional branding, header, footer, page numbers
- Uses Arial (macOS/Windows) or Liberation (Linux) for Turkish character support

### After Generating

Tell the user:
1. The path to the PDF
2. How many cases were cited and linked
3. Any cases that had no DeJure ID (no clickable link)

---

## Quick Reference

### Citation syntax
```
[display text](dejure:DOCUMENT_ID)     ← DeJure karar linki
[display text](jurix:ARTICLE_ID)       ← Jurix makale linki
[display text](URL)                    ← herhangi bir URL
```

### Frontmatter keys
`title`, `konu`, `tarih`, `gizlilik`, `dosya`, `muhatap`, `hazirlayan`

If `output.pdf` is omitted, the PDF is saved alongside the markdown file.

**Required Python packages** (install once):
```bash
pip install reportlab
```

The script:
- Parses YAML frontmatter → cover page metadata
- Converts H1/H2/H3 → styled headings with auto-generated TOC
- Converts `[text](dejure:ID)` → clickable link `https://app.dejure.ai/dokuman/ID`
- Converts standard `[text](URL)` → clickable hyperlink
- Converts tables, blockquotes, bullet lists, numbered lists
- Adds Araz & Ünlüeser branding, header, footer, page numbers
- Uses Arial (macOS/Windows) or Liberation (Linux) for Turkish character support

### After Generating

Tell the user:
1. The path to the PDF
2. How many cases were cited and linked
3. Any cases that had no DeJure ID (no clickable link)
4. Optional: the notebook ID if NotebookLM was used

---

## Quick Reference

### Citation syntax
```
[display text](dejure:DOCUMENT_ID)     ← DeJure karar linki
[display text](jurix:ARTICLE_ID)       ← Jurix makale linki
[display text](URL)                    ← herhangi bir URL
```

### Frontmatter keys
`title`, `konu`, `tarih`, `gizlilik`, `dosya`, `muhatap`, `hazirlayan`

### PDF generator
```bash
python ~/.cursor/skills/legal-research-report/scripts/generate_pdf.py report.md
```

### Report archetypes
See [references/report-structure.md](references/report-structure.md)
