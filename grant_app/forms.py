"""Validate submitted student data and convert valid form values into domain input."""

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
    """Trim surrounding whitespace and normalize text to Unicode NFC.

    Args:
        value: A submitted string or ``None``.

    Returns:
        The normalized string, or the original non-string value.
    """
    return unicodedata.normalize("NFC", value.strip()) if isinstance(value, str) else value


def normalize_province(value: str | None) -> str | None:
    """Normalize a submitted province or territory code to uppercase.

    Args:
        value: A submitted province code or ``None``.

    Returns:
        A trimmed, NFC-normalized uppercase code, or the original non-string
        value.
    """
    return trim_text(value).upper() if isinstance(value, str) else value


def validate_name(_form, field) -> None:
    """Require a name to contain only letters and common name separators.

    Args:
        _form: The WTForms form instance; unused by this field validator.
        field: The name field containing normalized submitted text.

    Raises:
        ValidationError: If the name contains digits, punctuation other than
            apostrophes or hyphens, or other unsupported characters.
    """
    allowed_marks = {" ", "-", "'", "’"}
    if any(not (char.isalpha() or char in allowed_marks) for char in field.data):
        raise ValidationError(
            "Name may contain letters, spaces, apostrophes, and hyphens only."
        )


def reject_control_characters(_form, field) -> None:
    """Reject control, line-separator, and paragraph-separator characters.

    Args:
        _form: The WTForms form instance; unused by this field validator.
        field: The text field whose submitted value is inspected.

    Raises:
        ValidationError: If the value contains an unsupported Unicode control
            or separator character.
    """
    if any(
        unicodedata.category(char).startswith("C")
        or unicodedata.category(char) in {"Zl", "Zp"}
        for char in field.data
    ):
        raise ValidationError("This field contains unsupported characters.")


def validate_finite_income(_form, field) -> None:
    """Stop income validation when the parsed decimal is not finite.

    Args:
        _form: The WTForms form instance; unused by this field validator.
        field: The annual-income field containing a parsed ``Decimal``.

    Raises:
        StopValidation: If the value is positive infinity, negative infinity,
            or NaN.
    """
    if field.data is not None and not field.data.is_finite():
        raise StopValidation("Annual income must be a finite number.")


def validate_income_decimal_places(_form, field) -> None:
    """Limit annual income to at most two fractional decimal places.

    Args:
        _form: The WTForms form instance; unused by this field validator.
        field: The annual-income field containing a parsed ``Decimal``.

    Raises:
        ValidationError: If the submitted amount has more than two decimal
            places.
    """
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
        """Initialize the form and support a plain mapping through ``data``.

        Args:
            *args: Positional arguments forwarded to ``FlaskForm``.
            **kwargs: Keyword arguments forwarded to ``FlaskForm``. When a
                ``data`` mapping is provided without form data, it is converted
                to a ``MultiDict`` so normal parsing and validation still run.
        """
        data = kwargs.get("data")
        if data is not None and "formdata" not in kwargs and not args:
            kwargs["formdata"] = MultiDict(data)
            kwargs.pop("data")
        super().__init__(*args, **kwargs)

    def to_domain(self) -> ApplicationInput:
        """Convert a valid form into the service-layer input object.

        Returns:
            An immutable ``ApplicationInput`` containing all normalized values.

        Raises:
            ValueError: If the form does not pass validation at conversion time.
        """
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
