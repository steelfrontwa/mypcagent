# -*- coding: utf-8 -*-
"""Чтение и создание документов Word, Excel, PowerPoint и PDF."""
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape as xesc

from . import fileops, state, util


# ---------- документы: Word, Excel, PowerPoint, PDF ----------
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


X_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


DOC_EXT = (".docx", ".xlsx", ".pptx", ".pdf")


def _xml_text(root, tag):
    return "".join(t.text or "" for t in root.iter(tag))


def read_docx(f):
    W = "{%s}" % W_NS
    with zipfile.ZipFile(f) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    out = []
    body = root.find(W + "body")
    for el in body:
        if el.tag == W + "p":
            st = el.find(f"{W}pPr/{W}pStyle")
            style = (st.get(W + "val") if st is not None else "") or ""
            text = _xml_text(el, W + "t")
            m = re.search(r"(?:heading|заголовок)\s*(\d)", style, re.I)
            out.append(("#" * int(m.group(1)) + " " + text) if m and text else text)
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                out.append(" | ".join(_xml_text(tc, W + "t") for tc in tr.findall(W + "tc")))
    return "\n".join(out)


def read_xlsx(f, max_rows=300):
    X = "{%s}" % X_NS
    out = []
    with zipfile.ZipFile(f) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(X + "si"):
                shared.append(_xml_text(si, X + "t"))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {r.get("Id"): r.get("Target") for r in rels}
        for sh in wb.find(X + "sheets"):
            target = relmap.get(sh.get("{%s}id" % R_NS), "")
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            out.append(f"## Лист: {sh.get('name')}")
            root = ET.fromstring(z.read(path))
            for ri, row in enumerate(root.iter(X + "row")):
                if ri >= max_rows:
                    out.append("...[строки обрезаны]")
                    break
                cells = []
                for c in row.findall(X + "c"):
                    t, v, fm = c.get("t"), c.find(X + "v"), c.find(X + "f")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = _xml_text(c, X + "t")
                    else:
                        val = v.text if v is not None and v.text else ""
                    if fm is not None and fm.text:
                        val = f"{val} (=" + fm.text + ")"
                    if val != "":
                        cells.append(f"{c.get('r')}={val}")
                if cells:
                    out.append(" | ".join(cells))
    return "\n".join(out)


def read_pptx(f):
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    out = []
    with zipfile.ZipFile(f) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
        for i, n in enumerate(slides, 1):
            root = ET.fromstring(z.read(n))
            paras = ["".join(t.text or "" for t in p.iter(A + "t")) for p in root.iter(A + "p")]
            out.append(f"## Слайд {i}\n" + "\n".join(x for x in paras if x))
    return "\n".join(out)


def read_pdf(f):
    reader = None
    try:
        import pypdf
        reader = pypdf.PdfReader(str(f))
    except ImportError:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(f))
        except ImportError:
            return "Для чтения PDF нужна библиотека: выполни через run_command `pip install pypdf` и повтори."
    text = "\n\n".join((pg.extract_text() or "") for pg in reader.pages)
    return text or "В PDF нет текстового слоя (возможно, это скан)."


def t_read_document(path):
    f = util.safe(path)
    if not f.is_file():
        return "Файл не найден: " + path
    try:
        ext = f.suffix.lower()
        text = {".docx": read_docx, ".xlsx": read_xlsx, ".pptx": read_pptx, ".pdf": read_pdf}[ext](f)
    except KeyError:
        return "Поддерживаются: " + ", ".join(DOC_EXT)
    except Exception as e:
        return f"Не удалось прочитать файл: {e}"
    if len(text) > 30000:
        text = text[:30000] + "\n...[обрезано]"
    return text or "(пусто)"


def _runs(text):
    out = ""
    for part in re.split(r"(\*\*[^*]+\*\*)", text):
        if not part:
            continue
        bold = len(part) > 4 and part.startswith("**") and part.endswith("**")
        if bold:
            part = part[2:-2]
        out += ("<w:r>" + ("<w:rPr><w:b/></w:rPr>" if bold else "") +
                '<w:t xml:space="preserve">' + xesc(part) + "</w:t></w:r>")
    return out


def _para(text, style=None, indent=False):
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + ('<w:ind w:left="567" w:hanging="283"/>' if indent else "")
    return "<w:p>" + (f"<w:pPr>{ppr}</w:pPr>" if ppr else "") + _runs(text) + "</w:p>"


def _table(rows):
    cols = max(len(r) for r in rows)
    x = ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>' +
         "".join(f'<w:{b} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
                 for b in ("top", "left", "bottom", "right", "insideH", "insideV")) +
         "</w:tblBorders></w:tblPr><w:tblGrid>" + '<w:gridCol w:w="2400"/>' * cols + "</w:tblGrid>")
    for i, r in enumerate(rows):
        x += "<w:tr>"
        for c in range(cols):
            txt = r[c].strip() if c < len(r) else ""
            if i == 0 and txt and not txt.startswith("**"):
                txt = "**" + txt + "**"
            x += f'<w:tc><w:tcPr><w:tcW w:w="2400" w:type="dxa"/></w:tcPr>{_para(txt)}</w:tc>'
        x += "</w:tr>"
    return x + "</w:tbl>"


def build_docx(content):
    body, rows = [], []

    def flush():
        if rows:
            body.append(_table(list(rows)))
            body.append("<w:p/>")
            rows.clear()

    for line in content.replace("\r", "").split("\n"):
        st = line.strip()
        if st.startswith("|") and st.endswith("|") and len(st) > 1:
            cells = [c for c in st.strip("|").split("|")]
            if not all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in cells):
                rows.append(cells)
            continue
        flush()
        m = re.match(r"^(#{1,3})\s+(.*)$", st)
        if m:
            body.append(_para(m.group(2), f"Heading{len(m.group(1))}"))
        elif re.match(r"^[-*•]\s+", st):
            body.append(_para("•\t" + re.sub(r"^[-*•]\s+", "", st), indent=True))
        elif re.match(r"^\d+[.)]\s+", st):
            body.append(_para(st, indent=True))
        elif st:
            body.append(_para(st))
    flush()
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W_NS}"><w:body>' +
           "".join(body) + '<w:p/><w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>'
           "</w:sectPr></w:body></w:document>")

    def hstyle(n, size, before):
        return (f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/>'
                f'<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="{before}" w:after="120"/>'
                f'<w:outlineLvl w:val="{n - 1}"/></w:pPr><w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>')

    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="{W_NS}"><w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="ru-RU"/>'
              '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
              '</w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>' +
              hstyle(1, 36, 360) + hstyle(2, 30, 280) + hstyle(3, 26, 220) + "</w:styles>")
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{R_NS}/officeDocument" Target="word/document.xml"/></Relationships>')
    drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             f'<Relationship Id="rId1" Type="{R_NS}/styles" Target="styles.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", drels)
    return buf.getvalue()


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def build_xlsx(sheets):
    names, sheet_xml = [], []
    for raw_name, rows in sheets.items():
        name = re.sub(r"[\[\]:*?/\\]", "_", str(raw_name))[:31] or "Лист"
        while name in names:
            name = (name[:28] + "_" + str(len(names)))[:31]
        names.append(name)
        widths, data = {}, []
        for ri, row in enumerate(rows, 1):
            cells = ""
            for ci, v in enumerate(row):
                if v is None or v == "":
                    continue
                ref = f"{_col(ci)}{ri}"
                style = ' s="1"' if ri == 1 else ""
                if isinstance(v, bool):
                    cells += f'<c r="{ref}" t="b"{style}><v>{int(v)}</v></c>'
                    shown = str(v)
                elif isinstance(v, (int, float)):
                    cells += f'<c r="{ref}"{style}><v>{v}</v></c>'
                    shown = str(v)
                elif isinstance(v, str) and v.startswith("=") and len(v) > 1:
                    cells += f'<c r="{ref}"{style}><f>{xesc(v[1:])}</f></c>'
                    shown = "0000000000"
                else:
                    sv = str(v)
                    cells += f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{xesc(sv)}</t></is></c>'
                    shown = sv
                widths[ci] = max(widths.get(ci, 8), min(len(shown) + 2, 60))
            data.append(f'<row r="{ri}">{cells}</row>')
        cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>' for c, w in sorted(widths.items()))
        sheet_xml.append(
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{X_NS}"><sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            + (f"<cols>{cols}</cols>" if cols else "") + "<sheetData>" + "".join(data) + "</sheetData></worksheet>")
    wb = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{X_NS}" xmlns:r="{R_NS}"><sheets>' +
          "".join(f'<sheet name="{xesc(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) +
          '</sheets><calcPr fullCalcOnLoad="1"/></workbook>')
    n = len(names)
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
              "".join(f'<Relationship Id="rId{i}" Type="{R_NS}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1)) +
              f'<Relationship Id="rId{n + 1}" Type="{R_NS}/styles" Target="styles.xml"/></Relationships>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="{X_NS}">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFDDE6F5"/><bgColor indexed="64"/></patternFill></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
          "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                  for i in range(1, n + 1)) +
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{R_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/styles.xml", styles)
        for i, x in enumerate(sheet_xml, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", x)
    return buf.getvalue()


def _write_doc(path, data, suffix, title):
    f = util.safe(path)
    if f.suffix.lower() != suffix:
        f = f.with_suffix(suffix)
    rel = f.relative_to(state.WS).as_posix()
    if not fileops.confirm(f"Создать файл {rel}", title):
        return "Пользователь отклонил."
    bak = fileops.backup(f)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    fileops.set_undo({"kind": "file", "path": str(f), "bak": str(bak) if bak else None})
    return "Создан: " + rel


def t_create_docx(path, content):
    data = build_docx(content)
    return _write_doc(path, data, ".docx", content[:600])


def t_create_xlsx(path, sheets):
    if isinstance(sheets, str):
        try:
            sheets = json.loads(sheets)
        except json.JSONDecodeError:
            return "Ошибка: sheets должен быть объектом {имя_листа: [[строка], ...]}."
    if isinstance(sheets, list):
        sheets = {"Лист1": sheets}
    if not isinstance(sheets, dict) or not sheets:
        return "Ошибка: sheets должен быть объектом {имя_листа: [[строка], ...]}."
    sheets = {k: [r if isinstance(r, list) else [r] for r in v] for k, v in sheets.items() if isinstance(v, list)}
    data = build_xlsx(sheets)
    preview = "\n".join(f"{k}: {len(v)} строк" for k, v in sheets.items())
    return _write_doc(path, data, ".xlsx", preview)
