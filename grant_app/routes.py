"""Handle application, history, detail, and synthetic-data HTTP requests."""

import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy.exc import SQLAlchemyError

from .approval import ApprovalEngineError
from .constants import Decision, EDUCATION_CHOICES, MARITAL_STATUS_CHOICES
from .data_generator import generate_rows
from .diagnostics import log_exception_context
from .forms import DataGeneratorForm, StudentApplicationForm
from .repository import ApplicationRepository
from .services import create_application
from .xlsx_export import write_xlsx


web = Blueprint("web", __name__)

RETRY_MESSAGE = "We could not process the application right now. Please try again."
GENERATOR_RETRY_MESSAGE = (
    "We could not generate the Excel file right now. Please try again."
)
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_HISTORY_PAGE = (2**63 - 1) // 20 + 1


def _positive_int(value: str | None) -> int:
    """Normalize a query-string value to a safe, positive history page number.

    Args:
        value: The raw page parameter, or ``None`` when it was omitted.

    Returns:
        The parsed one-based page number, or ``1`` when the value is invalid,
        non-positive, or too large for a safe SQLite offset.
    """
    try:
        parsed = int(value) if value is not None else 1
    except ValueError:
        return 1
    return parsed if 0 < parsed <= MAX_HISTORY_PAGE else 1


@web.get("/")
def index():
    """Redirect the site root to the new-application form.

    Returns:
        A redirect response targeting ``/applications/new``.
    """
    return redirect(url_for("web.application_new"))


@web.route("/applications/new", methods=["GET", "POST"])
def application_new():
    """Display the application form and process valid submissions.

    Returns:
        The empty or invalid form page, a redirect to the immutable detail page
        after successful creation, or a 503 form response when approval or
        persistence fails safely. Ordinary form-validation failures return 422;
        CSRF failures are intercepted by the application-level 400 handler.

    Notes:
        Successful submissions create one database record. Approval and database
        errors are sanitized before logging and never create a partial record.
    """
    form = StudentApplicationForm()
    if form.validate_on_submit():
        try:
            application = create_application(
                form.to_domain(), current_app.config["APPROVAL_ENGINE"]
            )
        except ApprovalEngineError as error:
            log_exception_context(
                current_app.logger, "application_approval_failed", error
            )
            flash(RETRY_MESSAGE, "error")
            return render_template("applications/new.html", form=form), 503
        except SQLAlchemyError as error:
            log_exception_context(
                current_app.logger, "application_persistence_failed", error
            )
            flash(RETRY_MESSAGE, "error")
            return render_template("applications/new.html", form=form), 503

        return redirect(
            url_for("web.application_detail", application_id=application.id)
        )

    status = 422 if request.method == "POST" else 200
    return render_template("applications/new.html", form=form), status


@web.route("/data-generator", methods=["GET", "POST"])
def data_generator():
    """Render the row-count form or return a generated XLSX attachment."""
    form = DataGeneratorForm()
    if form.validate_on_submit():
        output = None
        try:
            output = tempfile.TemporaryFile(mode="w+b")
            rows = generate_rows(form.row_count.data)
            write_xlsx(output, rows, expected_rows=form.row_count.data)
            date_stamp = datetime.now(ZoneInfo("America/Vancouver")).strftime(
                "%Y%m%d"
            )
            response = send_file(
                output,
                mimetype=XLSX_MIMETYPE,
                as_attachment=True,
                download_name=(
                    f"synthetic_fraud_data_{form.row_count.data}_{date_stamp}.xlsx"
                ),
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


@web.get("/applications")
def application_history():
    """Render filtered, paginated, read-only application history.

    Returns:
        The history page with normalized name, decision, and page filters plus
        pagination metadata from the repository.
    """
    name_query = request.args.get("q", "").strip()
    requested_decision = request.args.get("decision", "")
    valid_decisions = {decision.value for decision in Decision}
    decision = requested_decision if requested_decision in valid_decisions else ""
    page = _positive_int(request.args.get("page"))
    pagination = ApplicationRepository().list_page(name_query, decision, page)

    return render_template(
        "applications/history.html",
        pagination=pagination,
        name_query=name_query,
        decision=decision,
    )


@web.get("/applications/<int:application_id>")
def application_detail(application_id: int):
    """Render every stored field for one immutable application record.

    Args:
        application_id: The primary key captured from the request URL.

    Returns:
        The application detail page with display labels for coded choices.

    Raises:
        NotFound: If no application exists with the requested identifier.
    """
    application = ApplicationRepository().get(application_id)
    if application is None:
        abort(404)

    return render_template(
        "applications/detail.html",
        application=application,
        education_labels=dict(EDUCATION_CHOICES),
        marital_status_labels=dict(MARITAL_STATUS_CHOICES),
    )
