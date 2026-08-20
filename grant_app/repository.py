"""Provide the persistence and read-only query boundary for grant applications."""

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import select

from .constants import Decision
from .extensions import db
from .models import Application, make_name_search_key


class ApplicationRepository:
    def create(self, application: Application) -> Application:
        try:
            db.session.add(application)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return application

    def get(self, application_id: int) -> Application | None:
        return db.session.get(Application, application_id)

    def list_page(
        self,
        name_query: str,
        decision: str,
        page: int,
        per_page: int = 20,
    ) -> Pagination:
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
