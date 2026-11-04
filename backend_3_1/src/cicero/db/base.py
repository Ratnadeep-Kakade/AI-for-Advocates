from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for Cicero's SQLAlchemy mappings.

    The existing Cloud SQL tables are mapped explicitly in ``db.models``.
    Importing metadata does not create or modify database tables.
    """
