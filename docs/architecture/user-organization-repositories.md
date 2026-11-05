# User and Organization Repositories

This slice adds database query/staging methods for `auth.users`,
`auth.organizations`, and `auth.organization_members`.

## UserRepository

- `get_by_id(user_id)` (inherited)
- `get_by_firebase_uid(firebase_uid)`
- `get_by_email(email)` (case-insensitive, aligned with `idx_users_email`)
- `add`, `delete`, `flush`, and `refresh` (inherited)

## OrganizationRepository

- `get_by_id(organization_id)` (inherited)
- `list_for_user(user_id)`
- `get_membership(organization_id, user_id)`
- `list_members(organization_id)`
- `add_member(organization_id, user_id, role=...)`
- `remove_member(organization_id, user_id)`
- `change_member_role(organization_id, user_id, role)`

## Transaction and authorization boundaries

Repositories never commit or roll back. The service/request transaction boundary
uses the existing session dependencies. These methods do not decide whether a
caller is authenticated, belongs to an organization, or is allowed to invite,
remove, or change the role of a member. Services must perform those checks.

The database's existing foreign keys, unique constraints, and role check
constraint remain authoritative for referential integrity and valid stored roles.
No schema or live database changes are part of this implementation.
