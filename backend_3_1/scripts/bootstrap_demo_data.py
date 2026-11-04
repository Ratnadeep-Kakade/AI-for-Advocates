from __future__ import annotations

import json

import modal

app = modal.App("cicero-backend")

DATABASE_SECRET = modal.Secret.from_name(
    "cicero-database",
    required_keys=[
        "CICERO_DATABASE_INSTANCE_CONNECTION_NAME",
        "CICERO_DATABASE_NAME",
        "CICERO_DATABASE_USER",
        "CICERO_DATABASE_PASSWORD",
        "CICERO_DATABASE_WIF_PROJECT_NUMBER",
        "CICERO_DATABASE_WIF_POOL_ID",
        "CICERO_DATABASE_WIF_PROVIDER_ID",
        "CICERO_DATABASE_WIF_SERVICE_ACCOUNT_EMAIL",
    ],
)

IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "asyncpg>=0.30,<1.0",
        "cloud-sql-python-connector[asyncpg]>=1.18,<2.0",
        "google-auth>=2.35,<3.0",
        "pydantic-settings>=2.6,<3.0",
        "sqlalchemy[asyncio]>=2.0.36,<3.0",
    )
    .add_local_python_source("cicero")
)


@app.function(
    image=IMAGE,
    secrets=[DATABASE_SECRET],
    name="fastapi_app",
    timeout=180,
)
async def bootstrap_demo_data() -> dict[str, str]:
    """Create the synthetic demo tenant, organization membership and Zepto case.

    This is an explicit one-off bootstrap utility, not an authentication system.
    Repeated runs reuse the same seeded records.
    """
    from sqlalchemy import select

    from cicero.config import get_settings
    from cicero.db.connection import DatabaseManager
    from cicero.db.models.auth import Organization, User
    from cicero.db.models.cases import Case
    from cicero.db.repositories.case import CaseRepository
    from cicero.db.repositories.organization import OrganizationRepository
    from cicero.db.repositories.user import UserRepository

    demo_firebase_uid = "demo-cicero-hackathon-user-v1"
    demo_email = "demo.user@cicero.example"
    demo_user_name = "Cicero Demo User"
    demo_organization_name = "Cicero Demo Law Firm"
    demo_case_name = "Zepto IPO Due Diligence"

    manager = DatabaseManager(get_settings())
    try:
        await manager.start()
        if manager.session_factory is None:
            raise RuntimeError("Cloud SQL session factory was not initialized.")

        async with manager.session_factory() as session:
            async with session.begin():
                users = UserRepository(session)
                organizations = OrganizationRepository(session)
                cases = CaseRepository(session)

                user = await users.get_by_firebase_uid(demo_firebase_uid)
                if user is None:
                    email_owner = await users.get_by_email(demo_email)
                    if email_owner is not None:
                        raise RuntimeError(
                            "The demo email already belongs to a different Firebase UID. "
                            "Refusing to attach the demo tenant to that account."
                        )
                    user = users.add(
                        User(
                            firebase_uid=demo_firebase_uid,
                            name=demo_user_name,
                            email=demo_email,
                            email_verified=True,
                            account_status="active",
                        )
                    )
                    await users.flush()
                else:
                    user.name = demo_user_name
                    user.account_status = "active"

                organization_statement = (
                    select(Organization)
                    .where(
                        Organization.organization_name == demo_organization_name,
                        Organization.created_by == user.user_id,
                    )
                    .order_by(Organization.created_at, Organization.organization_id)
                    .limit(1)
                )
                organization_result = await session.execute(organization_statement)
                organization = organization_result.scalar_one_or_none()
                if organization is None:
                    organization = Organization(
                        organization_name=demo_organization_name,
                        organization_type="law_firm",
                        created_by=user.user_id,
                    )
                    session.add(organization)
                    await session.flush()

                organization_membership = await organizations.get_membership(
                    organization.organization_id,
                    user.user_id,
                )
                if organization_membership is None:
                    organizations.add_member(
                        organization.organization_id,
                        user.user_id,
                        role="owner",
                    )
                elif organization_membership.role != "owner":
                    organization_membership.role = "owner"

                # Ensure the organization membership exists before inserting the
                # case membership, whose composite foreign key depends on it.
                await session.flush()

                case_statement = (
                    select(Case)
                    .where(
                        Case.organization_id == organization.organization_id,
                        Case.case_name == demo_case_name,
                    )
                    .order_by(Case.created_at, Case.case_id)
                    .limit(1)
                )
                case_result = await session.execute(case_statement)
                case = case_result.scalar_one_or_none()
                if case is None:
                    case = Case(
                        organization_id=organization.organization_id,
                        case_name=demo_case_name,
                        case_description=(
                            "Corporate legal due diligence review of Zepto's Updated Draft "
                            "Red Herring Prospectus (UDRHP), focusing on disclosed risk "
                            "factors, business and financial disclosures, corporate "
                            "governance, related-party transactions, material proceedings "
                            "and regulatory disclosures. Findings must be grounded in the "
                            "UDRHP and distinguish issuer disclosures from independently "
                            "verified facts."
                        ),
                        jurisdiction="India",
                        case_type="corporate_ipo_due_diligence",
                        status="active",
                        created_by=user.user_id,
                    )
                    session.add(case)
                    await session.flush()

                case_membership = await cases.get_member(
                    case.case_id,
                    organization.organization_id,
                    user.user_id,
                )
                if case_membership is None:
                    cases.add_member(
                        case.case_id,
                        organization.organization_id,
                        user.user_id,
                        role="owner",
                    )
                elif case_membership.role != "owner":
                    case_membership.role = "owner"

                await session.flush()

                result = {
                    "status": "SUCCESS",
                    "user_id": str(user.user_id),
                    "organization_id": str(organization.organization_id),
                    "case_id": str(case.case_id),
                    "user_email": user.email,
                    "organization_name": organization.organization_name,
                    "case_name": case.case_name,
                    "idempotent": "true",
                }

        print("CICERO DEMO BOOTSTRAP:", json.dumps(result, indent=2), flush=True)
        return result
    finally:
        await manager.close()


@app.local_entrypoint()
def main() -> None:
    result = bootstrap_demo_data.remote()
    print("\n===== CICERO DEMO DATA =====")
    print(json.dumps(result, indent=2))
