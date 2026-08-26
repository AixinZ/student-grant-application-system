import random
from collections.abc import Iterator, Mapping

from .data_generator_schema import (
    CATEGORY_PROFILES,
    FOREIGN_LOCATIONS,
    HEADERS,
    MARITAL_STATUSES,
    OTHER_CANADIAN_LOCATIONS,
    RISK_RATE,
    RISK_SCENARIO_WEIGHTS,
    SK_LOCATIONS,
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
        (74, 20, 6),
        k=1,
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


def _sync_out_of_province(record: dict[str, object]) -> None:
    same_country = record["INSTITUTION_COUNTRY"] == record["STUDENT_COUNTRY"]
    same_province = record["INSTITUTION_PROVINCE"] == record["STUDENT_PROVINCE"]
    record["OUT_OF_PROV_IND"] = "N" if same_country and same_province else "Y"


def _apply_risk_scenario(record: dict[str, object], scenario: str, rng: random.Random) -> None:
    if scenario == "R02_MARITAL_MISMATCH":
        alternatives = tuple(status for status in MARITAL_STATUSES if status != record["MARITAL_STATUS"])
        record["CRA_MARITAL_STATUS"] = rng.choice(alternatives)
    elif scenario == "R08_STUDENT_OUTSIDE_SK":
        location = rng.choice(OTHER_CANADIAN_LOCATIONS)
        record.update(
            STUDENT_CITY=location.city,
            STUDENT_PROVINCE=location.province,
            STUDENT_COUNTRY=location.country,
        )
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
        record.update(
            STUDENT_CITY=student.city,
            STUDENT_PROVINCE=student.province,
            STUDENT_COUNTRY="CANADA",
            INSTITUTION_CITY=institution.city,
            INSTITUTION_PROVINCE=institution.province,
            INSTITUTION_COUNTRY="CANADA",
            CRA_CITY=rng.choice(SK_LOCATIONS).city,
            CRA_PROVINCE="SK",
        )
    elif scenario == "R19_OUTSIDE_SK_AT_FOREIGN_INSTITUTION":
        student = rng.choice(OTHER_CANADIAN_LOCATIONS)
        institution = rng.choice(FOREIGN_LOCATIONS)
        record.update(
            STUDENT_CITY=student.city,
            STUDENT_PROVINCE=student.province,
            STUDENT_COUNTRY="CANADA",
            INSTITUTION_CITY=institution.city,
            INSTITUTION_PROVINCE=institution.province,
            INSTITUTION_COUNTRY=institution.country,
        )
    elif scenario == "R20_FOREIGN_STUDENT_OUTSIDE_SK":
        student = rng.choice(FOREIGN_LOCATIONS)
        record.update(
            STUDENT_CITY=student.city,
            STUDENT_PROVINCE=student.province,
            STUDENT_COUNTRY=student.country,
        )
    else:
        raise ValueError(f"unsupported risk scenario: {scenario}")
    _sync_out_of_province(record)


def assert_record_invariants(record: Mapping[str, object]) -> None:
    assert tuple(record) == HEADERS
    assert record["CLIENT_DEPENDENT_STATUS"] == (
        "With Dependents" if record["NBR_OF_DEPENDENTS"] else "Without Dependents"
    )
    expected_out = (
        "N"
        if record["INSTITUTION_COUNTRY"] == record["STUDENT_COUNTRY"]
        and record["INSTITUTION_PROVINCE"] == record["STUDENT_PROVINCE"]
        else "Y"
    )
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
