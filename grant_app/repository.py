from .extensions import db
from .models import Application


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
