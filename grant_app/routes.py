"""Handle application entry, history, detail pages, and CSV scoring APIs."""

import time
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy.exc import SQLAlchemyError

from .approval import ApprovalEngineError
from .constants import Decision, EDUCATION_CHOICES, MARITAL_STATUS_CHOICES
from .diagnostics import log_exception_context
from .forms import StudentApplicationForm
from .repository import ApplicationRepository
from .services import create_application
from .csv_scoring.errors import (
    CsvValidationError,
    JobNotFoundError,
    ModelUnavailableError,
    UploadNotFoundError,
)
from .csv_scoring.parser import parse_upload, validate_selected_headers
from .csv_scoring.scorer import score_job


web = Blueprint("web", __name__)

RETRY_MESSAGE = "We could not process the application right now. Please try again."
MAX_HISTORY_PAGE = (2**63 - 1) // 20 + 1


def _csv_error(code: str, status: int = 400):
    """Return one fixed CSV-scoring error without request data."""
    return jsonify(error=code), status


def _csv_store():
    return current_app.config["CSV_SCORING_STORE"]


def _cleanup_csv_scoring() -> None:
    """Remove expired private scoring files without making requests fail."""
    try:
        _csv_store().cleanup_expired(time.time())
    except Exception as error:
        log_exception_context(current_app.logger, "csv_scoring_cleanup_failed", error)


def _upload_payload(upload) -> dict[str, object]:
    return {
        "upload_id": upload.upload_id,
        "fields": list(upload.headers),
        "row_count": upload.row_count,
        "size_bytes": upload.size_bytes,
    }


def _job_payload(job) -> dict[str, object]:
    payload: dict[str, object] = {
        "job_id": job.job_id,
        "status": job.status,
        "progress_rows": job.progress_rows,
    }
    if job.status == "failed":
        payload["error"] = job.error_code or "processing_failed"
    return payload


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


@web.get("/csv-scoring")
def csv_scoring_new():
    """Render the browser workflow for one server-side CSV scoring job."""
    return render_template(
        "csv_scoring/new.html",
        models=current_app.config["CSV_SCORING_MODEL_REGISTRY"].list_available(),
    )


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


@web.post("/csv-scoring/uploads")
def csv_scoring_upload():
    """Validate and retain one private CSV upload, returning only metadata."""
    _cleanup_csv_scoring()
    uploaded = request.files.get("file")
    if uploaded is None:
        return _csv_error("invalid_csv")
    store = _csv_store()
    try:
        parsed = parse_upload(
            uploaded.stream,
            store.root,
            upload_id=store.new_upload_id(),
            max_bytes=current_app.config["CSV_SCORING_MAX_BYTES"],
            min_rows=current_app.config["CSV_SCORING_MIN_ROWS"],
            max_rows=current_app.config["CSV_SCORING_MAX_ROWS"],
        )
        store.save_upload(parsed)
        return jsonify(_upload_payload(store.get_upload(parsed.upload_id))), 201
    except CsvValidationError:
        return _csv_error("invalid_csv")


@web.get("/csv-scoring/uploads/<upload_id>")
def csv_scoring_upload_metadata(upload_id: str):
    """Return safe metadata for a live private CSV upload."""
    _cleanup_csv_scoring()
    try:
        return jsonify(_upload_payload(_csv_store().get_upload(upload_id)))
    except UploadNotFoundError:
        return _csv_error("not_found", 404)


@web.post("/csv-scoring/jobs")
def csv_scoring_create_job():
    """Create and queue scoring work using one registered server-side model."""
    _cleanup_csv_scoring()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _csv_error("invalid_job")
    upload_id = payload.get("upload_id")
    selected_fields = payload.get("selected_fields")
    model_id = payload.get("model_id")
    if (
        not isinstance(upload_id, str)
        or not isinstance(model_id, str)
        or not isinstance(selected_fields, list)
        or any(not isinstance(field, str) for field in selected_fields)
    ):
        return _csv_error("invalid_job")

    store = _csv_store()
    try:
        upload = store.get_upload(upload_id)
    except UploadNotFoundError:
        return _csv_error("not_found", 404)
    try:
        selected_headers = validate_selected_headers(upload.headers, selected_fields)
    except CsvValidationError:
        return _csv_error("invalid_job")
    try:
        model = current_app.config["CSV_SCORING_MODEL_REGISTRY"].get(model_id)
    except ModelUnavailableError:
        return _csv_error("model_unavailable")
    if not model.matches_headers(upload.headers):
        return _csv_error("missing_model_columns")

    try:
        job = store.create_job(upload.upload_id, model.model_id, selected_headers, time.time())
    except (UploadNotFoundError, JobNotFoundError):
        return _csv_error("not_found", 404)

    chunk_size = current_app.config["CSV_SCORING_CHUNK_SIZE"]

    def work() -> None:
        score_job(
            upload.source_path,
            store.result_path(job.job_id),
            selected_headers=selected_headers,
            model=model,
            chunk_size=chunk_size,
            progress=lambda rows: store.update_job(
                job.job_id, status="running", progress_rows=rows
            ),
        )

    try:
        current_app.config["CSV_SCORING_TASK_EXECUTOR"].submit(job.job_id, work)
    except Exception as error:
        log_exception_context(current_app.logger, "csv_scoring_submit_failed", error)
        try:
            store.update_job(
                job.job_id, status="failed", progress_rows=0,
                error_code="processing_failed",
            )
        except Exception as cleanup_error:
            log_exception_context(
                current_app.logger, "csv_scoring_submit_cleanup_failed", cleanup_error
            )
        return _csv_error("processing_failed", 500)
    return jsonify(_job_payload(job)), 202


@web.get("/csv-scoring/jobs/<job_id>")
def csv_scoring_job_status(job_id: str):
    """Report only the safe state and progress of one scoring job."""
    _cleanup_csv_scoring()
    try:
        return jsonify(_job_payload(_csv_store().get_job(job_id)))
    except JobNotFoundError:
        return _csv_error("not_found", 404)


@web.get("/csv-scoring/jobs/<job_id>/download")
def csv_scoring_download(job_id: str):
    """Download a completed atomic CSV result with a server-generated name."""
    _cleanup_csv_scoring()
    store = _csv_store()
    try:
        job = store.get_job(job_id)
    except JobNotFoundError:
        return _csv_error("not_found", 404)
    if job.status != "completed":
        return _csv_error("result_not_ready")
    result_path = store.result_path(job.job_id)
    if not Path(result_path).is_file():
        return _csv_error("result_not_ready")
    return send_file(
        result_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"scored_{job.job_id}.csv",
        conditional=True,
    )
