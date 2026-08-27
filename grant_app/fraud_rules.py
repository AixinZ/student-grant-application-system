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
