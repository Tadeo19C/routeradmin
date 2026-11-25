import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


def _clean_cell_value(val):
    if val is None:
        return ''
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return str(val).strip()
    if isinstance(val, int):
        return str(val)
    return str(val).strip()


def generate_excel_bytes(headers, rows, sheet_name="Equipos"):
    """
    Genera un archivo Microsoft Excel (.xlsx) nativo en memoria.
    Usa openpyxl con formato limpio de encabezados y ancho automático,
    con fallback en Python puro (zipfile OpenXML) si openpyxl no estuviera disponible.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center")
        cell_font = Font(name="Calibri", size=11)
        thin_border = Border(
            left=Side(style='thin', color='D9D9D9'),
            right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'),
            bottom=Side(style='thin', color='D9D9D9')
        )

        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        for row_idx, r in enumerate(rows, start=2):
            ws.append(r)
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=row_idx, column=col_idx)
                c.font = cell_font
                c.border = thin_border

        # Ajustar ancho de columnas automáticamente
        for col_idx, h in enumerate(headers, start=1):
            max_len = len(str(h))
            for r in rows:
                if col_idx - 1 < len(r) and r[col_idx - 1] is not None:
                    max_len = max(max_len, len(str(r[col_idx - 1])))
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = max(max_len + 5, 14)

        ws.row_dimensions[1].height = 24

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except ImportError:
        return _generate_xlsx_pure_python(headers, rows, sheet_name)


def _generate_xlsx_pure_python(headers, rows, sheet_name="Equipos"):
    """Fallback en Python puro para crear un .xlsx estándar sin dependencias externas."""
    all_rows = [headers] + list(rows)
    sheet_rows_xml = []
    for r_idx, row in enumerate(all_rows, start=1):
        cells_xml = []
        for c_idx, val in enumerate(row):
            col_letter = chr(65 + c_idx)
            cell_ref = f"{col_letter}{r_idx}"
            val_str = escape(_clean_cell_value(val))
            cells_xml.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{val_str}</t></is></c>')
        sheet_rows_xml.append(f'<row r="{r_idx}">{"".join(cells_xml)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows_xml)}</sheetData>'
        '</worksheet>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    wb_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types_xml)
        zf.writestr('_rels/.rels', rels_xml)
        zf.writestr('xl/workbook.xml', wb_xml)
        zf.writestr('xl/_rels/workbook.xml.rels', wb_rels_xml)
        zf.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    return buf.getvalue()


def parse_excel_or_csv_bytes(raw_bytes, filename=""):
    """
    Lee un archivo subido (.xlsx o .csv) y devuelve:
    (headers: list[str], rows: list[dict[str, str]])
    """
    is_xlsx = (
        raw_bytes[:4] == b'PK\x03\x04'
        or (filename and filename.lower().endswith('.xlsx'))
    )
    if is_xlsx:
        return _parse_xlsx_bytes(raw_bytes)
    return _parse_csv_bytes(raw_bytes)


def _parse_xlsx_bytes(raw_bytes):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
        ws = wb.active
        all_rows = []
        for row in ws.iter_rows(values_only=True):
            cleaned = [_clean_cell_value(c) for c in row]
            if any(cleaned):
                all_rows.append(cleaned)
        if not all_rows:
            return [], []
        headers = [h.strip() for h in all_rows[0]]
        dict_rows = []
        for r in all_rows[1:]:
            row_dict = {}
            for idx, h in enumerate(headers):
                if h:
                    row_dict[h] = r[idx] if idx < len(r) else ''
            if any(row_dict.values()):
                dict_rows.append(row_dict)
        return headers, dict_rows
    except ImportError:
        return _parse_xlsx_pure_python(raw_bytes)


def _col_letters_to_index(col_letters):
    idx = 0
    for ch in col_letters:
        idx = idx * 26 + (ord(ch.upper()) - ord('A') + 1)
    return idx - 1


def _parse_xlsx_pure_python(raw_bytes):
    """Lector de .xlsx en Python puro usando zipfile + ElementTree."""
    with zipfile.ZipFile(io.BytesIO(raw_bytes), 'r') as zf:
        shared_strings = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            ss_root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in ss_root.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                texts = [t.text or '' for t in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')]
                shared_strings.append(''.join(texts))

        sheet_files = sorted([n for n in zf.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')])
        if not sheet_files:
            return [], []

        ws_root = ET.fromstring(zf.read(sheet_files[0]))
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        all_rows = []
        for row_el in ws_root.findall(f'.//{ns}row'):
            row_cells = {}
            max_col = -1
            for c_el in row_el.findall(f'{ns}c'):
                ref = c_el.attrib.get('r', '')
                m = re.match(r'^([A-Za-z]+)', ref)
                col_idx = _col_letters_to_index(m.group(1)) if m else (max_col + 1)
                max_col = max(max_col, col_idx)
                c_type = c_el.attrib.get('t', '')
                v_el = c_el.find(f'{ns}v')
                is_el = c_el.find(f'{ns}is')
                val = ''
                if c_type == 's' and v_el is not None and v_el.text is not None:
                    s_idx = int(v_el.text)
                    val = shared_strings[s_idx] if 0 <= s_idx < len(shared_strings) else ''
                elif c_type == 'inlineStr' and is_el is not None:
                    texts = [t.text or '' for t in is_el.findall(f'.//{ns}t')]
                    val = ''.join(texts)
                elif v_el is not None and v_el.text is not None:
                    val = v_el.text
                row_cells[col_idx] = _clean_cell_value(val)
            if max_col >= 0:
                cleaned = [row_cells.get(i, '') for i in range(max_col + 1)]
                if any(cleaned):
                    all_rows.append(cleaned)

        if not all_rows:
            return [], []
        headers = [h.strip() for h in all_rows[0]]
        dict_rows = []
        for r in all_rows[1:]:
            row_dict = {}
            for idx, h in enumerate(headers):
                if h:
                    row_dict[h] = r[idx] if idx < len(r) else ''
            if any(row_dict.values()):
                dict_rows.append(row_dict)
        return headers, dict_rows


def _parse_csv_bytes(raw_bytes):
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            text = raw_bytes.decode(enc).strip()
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return [], []

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return [], []

    first_line = lines[0]
    if first_line.count(';') > first_line.count(','):
        delimiter = ';'
    elif first_line.count('\t') > first_line.count(','):
        delimiter = '\t'
    else:
        delimiter = ','

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [h.strip() for h in (reader.fieldnames or []) if h]
    dict_rows = []
    for raw_row in reader:
        row_dict = {}
        for k, v in raw_row.items():
            if k:
                row_dict[k.strip()] = (v.strip() if v else '')
        if any(row_dict.values()):
            dict_rows.append(row_dict)
    return headers, dict_rows
