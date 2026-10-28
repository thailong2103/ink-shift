---
name: docx-report-design
description: "Design, compile, and format publication-grade Word documents (.docx) for academic reports, engineering monographs, and university theses. Synthesizes Anthropic's OOXML safety gotchas, python-docx typography normalization, and scientific claim-evidence prose discipline. Use when creating, converting, or formatting Word reports from Markdown, fixing layout defects (broken tables, double numbering, orphan headings), or enforcing Vietnamese academic standards (Nghị định 30/2020/NĐ-CP)."
---

# Professional DOCX Report Design & Engineering Standards

## 1. Overview & Architectural Posture

This skill governs the automated generation and formatting of professional Word documents (`.docx`). It enforces a strict **two-step compilation pipeline**:
1. **Drafting:** Content is authored in clean, structured Markdown (`.md`) with explicit section numbers, data tables, and evidence-backed claims.
2. **Compilation:** A robust Python script (using `python-docx`) transforms the Markdown into an OpenXML-compliant `.docx` document, applying closed typography tokens and eliminating layout defects.

> **CRITICAL RULE:** Never allow an LLM to generate raw XML strings directly. Always use the Python compilation bridge to ensure 100% valid document packages.

---

## 2. Vietnamese Academic & Administrative Typography Tokens

Aligned with **Nghị định 30/2020/NĐ-CP** and standard university graduation thesis regulations (HUST, PTIT, VNU):

### A. Page Geometry (A4 Standards)
- **Paper Size:** Standard A4 (`210 mm × 297 mm`).
- **Page Margins (Lề trang in chuẩn đóng gáy):**
  - **Left (Trái):** `3.0 cm` (chừa khoảng đóng gáy sách/ghim bìa).
  - **Right (Phải):** `2.0 cm`.
  - **Top (Trên):** `2.0 cm`.
  - **Bottom (Dưới):** `2.0 cm`.

### B. Closed Type Scale (Thang tỷ lệ chữ chuẩn vàng)
- **Font Family:** `Times New Roman` (đồng nhất toàn văn bản). Cả ba thuộc tính `w:ascii`, `w:hAnsi`, và `w:cs` đều phải trỏ về `Times New Roman` để tránh lỗi vỡ font tiếng Việt có dấu.
- **Title (Bìa):** `20.0 - 24.0 pt`, Bold, Căn giữa.
- **Heading 1 (Chương / Phần):** `16.0 pt`, Bold, In hoa, Space Before `18 pt`, Space After `12 pt`, ngắt trang trước mỗi phần.
- **Heading 2 (Mục 1.1):** `14.0 pt`, Bold, Space Before `18 pt`, Space After `6 pt`.
- **Heading 3 (Tiểu mục 1.1.1):** `13.0 pt`, Bold, Space Before `12 pt`, Space After `4 pt`.
- **Body Text (Normal):** `13.0 pt`, Regular, giãn dòng `1.5 lines`, Space After `6.0 pt`, Space Before `0 pt`, Căn đều hai bên (`Justified`).
- **Chú thích Bảng / Hình:** `11.0 - 11.5 pt`, Regular hoặc Italic, Căn giữa.
- **Đoạn mã code / Dữ liệu:** `9.5 pt`, `Consolas`, màu `#222222`, thụt lề trái `0.2"`.

---

## 3. The Seven Defect-Prevention Gotchas (Cạm bẫy kỹ thuật)

Every compilation script **MUST** enforce these safeguards:

### 1. The Duplicate Numbering Purge (`numPr` Guard)
* **Symptom:** Word displays double numbers like `1 PHẦN 1:` or `1.1 1.1. Bối cảnh...`.
* **Root Cause:** Template styles inherit Word's automatic Multilevel List numbering (`<w:numPr>`).
* **Enforced Guard:** Iterate over all styles starting with `Heading` and purge `<w:numPr>` and `<w:ind>`:
  ```python
  for s in doc.styles:
      if s.name.startswith('Heading') or s.name in ['Subtitle', 'TOC Heading']:
          for numPr in s._element.xpath('.//w:numPr'):
              numPr.getparent().remove(numPr)
          for ind in s._element.xpath('.//w:ind'):
              ind.getparent().remove(ind)
  ```

### 2. Table Integrity (`tblHeader` & `cantSplit`)
* **Symptom:** Table headers disappear when spanning pages; rows get sliced in half horizontally across page breaks.
* **Enforced Guard:**
  ```python
  def prevent_row_split(row):
      row._tr.get_or_add_trPr().append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))

  def set_repeat_header(row):
      row._tr.get_or_add_trPr().append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
  ```

### 3. Cell Padding & Minimal-Ink Styling
* **Symptom:** Text touching border lines; heavy black borders resembling legacy 1990s tables.
* **Enforced Guard:**
  - Internal padding (`tcMar`): minimum `100 dxa` top/bottom, `140 dxa` left/right.
  - Header shading: soft gray `#EAECEF` or `#F1F5F9`.
  - Subtle zebra striping on odd rows: `#FAFAFA`.
  - Style name in `python-docx`: use `'TableGrid'` (without space), NOT `'Table Grid'`.

### 4. Heading Orphan Prevention (`keep_with_next`)
* **Symptom:** Heading sits lonely at the bottom of a page while its body paragraph jumps to the next page.
* **Enforced Guard:** Always set `hf.keep_with_next = True` on all Headings.

### 5. Table & Figure Placement Rules
* **Tables:** Caption **ALWAYS ABOVE** the table (`Bảng X.Y: Tên bảng`), centered or left-aligned.
* **Figures:** Image centered; Caption **ALWAYS BELOW** the image (`Hình X.Y: Tên hình`), centered, 11.5pt italic.

### 6. Media Bloat Purge
* **Symptom:** Word file is 15–30 MB because template contains old deleted slides/images in `word/media/`.
* **Enforced Guard:** Delete unreferenced image relationships from `doc.part.rels` before saving. `python-docx` will automatically omit unreferenced binaries, compressing output from ~17 MB down to ~3 MB.

### 7. File-Lock Recovery (Windows PermissionError)
* **Symptom:** Script crashes with `[Errno 13] Permission denied` because user has the `.docx` open in MS Word.
* **Enforced Guard:** Wrap `doc.save()` in a `try...except PermissionError` block and fall back to saving as `_V2.docx`.

---

## 4. Academic Prose & Evidence-Claim Calibration (Scientific Writing)

When generating report content:
1. **One message per paragraph:** The first sentence states the core thesis or action.
2. **Claim-Evidence Alignment:** Every technical claim must cite measured data:
   - *Bad:* "InkShift đạt tốc độ dịch siêu nhanh và tối ưu bộ nhớ."
   - *Good:* "InkShift đạt độ trễ đọc bộ đệm SQLite WAL dưới $6.9\text{ ms}$ và giải phóng $100\%$ băng thông truyền tải ảnh khi trúng cache."
3. **Self-contained Terminology:** Define all acronyms (WAL, OCR, MV3, TTFB, RDP) upon first introduction.
4. **Minimal-ink Comparison Tables:** Summarize trade-offs using objective matrices comparing Speed, Memory, Network, and Reliability.

---

## 5. Observability & Quality Checklist (Pre-Flight & Post-Flight)

Before delivering a `.docx` to the user, run these verification assertions:
- [ ] **Styles Check:** `numPr count == 0` for all Heading styles.
- [ ] **Structure Check:** Correct count of `Heading 1` (Chương/Phần), `Heading 2`, `Heading 3`.
- [ ] **Table Check:** All tables have `TableGrid`, centered, with repeated headers.
- [ ] **Image Check:** All figures centered, high-resolution, with italic captions below.
- [ ] **Size Check:** File size is optimized (typically $2 - 5\text{ MB}$, not $>15\text{ MB}$).
- [ ] **Lock Check:** No crash on locked files; graceful fallback message presented.
