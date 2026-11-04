# Database repository and transaction conventions

## Current scope

This milestone slice adds the shared `BaseRepository` foundation and an explicit
request-scoped transaction dependency. It does not yet add domain-specific
repositories for users, organizations, cases, or documents.

## Repository responsibilities

- Repositories receive an `AsyncSession`; they never create or close sessions.
- Repositories may query, add, delete, flush, and refresh mapped entities.
- Repository methods must not call `commit()` or `rollback()`.
- Tenant-owned repository methods must require an `organization_id` and include it
  in the SQL predicate. A UUID alone is not sufficient authorization scope.
- Repositories do not decide whether a caller is authorized. Authorization belongs
  in the service layer and must be enforced before data is returned or mutated.

`BaseRepository` is intentionally small. Concrete repositories should expose
purpose-specific methods rather than turning the base class into an unrestricted
CRUD API.

## Session and transaction responsibilities

`get_db_session` provides a session but does not implicitly commit. Use it when a
service explicitly owns its transaction boundary. Uncommitted changes are rolled
back when the session closes.

`get_transactional_db_session` wraps the request in one transaction:

- Normal completion commits.
- An exception rolls back.
- Endpoints/services using this dependency must not start another top-level
  `session.begin()` block.

Choose one transaction owner per operation. Do not mix both dependencies for the
same request.

## Safety constraints

- Never commit inside a repository method.
- Never fetch organization-owned records by object ID alone.
- Do not expose raw SQL construction or arbitrary filters to API callers.
- Keep the existing composite foreign keys and organization scoping intact.
- No schema DDL or live database migration is part of this work.
