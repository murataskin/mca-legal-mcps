---
name: udf-cli
description: Convert between HTML, Markdown, and UYAP UDF document format.
---

Use this skill to read, write, and manipulate UYAP `.udf` documents (Turkey's National Judiciary Informatics System format). AI agents work best by reading UDF files as Markdown and writing them as HTML with inline CSS.

### Core Capabilities

- **Read UDF:** Convert UDF files to Markdown for easy analysis.
- **Write UDF:** Convert Markdown or HTML to UDF for compatibility with UYAP.
- **Authoring:** Generate high-quality legal documents with tables, images, and specific formatting (Times New Roman, 12pt, justified text).

### How to use

#### Read a UDF file
To see the content of a UDF file, convert it to Markdown:
```bash
npx udf-cli udf2md <input.udf>
```

#### Create a UDF file from Markdown
```bash
npx udf-cli md2udf <input.md> <output.udf>
```

#### Create a UDF file from HTML (for rich formatting)
```bash
npx udf-cli html2udf '<p style="text-align:justify; font-family:Times New Roman; font-size:12pt">Legal text here...</p>' <output.udf>
```

### AI Authoring Rules for UDF

When generating documents, follow these standards for best UYAP compatibility:

1. **Units:** Always use `pt` for lengths (e.g., `font-size:12pt`).
2. **Typography:** Default is Times New Roman 12pt. Use `<strong>`, `<em>`, `<u>` for styles.
3. **Layout:** Use `<p style="text-align:justify; line-height:1.5; text-indent:24pt">` for standard legal paragraphs.
4. **Tables:** Use standard `<table>` with `border:1pt solid #000`.
5. **Tabs:** Use `<tab/>` to align with `tab-stops` (e.g., `<p style="tab-stops:200pt 400pt">Item<tab/>Value</p>`).
6. **Page Breaks:** Use `<page-break/>` ONLY if explicitly requested.
7. **Images:** Use `<img src="data:image/png;base64,...">` with `width` and `height` in `pt`.
8. **Line Breaks:** Use separate `<p>` tags instead of `<br>` for new paragraphs.

### Common CLI commands

- `npx udf-cli udf2md file.udf` - Print UDF content as Markdown.
- `npx udf-cli udf2html file.udf` - Print UDF content as HTML.
- `npx udf-cli md2udf file.md output.udf` - Convert Markdown to UDF.
- `npx udf-cli html2udf input.html output.udf` - Convert HTML to UDF.
