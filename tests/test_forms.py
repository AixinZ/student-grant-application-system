from decimal import Decimal

import pytest

from grant_app.forms import DataGeneratorForm, StudentApplicationForm


VALID_PAYLOAD = {
    "name": "Alex Student",
    "annual_income_cad": "42000.50",
    "address": "123 Main Street",
    "age": "24",
    "education_level": "BACHELORS_DEGREE",
    "marital_status": "SINGLE",
    "dependents": "0",
    "province": "BC",
}


@pytest.fixture(autouse=True)
def application_context(app):
    with app.app_context():
        yield


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("name", "   "),
        ("address", "   "),
        ("name", "A"),
        ("address", "1234"),
        ("name", "A" * 101),
        ("name", "Alex2 Student"),
        ("name", "Alex\x00 Student"),
        ("address", "1" * 201),
        ("address", "123 Main\x00 Street"),
        ("age", "15"),
        ("age", "101"),
        ("age", "18.5"),
        ("annual_income_cad", "-1"),
        ("annual_income_cad", "1000000000"),
        ("annual_income_cad", "1.999"),
        ("dependents", "-1"),
        ("dependents", "21"),
        ("dependents", "1.5"),
        ("education_level", "CERTIFICATE"),
        ("marital_status", "COMPLICATED"),
        ("province", "ZZ"),
    ],
    ids=[
        "blank-name",
        "blank-address",
        "short-name",
        "short-address",
        "long-name",
        "digit-in-name",
        "control-character-in-name",
        "long-address",
        "control-character-in-address",
        "young-age",
        "old-age",
        "fractional-age",
        "negative-income",
        "large-income",
        "income-with-three-decimals",
        "negative-dependents",
        "many-dependents",
        "fractional-dependents",
        "invalid-education",
        "invalid-marital-status",
        "invalid-province",
    ],
)
def test_rejects_invalid_application_input(field_name, value):
    form = StudentApplicationForm(data={**VALID_PAYLOAD, field_name: value})

    assert not form.validate()
    assert form[field_name].errors


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_rejects_non_finite_annual_income_without_raising(value):
    form = StudentApplicationForm(data={**VALID_PAYLOAD, "annual_income_cad": value})

    assert not form.validate()
    assert form.annual_income_cad.errors


@pytest.mark.parametrize("field_name", ["name", "address"])
@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_rejects_unicode_line_separators_in_text_fields(field_name, separator):
    form = StudentApplicationForm(
        data={**VALID_PAYLOAD, field_name: f"Alex{separator}Student"}
    )

    assert not form.validate()
    assert "This field contains unsupported characters." in form[field_name].errors


def test_normalizes_valid_application_into_domain_input():
    form = StudentApplicationForm(
        data={
            **VALID_PAYLOAD,
            "name": "  Marie-Claire O’Neil  ",
            "province": "bc",
        }
    )

    assert form.validate()

    domain = form.to_domain()
    assert domain.name == "Marie-Claire O’Neil"
    assert domain.province == "BC"
    assert domain.annual_income_cad == Decimal("42000.50")


def test_to_domain_requires_successful_validation():
    form = StudentApplicationForm(data={**VALID_PAYLOAD, "age": "15"})

    with pytest.raises(ValueError, match="valid"):
        form.to_domain()


@pytest.mark.parametrize("value", ["100", "250000"])
def test_data_generator_form_accepts_inclusive_limits(value):
    form = DataGeneratorForm(data={"row_count": value})

    assert form.validate()


@pytest.mark.parametrize("value", ["", "99", "250001", "10.5", "many"])
def test_data_generator_form_rejects_invalid_counts(value):
    form = DataGeneratorForm(data={"row_count": value})

    assert not form.validate()
    assert form.row_count.errors
