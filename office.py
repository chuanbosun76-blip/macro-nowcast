"""零依赖 OOXML 导出：Word(.docx) / Excel(.xlsx) / PowerPoint(.pptx)。
只用标准库 zipfile + 手写 XML，避免在 Render 上引入 lxml/Pillow 等二进制依赖。

用法：
    office.docx([{"h1": "标题"}, {"p": "正文"}, {"table": {"head": [...], "rows": [[...]]}}], title="...")
    office.xlsx({"表名": {"head": [...], "rows": [[...]], "widths": [...]}})
    office.pptx([{"title": "...", "bullets": [...], "notes": "..."}])
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime

CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ODR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def esc(t) -> str:
    if t is None:
        return ""
    t = str(t)
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("\x0b", " ").replace("\x0c", " "))


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
    return buf.getvalue()


# ------------------------------------------------------------------ Word
def _p(text="", style=None, bold=False, size=None, color=None, align=None, space_after=120):
    ppr = "<w:pPr>"
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    ppr += f'<w:spacing w:after="{space_after}" w:line="300" w:lineRule="auto"/></w:pPr>'
    rpr = "<w:rPr>"
    if bold:
        rpr += "<w:b/>"
    if size:
        rpr += f'<w:sz w:val="{size * 2}"/><w:szCs w:val="{size * 2}"/>'
    if color:
        rpr += f'<w:color w:val="{color}"/>'
    rpr += '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/></w:rPr>'
    runs = ""
    for i, line in enumerate(str(text).split("\n")):
        runs += ("<w:r>" + rpr + ("<w:br/>" if i else "") + f'<w:t xml:space="preserve">{esc(line)}</w:t></w:r>')
    return f"<w:p>{ppr}{runs}</w:p>"


def _cell(text, w, bold=False, fill=None, size=9):
    shd = f'<w:shd w:val="clear" w:fill="{fill}"/>' if fill else ""
    return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shd}<w:vAlign w:val="center"/></w:tcPr>'
            + _p(text, bold=bold, size=size, space_after=0) + "</w:tc>")


def _table(head, rows, widths=None, total=9360):
    n = max(len(head or []), max((len(r) for r in rows), default=1))
    widths = widths or [total // n] * n
    xml = ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/>'
           '<w:tblBorders>' + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="D7DCE5"/>' for s in
                                      ("top", "left", "bottom", "right", "insideH", "insideV")) + "</w:tblBorders></w:tblPr>")
    xml += "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
    if head:
        xml += "<w:tr><w:trPr><w:tblHeader/></w:trPr>" + "".join(_cell(h, w, True, "EEF2F8") for h, w in zip(head, widths)) + "</w:tr>"
    for r in rows:
        xml += "<w:tr>" + "".join(_cell(c, w) for c, w in zip(list(r) + [""] * (n - len(r)), widths)) + "</w:tr>"
    return xml + "</w:tbl>" + _p("", space_after=60)


def docx(blocks, title="报告", subject="宏观预测", creator="观数 · 宏观预测平台") -> bytes:
    body = ""
    for b in blocks:
        if "h1" in b:
            body += _p(b["h1"], bold=True, size=20, color="16324F", space_after=200)
        elif "h2" in b:
            body += _p(b["h2"], bold=True, size=15, color="1F4E79", space_after=160)
        elif "h3" in b:
            body += _p(b["h3"], bold=True, size=12, color="2E5E8C", space_after=120)
        elif "p" in b:
            body += _p(b["p"], size=10.5)
        elif "small" in b:
            body += _p(b["small"], size=9, color="666666")
        elif "bullets" in b:
            for it in b["bullets"]:
                body += _p("• " + str(it), size=10.5, space_after=60)
        elif "table" in b:
            t = b["table"]
            body += _table(t.get("head"), t.get("rows") or [], t.get("widths"))
        elif "pagebreak" in b:
            body += '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}'
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
           "</w:body></w:document>")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return _zip({
        "[Content_Types].xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{CT}">'
                               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                               '<Default Extension="xml" ContentType="application/xml"/>'
                               '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                               '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                               '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>',
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
                       f'<Relationship Id="rId1" Type="{ODR}/officeDocument" Target="word/document.xml"/>'
                       '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>',
        "word/_rels/document.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
                                        f'<Relationship Id="rId1" Type="{ODR}/styles" Target="styles.xml"/></Relationships>',
        "word/styles.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                           '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:rPrDefault></w:docDefaults>'
                           '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style></w:styles>',
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                             '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                             'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                             f"<dc:title>{esc(title)}</dc:title><dc:subject>{esc(subject)}</dc:subject><dc:creator>{esc(creator)}</dc:creator>"
                             f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>',
        "word/document.xml": doc,
    })


# ------------------------------------------------------------------ Excel
def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def xlsx(sheets: dict) -> bytes:
    """sheets: {名称: {"head": [...], "rows": [[...]], "widths": [int], "freeze": "A2", "note": str}}"""
    names = list(sheets)[:20]
    parts, rels, ovr, wsheets = {}, "", "", ""
    for idx, nm in enumerate(names, start=1):
        sh = sheets[nm]
        head, rows = sh.get("head") or [], sh.get("rows") or []
        widths = sh.get("widths") or ([18] + [12] * (max(len(head), 1) - 1))
        cols = "<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)) + "</cols>"
        data = ""
        r = 1
        if head:
            data += f'<row r="1" ht="20" customHeight="1">' + "".join(
                f'<c r="{_col(i)}1" s="1" t="inlineStr"><is><t xml:space="preserve">{esc(h)}</t></is></c>' for i, h in enumerate(head)) + "</row>"
            r = 2
        for row in rows:
            cells = ""
            for i, v in enumerate(row):
                ref = f"{_col(i)}{r}"
                if v is None or v == "":
                    continue
                if _is_num(v):
                    cells += f'<c r="{ref}" s="2"><v>{v}</v></c>'
                else:
                    cells += f'<c r="{ref}" s="0" t="inlineStr"><is><t xml:space="preserve">{esc(v)}</t></is></c>'
            data += f'<row r="{r}">{cells}</row>'
            r += 1
        freeze = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                  if head else "")
        parts[f"xl/worksheets/sheet{idx}.xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                                                  '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                                  + freeze + cols + f"<sheetData>{data}</sheetData></worksheet>")
        rels += f'<Relationship Id="rId{idx}" Type="{ODR}/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        ovr += f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        safe = esc(nm)[:31].replace("/", "-").replace("\\", "-").replace("?", "").replace("*", "").replace("[", "(").replace("]", ")")
        wsheets += f'<sheet name="{safe}" sheetId="{idx}" r:id="rId{idx}"/>'
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
              '<fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font>'
              '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/></patternFill></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>')
    parts.update({
        "[Content_Types].xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{CT}">'
                               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                               '<Default Extension="xml" ContentType="application/xml"/>'
                               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                               + ovr + "</Types>",
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
                       f'<Relationship Id="rId1" Type="{ODR}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                           f'xmlns:r="{ODR}"><sheets>{wsheets}</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">{rels}'
                                      f'<Relationship Id="rId900" Type="{ODR}/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": styles,
    })
    return _zip(parts)


# ------------------------------------------------------------------ PowerPoint
W, H = 12192000, 6858000  # 16:9


def _tx(sid, name, x, y, w, h, paras, ):
    body = ""
    for p in paras:
        txt, sz, bold, color, lvl, bullet = p
        pr = f'<a:pPr lvl="{lvl}"' + (' marL="228600" indent="-228600"' if bullet else ' marL="0" indent="0"') + ">"
        pr += "<a:buChar char=\"•\"/>" if bullet else "<a:buNone/>"
        pr += "</a:pPr>"
        runs = ""
        bx = ' b="1"' if bold else ""
        for i, line in enumerate(str(txt).split("\n")):
            runs += ("<a:br/>" if i else "") + (f'<a:r><a:rPr lang="zh-CN" sz="{int(sz * 100)}"{bx} dirty="0">'
                                                f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
                                                f'<a:latin typeface="Calibri"/><a:ea typeface="Microsoft YaHei"/></a:rPr>'
                                                f'<a:t>{esc(line)}</a:t></a:r>')
        body += f"<a:p>{pr}{runs}</a:p>"
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" rtlCol="0"><a:normAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>')


def _rect(sid, x, y, w, h, color):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="r{sid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            '<a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>')


def _slide_xml(s):
    shapes = _rect(2, 0, 0, W, 168000, "1F4E79")
    sid = 10
    if s.get("cover"):
        shapes += _tx(sid, "t", 914400, 2100000, W - 1828800, 900000, [(s.get("title", ""), 40, True, "16324F", 0, False)])
        shapes += _tx(sid + 1, "s", 914400, 3100000, W - 1828800, 700000,
                      [(l, 16, False, "5A6B7D", 0, False) for l in (s.get("bullets") or [])])
    else:
        shapes += _tx(sid, "t", 685800, 420000, W - 1371600, 700000, [(s.get("title", ""), 26, True, "16324F", 0, False)])
        if s.get("subtitle"):
            shapes += _tx(sid + 5, "st", 685800, 1050000, W - 1371600, 450000, [(s["subtitle"], 13, False, "2E5E8C", 0, False)])
        y = 1560000 if s.get("subtitle") else 1300000
        paras = []
        for b in (s.get("bullets") or []):
            if isinstance(b, (list, tuple)):
                paras.append((b[0], 14, False, "24303C", b[1], True))
            else:
                paras.append((b, 15, False, "24303C", 0, True))
        if paras:
            shapes += _tx(sid + 1, "b", 685800, y, W - 1371600, H - y - 600000, paras)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + shapes + '</p:spTree></p:cSld><p:clrMapOvr><a:overrideClrMapping bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/></p:clrMapOvr></p:sld>')


_THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office"><a:themeElements>'
          '<a:clrScheme name="Office"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
          '<a:dk2><a:srgbClr val="16324F"/></a:dk2><a:lt2><a:srgbClr val="EEF2F8"/></a:lt2><a:accent1><a:srgbClr val="1F4E79"/></a:accent1>'
          '<a:accent2><a:srgbClr val="2E5E8C"/></a:accent2><a:accent3><a:srgbClr val="C00000"/></a:accent3><a:accent4><a:srgbClr val="7F7F7F"/></a:accent4>'
          '<a:accent5><a:srgbClr val="4472C4"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
          '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
          '<a:fontScheme name="Office"><a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface=""/></a:majorFont>'
          '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
          '<a:fmtScheme name="Office"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
          '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
          '<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
          '<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
          '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>'
          '<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
          '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')

_LAYOUT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1"><p:cSld name="空白"><p:spTree>'
           '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
           '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
           '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')

_MASTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:bg><p:bgPr>'
           '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>'
           '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
           '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
           '</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
           'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
           '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>')


def pptx(slides) -> bytes:
    n = len(slides)
    parts = {}
    sldIds, prels, ovr = "", "", ""
    for i, s in enumerate(slides, start=1):
        parts[f"ppt/slides/slide{i}.xml"] = _slide_xml(s)
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
                                                        f'<Relationship Id="rId1" Type="{ODR}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>')
        sldIds += f'<p:sldId id="{255 + i}" r:id="rId{i}"/>'
        prels += f'<Relationship Id="rId{i}" Type="{ODR}/slide" Target="slides/slide{i}.xml"/>'
        ovr += f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
    parts.update({
        "[Content_Types].xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{CT}">'
                               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                               '<Default Extension="xml" ContentType="application/xml"/>'
                               '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                               '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
                               '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
                               '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
                               + ovr + "</Types>",
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
                       f'<Relationship Id="rId1" Type="{ODR}/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
        "ppt/presentation.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                                '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                                f'xmlns:r="{ODR}" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                                f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{n + 1}"/></p:sldMasterIdLst>'
                                f"<p:sldIdLst>{sldIds}</p:sldIdLst>"
                                f'<p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="{H}" cy="{W}"/></p:presentation>',
        "ppt/_rels/presentation.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">{prels}'
                                           f'<Relationship Id="rId{n + 1}" Type="{ODR}/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
                                           f'<Relationship Id="rId{n + 2}" Type="{ODR}/theme" Target="theme/theme1.xml"/></Relationships>',
        "ppt/slideMasters/slideMaster1.xml": _MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
                                                        f'<Relationship Id="rId1" Type="{ODR}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                                                        f'<Relationship Id="rId2" Type="{ODR}/theme" Target="../theme/theme1.xml"/></Relationships>',
        "ppt/slideLayouts/slideLayout1.xml": _LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
                                                        f'<Relationship Id="rId1" Type="{ODR}/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>',
        "ppt/theme/theme1.xml": _THEME,
    })
    return _zip(parts)
