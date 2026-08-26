import zipfile
from collections.abc import Iterable, Mapping
from typing import BinaryIO
from xml.sax.saxutils import escape

from .data_generator_schema import COLUMN_WIDTHS, HEADERS, NUMERIC_HEADERS


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

CONTENT_TYPES = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''
ROOT_RELS = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
WORKBOOK = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'''.encode()
WORKBOOK_RELS = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{MAIN_NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0B3578"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs></styleSheet>'''.encode()


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell(reference: str, value: object, *, header: bool = False) -> bytes:
    style = ' s="1"' if header else ""
    if _is_numeric(value):
        return f'<c r="{reference}"{style}><v>{value}</v></c>'.encode()
    text = str(value or "")
    preserve = ' xml:space="preserve"' if text != text.strip() else ""
    return (
        f'<c r="{reference}" t="inlineStr"{style}>'
        f'<is><t{preserve}>{escape(text)}</t></is></c>'
    ).encode()


def _write_xlsx(
    output: BinaryIO,
    rows: Iterable[Mapping[str, object]],
    expected_rows: int,
) -> None:
    if expected_rows < 0:
        raise ValueError("expected_rows must not be negative")

    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/styles.xml", STYLES)
        with archive.open("xl/worksheets/sheet1.xml", "w") as sheet:
            last_row = expected_rows + 1
            columns = "".join(
                f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
                for index, width in enumerate(COLUMN_WIDTHS, start=1)
            )
            sheet.write(
                (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    f'<worksheet xmlns="{MAIN_NS}"><dimension ref="A1:S{last_row}"/>'
                    '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" '
                    'topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                    f'</sheetView></sheetViews><cols>{columns}</cols><sheetData>'
                ).encode()
            )
            sheet.write(b'<row r="1">')
            for column, header in enumerate(HEADERS, start=1):
                sheet.write(_cell(f"{_column_name(column)}1", header, header=True))
            sheet.write(b"</row>")

            actual = 0
            for actual, record in enumerate(rows, start=1):
                if actual > expected_rows:
                    raise ValueError(f"expected {expected_rows} rows but received more")
                excel_row = actual + 1
                sheet.write(f'<row r="{excel_row}">'.encode())
                for column, header in enumerate(HEADERS, start=1):
                    value = record[header]
                    if header in NUMERIC_HEADERS and not _is_numeric(value):
                        raise TypeError(f"{header} must be numeric")
                    sheet.write(_cell(f"{_column_name(column)}{excel_row}", value))
                sheet.write(b"</row>")

            if actual != expected_rows:
                raise ValueError(f"expected {expected_rows} rows but received {actual}")
            sheet.write(f'</sheetData><autoFilter ref="A1:S{last_row}"/></worksheet>'.encode())



def write_xlsx(
    output: BinaryIO,
    rows: Iterable[Mapping[str, object]],
    expected_rows: int,
) -> None:
    try:
        _write_xlsx(output, rows, expected_rows)
        output.seek(0)
    except Exception:
        output.seek(0)
        output.truncate(0)
        output.seek(0)
        raise
