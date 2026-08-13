import unicodedata
from decimal import Decimal

from flask_wtf import FlaskForm
from werkzeug.datastructures import MultiDict
from wtforms import DecimalField, IntegerField, SelectField, StringField
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Length,
    NumberRange,
    StopValidation,
    ValidationError,
)

from .constants import EDUCATION_CHOICES, MARITAL_STATUS_CHOICES, PROVINCE_CHOICES
from .domain import ApplicationInput


def trim_text(value: str | None) -> str | None:
    return unicodedata.normalize("NFC", value.strip()) if isinstance(value, str) else value


def normalize_province(value: str | None) -> str | None:
    return trim_text(value).upper() if isinstance(value, str) else value


def validate_name(_form, field) -> None:
    allowed_marks = {" ", "-", "'", "’"}
    if any(not (char.isalpha() or char in allowed_marks) for char in field.data):
        raise ValidationError(
            "Name may contain letters, spaces, apostrophes, and hyphens only."
        )


def reject_control_characters(_form, field) -> None:
    if any(
        unicodedata.category(char).startswith("C")
        or unicodedata.category(char) in {"Zl", "Zp"}
        for char in field.data
    ):
        raise ValidationError("This field contains unsupported characters.")


def validate_finite_income(_form, field) -> None:
    if field.data is not None and not field.data.is_finite():
        raise StopValidation("Annual income must be a finite number.")


def validate_income_decimal_places(_form, field) -> None:
    if field.data is not None and field.data.as_tuple().exponent < -2:
        raise ValidationError("Annual income may have at most two decimal places.")


class StudentApplicationForm(FlaskForm):
    name = StringField(
        "Name",
        filters=[trim_text],
        validators=[
            DataRequired(message="Name is required."),
            Length(
                min=2,
                max=100,
                message="Name must be between 2 and 100 characters.",
            ),
            reject_control_characters,
            validate_name,
        ],
    )
    annual_income_cad = DecimalField(
        "Annual income (CAD)",
        validators=[
            InputRequired(message="Annual income is required."),
            validate_finite_income,
            NumberRange(
                min=Decimal("0"),
                max=Decimal("999999999.99"),
                message="Annual income must be between 0.00 and 999999999.99.",
            ),
            validate_income_decimal_places,
        ],
    )
    address = StringField(
        "Address",
        filters=[trim_text],
        validators=[
            DataRequired(message="Address is required."),
            Length(
                min=5,
                max=200,
                message="Address must be between 5 and 200 characters.",
            ),
            reject_control_characters,
        ],
    )
    age = IntegerField(
        "Age",
        validators=[
            InputRequired(message="Age is required."),
            NumberRange(
                min=16,
                max=100,
                message="Age must be between 16 and 100.",
            ),
        ],
    )
    education_level = SelectField(
        "Education level",
        choices=EDUCATION_CHOICES,
        validate_choice=True,
        validators=[DataRequired(message="Education level is required.")],
    )
    marital_status = SelectField(
        "Marital status",
        choices=MARITAL_STATUS_CHOICES,
        validate_choice=True,
        validators=[DataRequired(message="Marital status is required.")],
    )
    dependents = IntegerField(
        "Dependents",
        validators=[
            InputRequired(message="Dependents is required."),
            NumberRange(
                min=0,
                max=20,
                message="Dependents must be between 0 and 20.",
            ),
        ],
    )
    province = SelectField(
        "Province",
        choices=PROVINCE_CHOICES,
        filters=[normalize_province],
        validate_choice=True,
        validators=[DataRequired(message="Province is required.")],
    )

    def __init__(self, *args, **kwargs) -> None:
        data = kwargs.get("data")
        if data is not None and "formdata" not in kwargs and not args:
            kwargs["formdata"] = MultiDict(data)
            kwargs.pop("data")
        super().__init__(*args, **kwargs)

    def to_domain(self) -> ApplicationInput:
        if not self.validate():
            raise ValueError("Form must be valid before conversion.")

        return ApplicationInput(
            name=self.name.data,
            annual_income_cad=self.annual_income_cad.data,
            address=self.address.data,
            age=self.age.data,
            education_level=self.education_level.data,
            marital_status=self.marital_status.data,
            dependents=self.dependents.data,
            province=self.province.data,
        )
