from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from cicero.persistence.base import Base


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"],
            ["auth.organizations.organization_id"],
            name="cases_organization_id_fkey",
        ),
        ForeignKeyConstraint(
            ["created_by"],
            ["auth.users.user_id"],
            name="cases_created_by_fkey",
        ),
        UniqueConstraint("case_id", "organization_id", name="cases_case_id_organization_id_key"),
        CheckConstraint(
            "status = ANY (ARRAY['active'::text, 'archived'::text, 'closed'::text])",
            name="cases_status_check",
        ),
        Index("idx_cases_organization", "organization_id"),
        Index("idx_cases_status", "status"),
        {"schema": "cases"},
    )

    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    case_name: Mapped[str] = mapped_column(Text, nullable=False)
    case_description: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    court: Mapped[str | None] = mapped_column(Text)
    case_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CaseMember(Base):
    __tablename__ = "case_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["cases.cases.case_id", "cases.cases.organization_id"],
            name="case_members_case_id_organization_id_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["auth.organization_members.organization_id", "auth.organization_members.user_id"],
            name="case_members_organization_id_user_id_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "role = ANY (ARRAY['owner'::text, 'editor'::text, 'viewer'::text])",
            name="case_members_role_check",
        ),
        Index("idx_case_members_user", "user_id"),
        {"schema": "cases"},
    )

    case_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'viewer'"))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CaseParty(Base):
    __tablename__ = "case_parties"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id"],
            ["cases.cases.case_id"],
            name="case_parties_case_id_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "party_position = ANY (ARRAY['claimant'::text, 'defendant'::text, "
            "'plaintiff'::text, 'respondent'::text, 'petitioner'::text, "
            "'opposite_party'::text, 'other'::text])",
            name="case_parties_party_position_check",
        ),
        CheckConstraint(
            "party_type = ANY (ARRAY['individual'::text, 'company'::text, "
            "'government'::text, 'other'::text])",
            name="case_parties_party_type_check",
        ),
        Index("idx_case_parties_case", "case_id"),
        {"schema": "cases"},
    )

    party_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    case_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    party_name: Mapped[str] = mapped_column(Text, nullable=False)
    party_type: Mapped[str] = mapped_column(Text, nullable=False)
    party_position: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
