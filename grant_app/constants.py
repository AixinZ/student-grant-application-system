"""Provide shared decision values and the choices displayed by application forms."""

from enum import StrEnum


class Decision(StrEnum):
    APPROVED = "APPROVED"
    NOT_APPROVED = "NOT_APPROVED"


EDUCATION_CHOICES = (
    ("HIGH_SCHOOL_OR_BELOW", "High School or Below"),
    ("COLLEGE_DIPLOMA", "College / Diploma"),
    ("BACHELORS_DEGREE", "Bachelor's Degree"),
    ("MASTERS_DEGREE", "Master's Degree"),
    ("DOCTORATE", "Doctorate"),
)

MARITAL_STATUS_CHOICES = (
    ("SINGLE", "Single"),
    ("MARRIED", "Married"),
    ("COMMON_LAW", "Common-law"),
    ("DIVORCED", "Divorced"),
    ("SEPARATED", "Separated"),
    ("WIDOWED", "Widowed"),
)

PROVINCE_CHOICES = (
    ("AB", "Alberta (AB)"),
    ("BC", "British Columbia (BC)"),
    ("MB", "Manitoba (MB)"),
    ("NB", "New Brunswick (NB)"),
    ("NL", "Newfoundland and Labrador (NL)"),
    ("NS", "Nova Scotia (NS)"),
    ("NT", "Northwest Territories (NT)"),
    ("NU", "Nunavut (NU)"),
    ("ON", "Ontario (ON)"),
    ("PE", "Prince Edward Island (PE)"),
    ("QC", "Quebec (QC)"),
    ("SK", "Saskatchewan (SK)"),
    ("YT", "Yukon (YT)"),
)
