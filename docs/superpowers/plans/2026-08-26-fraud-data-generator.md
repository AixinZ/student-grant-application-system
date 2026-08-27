# Fraud Data Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local Flask page that generates 10,000–250,000 coherent synthetic student-grant rows in a schema-exact XLSX, with approximately 10% of rows labelled `Yes` solely by eight supported screening rules.

**Architecture:** Keep the rule engine pure and independent from generation, generate ordinary and risk scenarios through an injectable `random.Random`, and stream a minimal standards-compliant XLSX package with Python's standard library. The Flask route validates one integer, writes to an anonymous temporary file, serves it as a download, and closes it with the response without touching SQLite.

**Tech Stack:** Python 3.13, Flask 3.1, Flask-WTF/WTForms, Python standard-library `random`, `tempfile`, `zipfile`, and `xml.sax.saxutils`, pytest, HTML/CSS/vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-26-fraud-data-generator-design.md`

## Global Constraints

- Preserve the existing application-entry and application-history behaviour.
- The row-count range is exactly 10,000 through 250,000, inclusive.
- Output exactly the sample's 19 headers in the same order; preserve the trailing space in `FRAUD_Label `.
- Output labels are exactly `Yes` and `No`, calculated by the eight supported predicates.
- A blank `CRA_PROVINCE` does not trigger the non-Saskatchewan CRA rule.
- A total need of exactly 50,000 and age exactly 65 do not trigger threshold rules.
- Use approximately 10% independently sampled risk scenarios; never override a computed label to meet a quota.
- Do not add absent source fields, write generated rows to SQLite, copy complete sample rows, or accept user-supplied paths or filenames.
- Stream XLSX rows and automatically close temporary output files.
- Preserve the site's current responsive, accessible, privacy-safe conventions.
- Follow test-driven development: each production behaviour starts with a failing test that is observed before implementation.

## File Structure

- Create `grant_app/data_generator_schema.py`: exact workbook headers, location tuples, category pools, scenario weights, and numeric limits.
- Create `grant_app/fraud_rules.py`: eight pure rule predicates, match reporting, and final label calculation.
- Create `grant_app/data_generator.py`: coherent ordinary records, risk mutations, row iteration, and generator invariants.
- Create `grant_app/xlsx_export.py`: constant-memory OOXML/XLSX packaging and cell serialization.
- Modify `grant_app/forms.py`: add the row-count form.
- Modify `grant_app/routes.py`: add generator GET/POST and safe download lifecycle.
- Create `grant_app/templates/data_generator/new.html`: accessible generator form.
- Create `grant_app/static/js/data-generator-form.js`: error focus and duplicate-submit prevention.
- Modify `grant_app/templates/base.html`: add the navigation entry.
- Create `tests/test_fraud_rules.py`, `tests/test_data_generator.py`, `tests/test_xlsx_export.py`, and `tests/test_data_generator_routes.py`.
- Modify `tests/test_forms.py` and `tests/test_security_accessibility.py` for form and page integration coverage.
- Modify `README.md` and `docs/manual-test-checklist.md` with operator instructions.

---

### Task 1: Exact schema and pure screening rules

**Files:**
- Create: `grant_app/data_generator_schema.py`
- Create: `grant_app/fraud_rules.py`
- Create: `tests/test_fraud_rules.py`

**Interfaces:**
- Produces: `HEADERS: tuple[str, ...]`, `NUMERIC_HEADERS: frozenset[str]`, `COLUMN_WIDTHS: tuple[int, ...]`, and `RULE_IDS: tuple[str, ...]`.
- Produces: `evaluate_rules(record: Mapping[str, object]) -> tuple[str, ...]` and `fraud_label(record: Mapping[str, object]) -> str`.
- Depends on: no Flask, database, workbook, or generator state.

- [ ] **Step 1: Write failing tests for all predicates, boundaries, and aggregation**

Create a normal baseline record and mutate exactly one condition per case:

```python
# tests/test_fraud_rules.py
from copy import deepcopy

import pytest

from grant_app.data_generator_schema import HEADERS
from grant_app.fraud_rules import RULE_IDS, evaluate_rules, fraud_label


def normal_record():
    return {
        "CLIENT_DEPENDENT_STATUS": "Without Dependents",
        "DISABILITY_STATUS_IND": "N",
        "INSTITUTION_CITY": "REGINA",
        "INSTITUTION_PROVINCE": "SK",
        "INSTITUTION_COUNTRY": "CANADA",
        "OUT_OF_PROV_IND": "N",
        "NBR_OF_DEPENDENTS": 0,
        "TOTAL_NEED": 50000,
        "STUDENT_AGE": 65,
        "STUDENT_CITY": "SASKATOON",
        "STUDENT_PROVINCE": "SK",
        "STUDENT_COUNTRY": "CANADA",
        "CLIENT_CATEGORY": "Single Independent",
        "MARITAL_STATUS": "Single",
        "GRANTS_ONLY_IND": "Y",
        "CRA_MARITAL_STATUS": "Single",
        "CRA_CITY": "SASKATOON",
        "CRA_PROVINCE": "SK",
    }


@pytest.mark.parametrize(
    ("rule_id", "changes"),
    [
        ("R02_MARITAL_MISMATCH", {"CRA_MARITAL_STATUS": "Married"}),
        ("R08_STUDENT_OUTSIDE_SK", {"STUDENT_PROVINCE": "AB"}),
        ("R10_HIGH_NEED_GRANTS_ONLY", {"TOTAL_NEED": 50000.01}),
        ("R11_AGE_OVER_65", {"STUDENT_AGE": 66}),
        ("R13_CRA_OUTSIDE_SK", {"CRA_PROVINCE": "BC"}),
        (
            "R16_CRA_SK_STUDY_AND_LIVE_OUTSIDE",
            {
                "INSTITUTION_PROVINCE": "AB",
                "STUDENT_PROVINCE": "AB",
                "CRA_PROVINCE": "SK",
            },
        ),
        (
            "R19_OUTSIDE_SK_AT_FOREIGN_INSTITUTION",
            {"STUDENT_PROVINCE": "AB", "INSTITUTION_COUNTRY": "UNITED STATES"},
        ),
        (
            "R20_FOREIGN_STUDENT_OUTSIDE_SK",
            {"STUDENT_COUNTRY": "UNITED STATES", "STUDENT_PROVINCE": "ND"},
        ),
    ],
)
def test_each_supported_rule_can_trigger(rule_id, changes):
    record = normal_record()
    record.update(changes)

    assert rule_id in evaluate_rules(record)
    assert fraud_label(record) == "Yes"


def test_normal_record_and_strict_boundaries_are_not_flagged():
    assert evaluate_rules(normal_record()) == ()
    assert fraud_label(normal_record()) == "No"


def test_blank_cra_province_is_not_treated_as_outside_sk():
    record = normal_record()
    record["CRA_PROVINCE"] = ""
    assert "R13_CRA_OUTSIDE_SK" not in evaluate_rules(record)


def test_multiple_matches_still_produce_one_yes_label():
    record = normal_record()
    record.update({"STUDENT_PROVINCE": "AB", "STUDENT_AGE": 70})
    assert len(evaluate_rules(record)) == 2
    assert fraud_label(record) == "Yes"


def test_schema_is_exact_and_label_is_last():
    assert len(HEADERS) == 19
    assert HEADERS[-1] == "FRAUD_Label "
    assert len(RULE_IDS) == 8
```

- [ ] **Step 2: Run the rule tests and observe the expected import failure**

Run: `.venv/bin/python -m pytest tests/test_fraud_rules.py -q`

Expected: collection fails because `grant_app.data_generator_schema` and `grant_app.fraud_rules` do not exist.

- [ ] **Step 3: Implement exact schema constants and the eight pure predicates**

Create `data_generator_schema.py` with the exact tuple and reusable immutable pools:

```python
from dataclasses import dataclass

HEADERS = (
    "CLIENT_DEPENDENT_STATUS", "DISABILITY_STATUS_IND", "INSTITUTION_CITY",
    "INSTITUTION_PROVINCE", "INSTITUTION_COUNTRY", "OUT_OF_PROV_IND",
    "NBR_OF_DEPENDENTS", "TOTAL_NEED", "STUDENT_AGE", "STUDENT_CITY",
    "STUDENT_PROVINCE", "STUDENT_COUNTRY", "CLIENT_CATEGORY",
    "MARITAL_STATUS", "GRANTS_ONLY_IND", "CRA_MARITAL_STATUS", "CRA_CITY",
    "CRA_PROVINCE", "FRAUD_Label ",
)
NUMERIC_HEADERS = frozenset({"NBR_OF_DEPENDENTS", "TOTAL_NEED", "STUDENT_AGE"})
COLUMN_WIDTHS = (27, 24, 24, 25, 24, 17, 20, 14, 14, 22, 20, 20, 22, 18, 20, 23, 22, 18, 16)
MIN_ROWS = 10_000
MAX_ROWS = 250_000
RISK_RATE = 0.10

@dataclass(frozen=True)
class Location:
    city: str
    province: str
    country: str

SK_LOCATIONS = (
    Location("REGINA", "SK", "CANADA"),
    Location("SASKATOON", "SK", "CANADA"),
    Location("PRINCE ALBERT", "SK", "CANADA"),
    Location("MOOSE JAW", "SK", "CANADA"),
    Location("YORKTON", "SK", "CANADA"),
    Location("SWIFT CURRENT", "SK", "CANADA"),
    Location("MEADOW LAKE", "SK", "CANADA"),
    Location("LLOYDMINSTER", "SK", "CANADA"),
)
OTHER_CANADIAN_LOCATIONS = (
    Location("EDMONTON", "AB", "CANADA"),
    Location("CALGARY", "AB", "CANADA"),
    Location("VANCOUVER", "BC", "CANADA"),
    Location("WINNIPEG", "MB", "CANADA"),
    Location("TORONTO", "ON", "CANADA"),
    Location("OTTAWA", "ON", "CANADA"),
    Location("MONTREAL", "QC", "CANADA"),
    Location("FREDERICTON", "NB", "CANADA"),
)
FOREIGN_LOCATIONS = (
    Location("MINOT", "ND", "UNITED STATES"),
    Location("PROVO", "UT", "UNITED STATES"),
    Location("LONDON", "ENGLAND", "UNITED KINGDOM"),
    Location("SEOUL", "SEOUL", "KOREA, REPUBLIC OF"),
    Location("DUBLIN", "LEINSTER", "IRELAND"),
    Location("TOKYO", "TOKYO", "JAPAN"),
    Location("SYDNEY", "NSW", "AUSTRALIA"),
    Location("BERLIN", "BERLIN", "GERMANY"),
)
RISK_SCENARIO_WEIGHTS = (
    ("R08_STUDENT_OUTSIDE_SK", 23),
    ("R13_CRA_OUTSIDE_SK", 20),
    ("R10_HIGH_NEED_GRANTS_ONLY", 20),
    ("R16_CRA_SK_STUDY_AND_LIVE_OUTSIDE", 15),
    ("R02_MARITAL_MISMATCH", 8),
    ("R11_AGE_OVER_65", 6),
    ("R19_OUTSIDE_SK_AT_FOREIGN_INSTITUTION", 4),
    ("R20_FOREIGN_STUDENT_OUTSIDE_SK", 4),
)
```

Create `fraud_rules.py` with case-normalized access and stable match order:

```python
from collections.abc import Callable, Mapping

Record = Mapping[str, object]

def _text(record: Record, field: str) -> str:
    return str(record.get(field) or "").strip().upper()

def _number(record: Record, field: str) -> float:
    return float(record.get(field) or 0)

RULES: tuple[tuple[str, Callable[[Record], bool]], ...] = (
    ("R02_MARITAL_MISMATCH", lambda r: _text(r, "MARITAL_STATUS") != _text(r, "CRA_MARITAL_STATUS")),
    ("R08_STUDENT_OUTSIDE_SK", lambda r: _text(r, "STUDENT_PROVINCE") != "SK"),
    ("R10_HIGH_NEED_GRANTS_ONLY", lambda r: _number(r, "TOTAL_NEED") > 50_000 and _text(r, "GRANTS_ONLY_IND") == "Y"),
    ("R11_AGE_OVER_65", lambda r: _number(r, "STUDENT_AGE") > 65),
    ("R13_CRA_OUTSIDE_SK", lambda r: bool(_text(r, "CRA_PROVINCE")) and _text(r, "CRA_PROVINCE") != "SK"),
    ("R16_CRA_SK_STUDY_AND_LIVE_OUTSIDE", lambda r: _text(r, "INSTITUTION_PROVINCE") != "SK" and _text(r, "STUDENT_PROVINCE") != "SK" and _text(r, "CRA_PROVINCE") == "SK"),
    ("R19_OUTSIDE_SK_AT_FOREIGN_INSTITUTION", lambda r: _text(r, "STUDENT_PROVINCE") != "SK" and _text(r, "INSTITUTION_COUNTRY") != "CANADA"),
    ("R20_FOREIGN_STUDENT_OUTSIDE_SK", lambda r: _text(r, "STUDENT_COUNTRY") != "CANADA" and _text(r, "STUDENT_PROVINCE") != "SK"),
)
RULE_IDS = tuple(rule_id for rule_id, _predicate in RULES)

def evaluate_rules(record: Record) -> tuple[str, ...]:
    return tuple(rule_id for rule_id, predicate in RULES if predicate(record))

def fraud_label(record: Record) -> str:
    return "Yes" if evaluate_rules(record) else "No"
```

- [ ] **Step 4: Run the rule tests and the existing suite**

Run: `.venv/bin/python -m pytest tests/test_fraud_rules.py -q`

Expected: all rule tests pass.

Run: `.venv/bin/python -m pytest -q`

Expected: existing suite and new tests pass.

- [ ] **Step 5: Commit the pure rule layer**

```bash
git add grant_app/data_generator_schema.py grant_app/fraud_rules.py tests/test_fraud_rules.py
git commit -m "feat: define fraud screening rules"
```

---

### Task 2: Coherent ordinary records and weighted risk scenarios

**Files:**
- Modify: `grant_app/data_generator_schema.py`
- Create: `grant_app/data_generator.py`
- Create: `tests/test_data_generator.py`

**Interfaces:**
- Consumes: `Location`, location pools, `RISK_RATE`, `RISK_SCENARIO_WEIGHTS`, `evaluate_rules`, and `fraud_label`.
- Produces: `generate_rows(count: int, rng: random.Random | None = None) -> Iterator[dict[str, object]]`.
- Produces: `assert_record_invariants(record: Mapping[str, object]) -> None` for defensive checks and direct tests.

- [ ] **Step 1: Write failing tests for reproducibility, invariants, diversity, and prevalence**

```python
# tests/test_data_generator.py
import random
from collections import Counter

from grant_app.data_generator import assert_record_invariants, generate_rows
from grant_app.data_generator_schema import HEADERS
from grant_app.fraud_rules import RULE_IDS, evaluate_rules, fraud_label


def test_fixed_seed_is_reproducible_and_schema_exact():
    first = list(generate_rows(50, random.Random(20260826)))
    second = list(generate_rows(50, random.Random(20260826)))
    assert first == second
    assert all(tuple(row) == HEADERS for row in first)


def test_generated_records_obey_business_invariants():
    for record in generate_rows(2_000, random.Random(11)):
        assert_record_invariants(record)
        assert record["FRAUD_Label "] == fraud_label(record)
        assert isinstance(record["NBR_OF_DEPENDENTS"], int)
        assert isinstance(record["STUDENT_AGE"], int)
        assert isinstance(record["TOTAL_NEED"], (int, float))


def test_large_seeded_sample_is_diverse_and_near_ten_percent_positive():
    rows = list(generate_rows(20_000, random.Random(44)))
    positive = [row for row in rows if row["FRAUD_Label "] == "Yes"]
    matched = Counter(rule for row in rows for rule in evaluate_rules(row))
    assert 0.09 <= len(positive) / len(rows) <= 0.11
    assert set(matched) == set(RULE_IDS)
    assert len({row["STUDENT_CITY"] for row in rows}) >= 8
    assert len({row["INSTITUTION_CITY"] for row in rows}) >= 16
    assert len({row["TOTAL_NEED"] for row in rows}) >= 5_000
    assert len({row["STUDENT_AGE"] for row in rows}) >= 45
```

- [ ] **Step 2: Run generator tests and observe the missing-module failure**

Run: `.venv/bin/python -m pytest tests/test_data_generator.py -q`

Expected: collection fails because `grant_app.data_generator` does not exist.

- [ ] **Step 3: Implement normal profiles, risk mutations, and lazy row generation**

Add explicit category profiles to `data_generator_schema.py`:

```python
CATEGORY_PROFILES = (
    ("Single Independent", ("Single", "Separated", "Divorced", "Widowed"), 0, 48),
    ("Single Dependent", ("Single",), 0, 14),
    ("Single Parent", ("Single", "Separated", "Divorced", "Widowed"), 1, 23),
    ("Married", ("Married", "Common-Law"), 0, 15),
)
MARITAL_STATUSES = ("Single", "Separated", "Married", "Common-Law", "Divorced", "Widowed")
```

Implement `data_generator.py` around these exact helpers:

```python
import random
from collections.abc import Iterator, Mapping

from .data_generator_schema import (
    CATEGORY_PROFILES, FOREIGN_LOCATIONS, HEADERS, MARITAL_STATUSES,
    OTHER_CANADIAN_LOCATIONS, RISK_RATE, RISK_SCENARIO_WEIGHTS, SK_LOCATIONS,
)
from .fraud_rules import evaluate_rules, fraud_label

def _weighted_choice(rng, items, weight_index=-1):
    return rng.choices(items, weights=[item[weight_index] for item in items], k=1)[0]

def _ordinary_record(rng: random.Random) -> dict[str, object]:
    category, statuses, minimum_dependents, _weight = _weighted_choice(rng, CATEGORY_PROFILES)
    marital = rng.choice(statuses)
    if category == "Single Parent":
        dependents = rng.choices((1, 2, 3, 4, 5, 6), (46, 31, 14, 5, 3, 1), k=1)[0]
    elif category == "Married":
        dependents = rng.choices((0, 1, 2, 3, 4), (45, 24, 20, 8, 3), k=1)[0]
    else:
        dependents = minimum_dependents
    student = rng.choice(SK_LOCATIONS)
    institution_pool = rng.choices(
        (SK_LOCATIONS, OTHER_CANADIAN_LOCATIONS, FOREIGN_LOCATIONS),
        (74, 20, 6), k=1,
    )[0]
    institution = rng.choice(institution_pool)
    grants_only = "Y" if rng.random() < 0.16 else "N"
    total_need = round(rng.triangular(1_000, 75_000, 24_000), 2)
    if grants_only == "Y" and total_need > 50_000:
        total_need = round(rng.uniform(1_000, 50_000), 2)
    cra_missing = rng.random() < 0.003
    record = {
        "CLIENT_DEPENDENT_STATUS": "With Dependents" if dependents else "Without Dependents",
        "DISABILITY_STATUS_IND": "Y" if rng.random() < 0.36 else "N",
        "INSTITUTION_CITY": institution.city,
        "INSTITUTION_PROVINCE": institution.province,
        "INSTITUTION_COUNTRY": institution.country,
        "OUT_OF_PROV_IND": "N",
        "NBR_OF_DEPENDENTS": dependents,
        "TOTAL_NEED": total_need,
        "STUDENT_AGE": round(rng.triangular(18, 65, 27)),
        "STUDENT_CITY": student.city,
        "STUDENT_PROVINCE": student.province,
        "STUDENT_COUNTRY": student.country,
        "CLIENT_CATEGORY": category,
        "MARITAL_STATUS": marital,
        "GRANTS_ONLY_IND": grants_only,
        "CRA_MARITAL_STATUS": marital,
        "CRA_CITY": "" if cra_missing else student.city,
        "CRA_PROVINCE": "" if cra_missing else "SK",
    }
    _sync_out_of_province(record)
    if evaluate_rules(record):
        raise AssertionError("ordinary profile unexpectedly matched a rule")
    return record

def _sync_out_of_province(record):
    same_country = record["INSTITUTION_COUNTRY"] == record["STUDENT_COUNTRY"]
    same_province = record["INSTITUTION_PROVINCE"] == record["STUDENT_PROVINCE"]
    record["OUT_OF_PROV_IND"] = "N" if same_country and same_province else "Y"

def _apply_risk_scenario(record, scenario, rng):
    if scenario == "R02_MARITAL_MISMATCH":
        alternatives = tuple(status for status in MARITAL_STATUSES if status != record["MARITAL_STATUS"])
        record["CRA_MARITAL_STATUS"] = rng.choice(alternatives)
    elif scenario == "R08_STUDENT_OUTSIDE_SK":
        location = rng.choice(OTHER_CANADIAN_LOCATIONS)
        record.update(STUDENT_CITY=location.city, STUDENT_PROVINCE=location.province, STUDENT_COUNTRY=location.country)
    elif scenario == "R10_HIGH_NEED_GRANTS_ONLY":
        record.update(TOTAL_NEED=round(rng.uniform(50_000.01, 75_000), 2), GRANTS_ONLY_IND="Y")
    elif scenario == "R11_AGE_OVER_65":
        record["STUDENT_AGE"] = rng.randint(66, 82)
    elif scenario == "R13_CRA_OUTSIDE_SK":
        location = rng.choice(OTHER_CANADIAN_LOCATIONS)
        record.update(CRA_CITY=location.city, CRA_PROVINCE=location.province)
    elif scenario == "R16_CRA_SK_STUDY_AND_LIVE_OUTSIDE":
        student = rng.choice(OTHER_CANADIAN_LOCATIONS)
        institution = rng.choice(OTHER_CANADIAN_LOCATIONS)
        record.update(STUDENT_CITY=student.city, STUDENT_PROVINCE=student.province, STUDENT_COUNTRY="CANADA", INSTITUTION_CITY=institution.city, INSTITUTION_PROVINCE=institution.province, INSTITUTION_COUNTRY="CANADA", CRA_CITY=rng.choice(SK_LOCATIONS).city, CRA_PROVINCE="SK")
    elif scenario == "R19_OUTSIDE_SK_AT_FOREIGN_INSTITUTION":
        student = rng.choice(OTHER_CANADIAN_LOCATIONS)
        institution = rng.choice(FOREIGN_LOCATIONS)
        record.update(STUDENT_CITY=student.city, STUDENT_PROVINCE=student.province, STUDENT_COUNTRY="CANADA", INSTITUTION_CITY=institution.city, INSTITUTION_PROVINCE=institution.province, INSTITUTION_COUNTRY=institution.country)
    elif scenario == "R20_FOREIGN_STUDENT_OUTSIDE_SK":
        student = rng.choice(FOREIGN_LOCATIONS)
        record.update(STUDENT_CITY=student.city, STUDENT_PROVINCE=student.province, STUDENT_COUNTRY=student.country)
    else:
        raise ValueError(f"unsupported risk scenario: {scenario}")
    _sync_out_of_province(record)

def assert_record_invariants(record: Mapping[str, object]) -> None:
    assert tuple(record) == HEADERS
    assert record["CLIENT_DEPENDENT_STATUS"] == ("With Dependents" if record["NBR_OF_DEPENDENTS"] else "Without Dependents")
    expected_out = "N" if record["INSTITUTION_COUNTRY"] == record["STUDENT_COUNTRY"] and record["INSTITUTION_PROVINCE"] == record["STUDENT_PROVINCE"] else "Y"
    assert record["OUT_OF_PROV_IND"] == expected_out
    assert record["FRAUD_Label "] == fraud_label(record)

def generate_rows(count: int, rng: random.Random | None = None) -> Iterator[dict[str, object]]:
    if count < 0:
        raise ValueError("count must not be negative")
    source = rng or random.Random()
    scenarios, weights = zip(*RISK_SCENARIO_WEIGHTS)
    for _index in range(count):
        record = _ordinary_record(source)
        if source.random() < RISK_RATE:
            _apply_risk_scenario(record, source.choices(scenarios, weights=weights, k=1)[0], source)
            if not evaluate_rules(record):
                raise AssertionError("risk profile did not match a rule")
        record["FRAUD_Label "] = fraud_label(record)
        assert_record_invariants(record)
        yield record
```

- [ ] **Step 4: Run generator tests and correct only behaviour exposed by failures**

Run: `.venv/bin/python -m pytest tests/test_data_generator.py -q`

Expected: all generator tests pass with a positive rate between 9% and 11%, every rule covered, and deterministic fixed-seed rows.

- [ ] **Step 5: Run rule and generator tests together, then commit**

Run: `.venv/bin/python -m pytest tests/test_fraud_rules.py tests/test_data_generator.py -q`

Expected: all pass.

```bash
git add grant_app/data_generator_schema.py grant_app/data_generator.py tests/test_data_generator.py
git commit -m "feat: generate coherent fraud scenarios"
```

---

### Task 3: Constant-memory XLSX exporter

**Files:**
- Create: `grant_app/xlsx_export.py`
- Create: `tests/test_xlsx_export.py`

**Interfaces:**
- Consumes: `HEADERS`, `NUMERIC_HEADERS`, and a lazy iterable of record mappings.
- Produces: `write_xlsx(output: BinaryIO, rows: Iterable[Mapping[str, object]], expected_rows: int) -> None`.
- Contract: seeks the completed output to byte zero, raises `ValueError` when the iterator length differs from `expected_rows`, and never materializes all rows.

- [ ] **Step 1: Write failing tests for package validity, headers, row count, and cell types**

```python
# tests/test_xlsx_export.py
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
```

- [ ] **Step 2: Run exporter tests and observe the missing-module failure**

Run: `.venv/bin/python -m pytest tests/test_xlsx_export.py -q`

Expected: collection fails because `grant_app.xlsx_export` does not exist.

- [ ] **Step 3: Implement the minimal OOXML package and streaming worksheet writer**

Use standard-library XML escaping and `ZipFile.open()` so worksheet rows are compressed as they are generated. Define complete static package parts, including content types for workbook, worksheet, and styles; root relationship to `xl/workbook.xml`; workbook relationship to `worksheets/sheet1.xml` and `styles.xml`; one sheet named `Sheet1`; and a two-style stylesheet with a bold filled header.

```python
import zipfile
from collections.abc import BinaryIO, Iterable, Mapping
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

def _cell(reference: str, value: object, *, header: bool = False) -> bytes:
    style = ' s="1"' if header else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{reference}"{style}><v>{value}</v></c>'.encode()
    text = str(value or "")
    preserve = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{reference}" t="inlineStr"{style}><is><t{preserve}>{escape(text)}</t></is></c>'.encode()

def write_xlsx(output: BinaryIO, rows: Iterable[Mapping[str, object]], expected_rows: int) -> None:
    if expected_rows < 0:
        raise ValueError("expected_rows must not be negative")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
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
            sheet.write(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{MAIN_NS}"><dimension ref="A1:S{last_row}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{columns}</cols><sheetData>'.encode())
            sheet.write(b'<row r="1">')
            for column, header in enumerate(HEADERS, start=1):
                sheet.write(_cell(f"{_column_name(column)}1", header, header=True))
            sheet.write(b'</row>')
            actual = 0
            for actual, record in enumerate(rows, start=1):
                if actual > expected_rows:
                    raise ValueError(f"expected {expected_rows} rows but received more")
                excel_row = actual + 1
                sheet.write(f'<row r="{excel_row}">'.encode())
                for column, header in enumerate(HEADERS, start=1):
                    value = record[header]
                    if header in NUMERIC_HEADERS and not isinstance(value, (int, float)):
                        raise TypeError(f"{header} must be numeric")
                    sheet.write(_cell(f"{_column_name(column)}{excel_row}", value))
                sheet.write(b'</row>')
            if actual != expected_rows:
                raise ValueError(f"expected {expected_rows} rows but received {actual}")
            sheet.write(f'</sheetData><autoFilter ref="A1:S{last_row}"/></worksheet>'.encode())
    output.seek(0)
```

- [ ] **Step 4: Run exporter tests and inspect a compact workbook package**

Run: `.venv/bin/python -m pytest tests/test_xlsx_export.py -q`

Expected: both tests pass; `archive.testzip()` returns `None`, header text including the trailing space survives, and G/H/I are numeric cells.

Run: `.venv/bin/python -m pytest tests/test_fraud_rules.py tests/test_data_generator.py tests/test_xlsx_export.py -q`

Expected: all pass.

- [ ] **Step 5: Commit the exporter**

```bash
git add grant_app/xlsx_export.py tests/test_xlsx_export.py
git commit -m "feat: stream synthetic data to xlsx"
```

---

### Task 4: Row-count form and safe Flask download route

**Files:**
- Modify: `grant_app/forms.py`
- Modify: `grant_app/routes.py`
- Modify: `tests/test_forms.py`
- Create: `tests/test_data_generator_routes.py`

**Interfaces:**
- Consumes: `MIN_ROWS`, `MAX_ROWS`, `generate_rows`, and `write_xlsx`.
- Produces: `DataGeneratorForm` with `row_count: IntegerField`.
- Produces: `GET|POST /data-generator`; valid POST returns the XLSX attachment.

- [ ] **Step 1: Write failing form tests for inclusive limits and invalid values**

Append to `tests/test_forms.py`:

```python
from grant_app.forms import DataGeneratorForm

@pytest.mark.parametrize("value", ["10000", "250000"])
def test_data_generator_form_accepts_inclusive_limits(value):
    form = DataGeneratorForm(data={"row_count": value})
    assert form.validate()

@pytest.mark.parametrize("value", ["", "9999", "250001", "10.5", "many"])
def test_data_generator_form_rejects_invalid_counts(value):
    form = DataGeneratorForm(data={"row_count": value})
    assert not form.validate()
    assert form.row_count.errors
```

- [ ] **Step 2: Run the form tests and observe the missing-class failure**

Run: `.venv/bin/python -m pytest tests/test_forms.py -q`

Expected: collection fails because `DataGeneratorForm` is not defined.

- [ ] **Step 3: Implement the minimal form and make its tests pass**

Add to `grant_app/forms.py`:

```python
from .data_generator_schema import MAX_ROWS, MIN_ROWS

class DataGeneratorForm(FlaskForm):
    row_count = IntegerField(
        "Number of rows",
        validators=[
            InputRequired(message="Number of rows is required."),
            NumberRange(
                min=MIN_ROWS,
                max=MAX_ROWS,
                message=f"Number of rows must be between {MIN_ROWS:,} and {MAX_ROWS:,}.",
            ),
        ],
    )
```

Run: `.venv/bin/python -m pytest tests/test_forms.py -q`

Expected: all form tests pass.

- [ ] **Step 4: Write failing route tests for GET, validation, download, maximum handoff, and safe failure**

Create `tests/test_data_generator_routes.py` with these behaviours:

```python
import io
import logging
import zipfile

class TrackingBuffer(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.was_closed = False

    def close(self):
        self.was_closed = True
        super().close()

def test_get_data_generator_page(client):
    response = client.get("/data-generator")
    assert response.status_code == 200
    assert b"Data Generator" in response.data
    assert b'name="row_count"' in response.data

def test_invalid_count_returns_422_without_download(client):
    response = client.post("/data-generator", data={"row_count": "9999"})
    assert response.status_code == 422
    assert b"between 10,000 and 250,000" in response.data
    assert "attachment" not in response.headers.get("Content-Disposition", "")

def test_minimum_count_downloads_valid_xlsx(client):
    response = client.post("/data-generator", data={"row_count": "10000"})
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "synthetic_fraud_data_10000_" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.testzip() is None
    response.close()

def test_maximum_count_is_passed_to_lazy_generator(client, monkeypatch):
    from grant_app import routes
    captured = {}
    def capture_count(count):
        captured["count"] = count
        return iter(())
    monkeypatch.setattr(routes, "generate_rows", capture_count)
    monkeypatch.setattr(routes, "write_xlsx", lambda output, rows, expected_rows: output.write(b"test-xlsx"))
    response = client.post("/data-generator", data={"row_count": "250000"})
    assert response.status_code == 200
    assert captured["count"] == 250000

def test_response_close_releases_temporary_file(client, monkeypatch):
    from grant_app import routes
    output = TrackingBuffer()
    monkeypatch.setattr(routes.tempfile, "TemporaryFile", lambda **_kwargs: output)
    monkeypatch.setattr(routes, "write_xlsx", lambda target, rows, expected_rows: target.write(b"xlsx"))
    response = client.post("/data-generator", data={"row_count": "10000"})
    response.close()
    assert output.was_closed

def test_generation_failure_is_sanitized(client, monkeypatch, caplog):
    from grant_app import routes
    output = TrackingBuffer()
    def fail_export(output, rows, expected_rows):
        raise RuntimeError("private temp path /secret/output.xlsx") from OSError("disk details")
    monkeypatch.setattr(routes.tempfile, "TemporaryFile", lambda **_kwargs: output)
    monkeypatch.setattr(routes, "write_xlsx", fail_export)
    with caplog.at_level(logging.ERROR):
        response = client.post("/data-generator", data={"row_count": "10000"})
    assert response.status_code == 503
    assert b"could not generate" in response.data.lower()
    assert b"/secret/output.xlsx" not in response.data
    assert "data_generation_failed" in caplog.text
    assert "/secret/output.xlsx" not in caplog.text
    assert output.was_closed
```

- [ ] **Step 5: Run route tests and observe the missing-route failures**

Run: `.venv/bin/python -m pytest tests/test_data_generator_routes.py -q`

Expected: GET returns 404 and POST tests fail because the route does not exist.

- [ ] **Step 6: Implement temporary-file ownership, response cleanup, and safe errors**

Add imports and this route structure to `grant_app/routes.py`:

```python
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import send_file

from .data_generator import generate_rows
from .forms import DataGeneratorForm, StudentApplicationForm
from .xlsx_export import write_xlsx

GENERATOR_RETRY_MESSAGE = "We could not generate the Excel file right now. Please try again."
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

@web.route("/data-generator", methods=["GET", "POST"])
def data_generator():
    form = DataGeneratorForm()
    if form.validate_on_submit():
        output = None
        try:
            output = tempfile.TemporaryFile(mode="w+b")
            rows = generate_rows(form.row_count.data)
            write_xlsx(output, rows, expected_rows=form.row_count.data)
            date_stamp = datetime.now(ZoneInfo("America/Vancouver")).strftime("%Y%m%d")
            response = send_file(
                output,
                mimetype=XLSX_MIMETYPE,
                as_attachment=True,
                download_name=f"synthetic_fraud_data_{form.row_count.data}_{date_stamp}.xlsx",
                max_age=0,
            )
            response.call_on_close(output.close)
            return response
        except Exception as error:
            if output is not None:
                output.close()
            log_exception_context(current_app.logger, "data_generation_failed", error)
            flash(GENERATOR_RETRY_MESSAGE, "error")
            return render_template("data_generator/new.html", form=form), 503
    status = 422 if request.method == "POST" else 200
    return render_template("data_generator/new.html", form=form), status
```

The broad catch is restricted to this request boundary: it guarantees temporary-file closure and a safe operator response; the diagnostic helper logs types and traceback location without messages or generated data.

Create a temporary minimal `grant_app/templates/data_generator/new.html` that extends `base.html`, renders `form.hidden_tag()`, `form.row_count`, errors, and a submit button so route tests can proceed. Task 5 replaces it with the complete approved markup.

- [ ] **Step 7: Run focused and full tests, then commit**

Run: `.venv/bin/python -m pytest tests/test_forms.py tests/test_data_generator_routes.py -q`

Expected: all pass.

Run: `.venv/bin/python -m pytest -q`

Expected: full suite passes.

```bash
git add grant_app/forms.py grant_app/routes.py grant_app/templates/data_generator/new.html tests/test_forms.py tests/test_data_generator_routes.py
git commit -m "feat: serve synthetic data downloads"
```

---

### Task 5: Integrated accessible page, navigation, and submit feedback

**Files:**
- Modify: `grant_app/templates/data_generator/new.html`
- Create: `grant_app/static/js/data-generator-form.js`
- Modify: `grant_app/templates/base.html`
- Modify: `tests/test_security_accessibility.py`

**Interfaces:**
- Consumes: `DataGeneratorForm` and the existing base template/CSS form classes.
- Produces: keyboard-accessible form, linked error summary, and `Data Generator` primary-navigation link.

- [ ] **Step 1: Write failing integration assertions for navigation, form semantics, help, and script**

Extend `tests/test_security_accessibility.py`:

```python
def test_data_generator_page_has_accessible_form_and_navigation(client):
    response = client.get("/data-generator")
    assert response.status_code == 200
    assert b'href="/data-generator"' in response.data
    assert b'id="data-generator-form"' in response.data
    assert b'id="row-count-help"' in response.data
    assert b'min="10000"' in response.data
    assert b'max="250000"' in response.data
    assert b'step="1"' in response.data
    assert b'<script src="/static/js/data-generator-form.js" defer></script>' in response.data

def test_invalid_generator_form_links_summary_to_row_count(client):
    response = client.post("/data-generator", data={"row_count": "9999"})
    assert response.status_code == 422
    assert b'id="error-summary"' in response.data
    assert b'href="#row_count"' in response.data
    assert b'aria-describedby="row-count-help row_count-error"' in response.data
    assert b'id="row_count-error"' in response.data
```

- [ ] **Step 2: Run the accessibility tests and observe missing markup failures**

Run: `.venv/bin/python -m pytest tests/test_security_accessibility.py -q`

Expected: the new tests fail on the absent navigation link, help text, field attributes, or script.

- [ ] **Step 3: Implement the approved generator page and navigation entry**

Use the existing error-summary and field-error structure in `new.html`:

```html
{% extends "base.html" %}
{% block title %}Data Generator · Student Grant Applications{% endblock %}
{% block content %}
  <h2>Data Generator</h2>
  <p>Create synthetic student-grant data. A Fraud Label of Yes means at least one supported screening rule matched.</p>
  {% if form.errors %}
    <section id="error-summary" class="error-summary" role="alert" aria-labelledby="error-summary-title" tabindex="-1">
      <h3 id="error-summary-title">Please correct the following errors</h3>
      <ul>{% for error in form.row_count.errors %}<li><a href="#{{ form.row_count.id }}">{{ form.row_count.label.text }}: {{ error }}</a></li>{% endfor %}</ul>
    </section>
  {% endif %}
  <form id="data-generator-form" class="application-form" method="post" novalidate>
    {{ form.hidden_tag() }}
    <div class="form-field">
      {{ form.row_count.label }}
      {{ form.row_count(required=true, min="10000", max="250000", step="1", inputmode="numeric", aria_invalid="true" if form.row_count.errors else "false", aria_describedby="row-count-help " ~ form.row_count.id ~ "-error" if form.row_count.errors else "row-count-help") }}
      <p id="row-count-help">Enter between 10,000 and 250,000 rows. Larger files may take longer.</p>
      {% if form.row_count.errors %}<div id="{{ form.row_count.id }}-error" class="field-error">{% for error in form.row_count.errors %}<p>{{ error }}</p>{% endfor %}</div>{% endif %}
    </div>
    <div class="form-actions"><button type="submit">Generate Excel File</button></div>
  </form>
{% endblock %}
{% block scripts %}<script src="{{ url_for('static', filename='js/data-generator-form.js') }}" defer></script>{% endblock %}
```

Add `<a href="{{ url_for('web.data_generator') }}">Data Generator</a>` after Application History in `base.html`.

- [ ] **Step 4: Implement duplicate-submit prevention and error focus**

```javascript
// grant_app/static/js/data-generator-form.js
const dataGeneratorForm = document.querySelector("#data-generator-form");
const errorSummary = document.querySelector("#error-summary");

if (errorSummary) {
  errorSummary.focus();
}

if (dataGeneratorForm) {
  dataGeneratorForm.addEventListener("submit", () => {
    if (!dataGeneratorForm.checkValidity()) {
      return;
    }
    const button = dataGeneratorForm.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.textContent = "Generating…";
    }
  });
}
```

- [ ] **Step 5: Run accessibility, route, and full regression tests**

Run: `.venv/bin/python -m pytest tests/test_security_accessibility.py tests/test_data_generator_routes.py -q`

Expected: all pass.

Run: `.venv/bin/python -m pytest -q`

Expected: all pass with no warnings.

- [ ] **Step 6: Commit the integrated page**

```bash
git add grant_app/templates/data_generator/new.html grant_app/static/js/data-generator-form.js grant_app/templates/base.html tests/test_security_accessibility.py
git commit -m "feat: add data generator page"
```

---

### Task 6: Operator documentation and end-to-end verification

**Files:**
- Modify: `README.md`
- Modify: `docs/manual-test-checklist.md`
- Modify only if verification exposes a defect: files introduced in Tasks 1–5 and their tests.

**Interfaces:**
- Consumes: the complete web generator.
- Produces: documented local workflow and verification evidence for 10,000 and 250,000 rows.

- [ ] **Step 1: Write failing documentation tests for the discoverable workflow**

Extend `tests/test_readme.py` with literal expectations:

```python
def test_readme_documents_data_generator_limits_and_download():
    contents = README_PATH.read_text(encoding="utf-8")
    assert "Data Generator" in contents
    assert "10,000" in contents
    assert "250,000" in contents
    assert "Fraud Label" in contents
```

Run: `.venv/bin/python -m pytest tests/test_readme.py -q`

Expected: fails because the README does not yet mention the generator.

- [ ] **Step 2: Document generation, interpretation, and manual checks**

Add a README section after Start and stop explaining: open `Data Generator`, enter 10,000–250,000, download the XLSX, and interpret `Yes` as a screening-rule match rather than confirmed fraud. Add checklist items for keyboard navigation, invalid limits, a 10,000-row download, opening the workbook, exact headers, populated labels, and a 250,000-row performance run.

- [ ] **Step 3: Run all automated tests from a clean process**

Run: `.venv/bin/python -m pytest -q`

Expected: every test passes with no errors or warnings.

- [ ] **Step 4: Generate and audit a 10,000-row workbook without keeping support files in the repository**

Use a temporary directory and Flask test client to POST `row_count=10000`; save the response body as `synthetic_fraud_data_10000.xlsx`. Inspect the package with the bundled spreadsheet runtime: verify one sheet, 10,001 total rows, 19 columns, exact headers, numeric G/H/I cells, populated S values, and no formula errors. Render `Sheet1!A1:S25` and visually confirm headers are legible and rows align.

Expected: the workbook imports and renders successfully; the first row is frozen and every data row has a `Yes` or `No` label.

- [ ] **Step 5: Recompute every 10,000-row label and prevalence from workbook values**

Read the generated workbook with the bundled spreadsheet runtime, convert each row to a mapping, and compare column S with `fraud_label(record)`. Count labels and rule identifiers.

Expected: zero label mismatches, all eight rules represented for the fixed verification seed or repeated random run, and a `Yes` rate between 9% and 11%.

- [ ] **Step 6: Run the 250,000-row performance acceptance check**

Run a dedicated Python command that wraps `write_xlsx` with `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` before and after, writes to `tempfile.TemporaryFile`, and records elapsed time and output byte size. Do not load the response body or rows into a list.

Expected: 250,000 data rows complete within 180 seconds, the ZIP passes `ZipFile.testzip()`, output begins with `PK`, and peak RSS increases by less than 150 MiB. Record the observed elapsed time, file size, and peak RSS in the task handoff.

- [ ] **Step 7: Perform browser acceptance testing**

Start the local Flask server on `127.0.0.1`, open the in-app browser, and verify desktop and narrow viewport behaviour: all three navigation links remain usable; the generator page explains the label; invalid values focus the summary; a valid submit disables the button and begins a download; existing New Application and Application History flows still work.

- [ ] **Step 8: Commit documentation and any verification-driven fixes**

```bash
git add README.md docs/manual-test-checklist.md tests/test_readme.py
git commit -m "docs: explain synthetic data generation"
```

If verification required a code fix, follow a fresh RED-GREEN cycle, stage the exact affected production and test files, and make a separate descriptive fix commit before the documentation commit.

- [ ] **Step 9: Review the final diff and repository state**

Run: `git diff --check 9ebf271..HEAD`

Run: `git status --short`

Expected: no whitespace errors; only the user's pre-existing `test.txt`, `outputs/`, and `work_iforest/` changes remain outside the feature commits.
