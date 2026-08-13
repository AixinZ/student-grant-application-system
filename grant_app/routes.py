from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy.exc import SQLAlchemyError

from .approval import ApprovalEngineError
from .constants import Decision, EDUCATION_CHOICES, MARITAL_STATUS_CHOICES
from .forms import StudentApplicationForm
from .repository import ApplicationRepository
from .services import create_application


web = Blueprint("web", __name__)

RETRY_MESSAGE = "We could not process the application right now. Please try again."
MAX_HISTORY_PAGE = (2**63 - 1) // 20 + 1


def _positive_int(value: str | None) -> int:
    try:
        parsed = int(value) if value is not None else 1
    except ValueError:
        return 1
    return parsed if 0 < parsed <= MAX_HISTORY_PAGE else 1


@web.get("/")
def index():
    return redirect(url_for("web.application_new"))


@web.route("/applications/new", methods=["GET", "POST"])
def application_new():
    form = StudentApplicationForm()
    if form.validate_on_submit():
        try:
            application = create_application(
                form.to_domain(), current_app.config["APPROVAL_ENGINE"]
            )
        except ApprovalEngineError:
            current_app.logger.error("application_approval_failed")
            flash(RETRY_MESSAGE, "error")
            return render_template("applications/new.html", form=form), 503
        except SQLAlchemyError:
            current_app.logger.error("application_persistence_failed")
            flash(RETRY_MESSAGE, "error")
            return render_template("applications/new.html", form=form), 503

        return redirect(
            url_for("web.application_detail", application_id=application.id)
        )

    status = 422 if request.method == "POST" else 200
    return render_template("applications/new.html", form=form), status


@web.get("/applications")
def application_history():
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
    application = ApplicationRepository().get(application_id)
    if application is None:
        abort(404)

    return render_template(
        "applications/detail.html",
        application=application,
        education_labels=dict(EDUCATION_CHOICES),
        marital_status_labels=dict(MARITAL_STATUS_CHOICES),
    )
