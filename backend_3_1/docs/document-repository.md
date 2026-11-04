# Document Repository

`DocumentRepository` provides organization-scoped database operations for
`documents.documents` and its `documents.document_versions` rows.

## Security and ownership boundaries

- Document retrieval always requires both `document_id` and `organization_id`.
- Case listings always constrain both `case_id` and `organization_id`.
- Version retrieval and history always constrain both `document_id` and
  `organization_id`; individual version lookup also requires `version_id`.
- Repository scoping is a data-access safeguard, not an authorization decision.
  Services must authenticate the caller and authorize access before invoking
  writes or returning protected records.
- The repository never commits or rolls back. The service/request transaction
  boundary owns commit and rollback.

## Document operations

- `get_by_id` / `get_by_id_and_organization`
- `list_by_case`
- `create_document`
- `update_details`
- `set_status`
- `soft_delete`

`soft_delete` changes the database status to `deleted`. It does not remove the
database row or delete any Google Cloud Storage object.

## Version operations

- `list_versions`
- `get_version`
- `get_latest_version`
- `add_version`

The service supplies `version_number`. The unique database constraint on
`(document_id, version_number)` is the final protection against concurrent
duplicate version numbers. The repository records GCS bucket/object metadata;
it does not upload, download, or delete objects.

## Validation

`list_by_case` accepts page sizes from 1 through 200 and non-negative offsets.
`add_version` rejects non-positive version numbers and file sizes before
staging an ORM object. Remaining constraints are enforced by PostgreSQL.
