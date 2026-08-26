import io
import zipfile
from xml.etree import ElementTree

import pytest

from grant_app.data_generator import generate_rows
from grant_app.data_generator_schema import HEADERS
from grant_app.xlsx_export import write_xlsx


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def inline_value(cell):
    text = cell.find("m:is/m:t", NS)
    return "" if text is None else text.text or ""


def test_xlsx_contains_exact_headers_rows_and_numeric_cells():
    output = io.BytesIO()
    write_xlsx(output, generate_rows(3), expected_rows=3)

    assert output.tell() == 0
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows = root.findall("m:sheetData/m:row", NS)
    assert len(rows) == 4
    assert [inline_value(cell) for cell in rows[0].findall("m:c", NS)] == list(HEADERS)
    cells = {cell.attrib["r"]: cell for cell in rows[1].findall("m:c", NS)}
    assert cells["G2"].get("t") is None
    assert cells["H2"].get("t") is None
    assert cells["I2"].get("t") is None
    assert cells["S2"].get("t") == "inlineStr"
    assert root.find("m:sheetViews/m:sheetView/m:pane", NS).get("state") == "frozen"
    assert root.find("m:autoFilter", NS).get("ref") == "A1:S4"
    assert len(root.findall("m:cols/m:col", NS)) == 19


def test_xlsx_rejects_short_and_long_iterators():
    with pytest.raises(ValueError, match="expected 2 rows"):
        write_xlsx(io.BytesIO(), generate_rows(1), expected_rows=2)
    with pytest.raises(ValueError, match="expected 1 rows"):
        write_xlsx(io.BytesIO(), generate_rows(2), expected_rows=1)
