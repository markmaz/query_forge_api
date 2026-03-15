from flask_mail import Mail
from sqlalchemy import ForeignKey, text as _sa_text
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

mail = Mail()


# ---------------------------------------------------------------------------
# Declarative base for destinations model
# ---------------------------------------------------------------------------

class _DestBase(DeclarativeBase):
    """Declarative base for the workspace_destinations model."""


# ---------------------------------------------------------------------------
# Session factory (lazily initialised to avoid import-time DB connection)
# ---------------------------------------------------------------------------

_scoped_session = None


def _get_db_session():
    global _scoped_session
    if _scoped_session is None:
        from app.adapters.mysql_sql_executor import engine
        _scoped_session = scoped_session(sessionmaker(bind=engine))
    return _scoped_session


# ---------------------------------------------------------------------------
# Minimal db shim compatible with Flask-SQLAlchemy-style usage
# ---------------------------------------------------------------------------

class _DB:
    """
    Provides a Flask-SQLAlchemy-compatible interface over raw SQLAlchemy.
    Used by app/models/destinations.py and app/routes/destination_routes.py.
    """

    Model = _DestBase

    @property
    def session(self):
        return _get_db_session()

    @staticmethod
    def text(sql):
        return _sa_text(sql)

    @staticmethod
    def ForeignKey(*args, **kwargs):
        return ForeignKey(*args, **kwargs)


db = _DB()
