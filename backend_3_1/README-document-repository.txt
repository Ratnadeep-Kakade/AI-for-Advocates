Cicero Milestone 3.2.3: DocumentRepository patch

Merge the archive contents into the root of your existing backend_3_1 directory.
Preserve the paths. This patch adds document.py, adds its export to the existing
repositories package, adds tests, and adds documentation.

No database migration or live database operation is included.

Run:
    uv run pytest

The full suite should now contain 54 tests if the previous 44 tests are unchanged.
