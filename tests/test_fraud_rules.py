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
