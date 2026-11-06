"""SQLAlchemy mappings for the existing Cicero PostgreSQL schema.

Importing this package registers all mapped tables on ``Base.metadata``.
These mappings describe existing tables; they do not create or alter them.
"""

from cicero.persistence.models.agents import (
    AgentResultRecord,
    ExecutionRecord,
    ExecutionTaskRecord,
)
from cicero.persistence.models.auth import Organization, OrganizationMember, User
from cicero.persistence.models.cases import Case, CaseMember, CaseParty
from cicero.persistence.models.documents import (
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentProcessingRun,
    DocumentVersion,
)

__all__ = [
    "AgentResultRecord",
    "Case",
    "CaseMember",
    "CaseParty",
    "Document",
    "DocumentChunk",
    "DocumentExtraction",
    "DocumentProcessingRun",
    "DocumentVersion",
    "ExecutionRecord",
    "ExecutionTaskRecord",
    "Organization",
    "OrganizationMember",
    "User",
]
