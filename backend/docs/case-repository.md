# Case Repository

`CaseRepository` provides database access for cases, case memberships, and case
parties using the existing SQLAlchemy models.

## Organization scoping

Case lookup requires both `case_id` and `organization_id`. The repository
overrides the generic `get_by_id` method so callers cannot accidentally perform
an unscoped case lookup through this repository.

Case member and party listing/deletion operations also include the organization
scope. Party records do not store `organization_id`, so party queries join to
the parent case to establish the organization boundary.

## Transaction ownership

Repository methods stage inserts, updates, and deletes in the supplied
`AsyncSession`. They never call `commit()` or `rollback()`. The service or
request transaction boundary owns commit/rollback.

## Authorization boundary

Organization-scoped queries prevent accidental cross-organization retrieval,
but they do not establish that the current user is authorized. Services must
authenticate the actor, verify organization membership and role, and authorize
the requested action before invoking mutations or returning protected data.

## Current operations

- Retrieve a case by `(case_id, organization_id)`.
- List cases in an organization, optionally filtered by status.
- List, retrieve, add, remove, and change roles for case members.
- List and add case parties.
- Delete a party scoped through its parent case and organization.

No database schema or live Cloud SQL data is changed by this implementation.
