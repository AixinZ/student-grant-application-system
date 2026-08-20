"""Provide the persistence and read-only query boundary for grant applications."""

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import select

from .constants import Decision
from .extensions import db
from .models import Application, make_name_search_key


class ApplicationRepository:
    def create(self, application: Application) -> Application:
        """Persist a new application as a complete database transaction.

        Args:
            application: The populated ORM object to insert.

        Returns:
            The same ORM object after commit, including database-generated
            values such as its identifier.

        Raises:
            Exception: Re-raises any persistence failure after rolling back the
                active SQLAlchemy session.
        """
        try:
            db.session.add(application)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return application

    def get(self, application_id: int) -> Application | None:
        """Retrieve one application by its immutable primary key.

        Args:
            application_id: The numeric application identifier.

        Returns:
            The matching application, or ``None`` when no record exists.
        """
        return db.session.get(Application, application_id)

    def list_page(
        self,
        name_query: str,
        decision: str,
        page: int,
        per_page: int = 20,
    ) -> Pagination:
        """Return a filtered, newest-first page of application history.

        Args:
            name_query: Optional student-name substring to match using the
                normalized search key.
            decision: Optional exact decision value; invalid values are ignored.
            page: The requested one-based page number.
            per_page: Maximum number of applications returned on each page.

        Returns:
            Flask-SQLAlchemy pagination metadata and the selected applications.
            Requests beyond the final page are normalized to page one.
        """
        statement = select(Application)
        normalized_name = name_query.strip()
        if normalized_name and len(normalized_name) <= 100:
            statement = statement.where(
                Application.name_search_key.contains(
                    make_name_search_key(normalized_name), autoescape=True
                )
            )

        try:
            normalized_decision = Decision(decision)
        except (TypeError, ValueError):
            normalized_decision = None
        if normalized_decision is not None:
            statement = statement.where(
                Application.decision == normalized_decision.value
            )

        statement = statement.order_by(
            Application.submitted_at.desc(), Application.id.desc()
        )
        pagination = db.paginate(
            statement, page=page, per_page=per_page, error_out=False
        )
        if page > max(pagination.pages, 1):
            pagination = db.paginate(
                statement, page=1, per_page=per_page, error_out=False
            )
        return pagination
