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
