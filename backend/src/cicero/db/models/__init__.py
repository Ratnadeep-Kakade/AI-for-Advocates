"""SQLAlchemy mappings for the existing Cicero PostgreSQL schema.

Importing this package registers all mapped tables on ``Base.metadata``.
These mappings describe existing tables; they do not create or alter them.
"""

from cicero.db.models.auth import Organization, OrganizationMember, User
from cicero.db.models.cases import Case, CaseMember, CaseParty
from cicero.db.models.documents import (
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentProcessingRun,
    DocumentVersion,
)

__all__ = [
    "Case",
    "CaseMember",
    "CaseParty",
    "Document",
    "DocumentChunk",
    "DocumentExtraction",
    "DocumentProcessingRun",
    "DocumentVersion",
    "Organization",
    "OrganizationMember",
    "User",
]
