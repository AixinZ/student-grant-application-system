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
