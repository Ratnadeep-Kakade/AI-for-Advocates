from __future__ import annotations

from sqlalchemy.dialects import postgresql

import cicero.db.models  # noqa: F401 - registers all mapped tables
from cicero.db.base import Base
from cicero.db.schema_parity import (
    CICERO_SCHEMAS,
    _normalize_sql,
    build_schema_parity_report,
)


class MetadataBackedInspector:
    """Small Inspector-shaped test double derived from ORM metadata."""

    def __init__(self, metadata, *, missing_column: tuple[str, str, str] | None = None):
        self.metadata = metadata
        self.missing_column = missing_column

    def get_schema_names(self):
        return sorted(CICERO_SCHEMAS)

    def get_table_names(self, schema=None):
        return sorted(
            table.name for table in self.metadata.tables.values() if table.schema == schema
        )

    def _table(self, table_name, schema):
        return self.metadata.tables[f"{schema}.{table_name}"]

    def get_columns(self, table_name, schema=None):
        table = self._table(table_name, schema)
        result = []
        for column in table.columns:
            if self.missing_column == (schema, table_name, column.name):
                continue
            default = None
            if column.server_default is not None:
                default = str(column.server_default.arg)
            result.append(
                {
                    "name": column.name,
                    "type": column.type,
                    "nullable": column.nullable,
                    "default": default,
                }
            )
        return result

    def get_pk_constraint(self, table_name, schema=None):
        table = self._table(table_name, schema)
        return {"constrained_columns": [column.name for column in table.primary_key.columns]}

    def get_foreign_keys(self, table_name, schema=None):
        table = self._table(table_name, schema)
        result = []
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            remote_table = elements[0].column.table
            result.append(
                {
                    "name": constraint.name,
                    "constrained_columns": [element.parent.name for element in elements],
                    "referred_schema": remote_table.schema,
                    "referred_table": remote_table.name,
                    "referred_columns": [element.column.name for element in elements],
                    "options": {"ondelete": constraint.ondelete} if constraint.ondelete else {},
                }
            )
        return result

    def get_unique_constraints(self, table_name, schema=None):
        table = self._table(table_name, schema)
        return [
            {
                "name": constraint.name,
                "column_names": [column.name for column in constraint.columns],
            }
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]

    def get_check_constraints(self, table_name, schema=None):
        table = self._table(table_name, schema)
        return [
            {"name": constraint.name, "sqltext": str(constraint.sqltext)}
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        ]

    def get_indexes(self, table_name, schema=None):
        table = self._table(table_name, schema)
        dialect = postgresql.dialect()
        result = []
        for index in table.indexes:
            column_names = []
            expressions = []
            for expression in index.expressions:
                if (
                    getattr(expression, "name", None)
                    and getattr(expression, "table", None) is not None
                ):
                    column_names.append(expression.name)
                else:
                    expressions.append(str(expression.compile(dialect=dialect)))
            where = index.dialect_options["postgresql"].get("where")
            result.append(
                {
                    "name": index.name,
                    "unique": index.unique,
                    "column_names": column_names,
                    "expressions": expressions,
                    "dialect_options": {"postgresql_where": where} if where is not None else {},
                }
            )
        return result


class FakeConnection:
    dialect = postgresql.dialect()

    def __init__(self, inspector):
        self._inspector = inspector


def test_normalize_sql_ignores_postgres_text_cast_and_formatting() -> None:
    assert _normalize_sql("'active'::text") == _normalize_sql(" 'active' ")
    assert _normalize_sql("(now())") == _normalize_sql("now()")


def test_schema_parity_passes_against_metadata_backed_inspector(monkeypatch) -> None:
    inspector = MetadataBackedInspector(Base.metadata)
    monkeypatch.setattr("cicero.db.schema_parity.inspect", lambda connection: inspector)

    report = build_schema_parity_report(FakeConnection(inspector))  # type: ignore[arg-type]

    assert report["status"] == "PASS"
    assert report["summary"]["schemas_checked"] == 8
    assert report["summary"]["tables_expected"] == 14
    assert report["summary"]["tables_compared"] == 14
    assert report["issues"] == []
    assert report["read_only"] is True


def test_schema_parity_reports_missing_column(monkeypatch) -> None:
    inspector = MetadataBackedInspector(
        Base.metadata,
        missing_column=("documents", "document_chunks", "content"),
    )
    monkeypatch.setattr("cicero.db.schema_parity.inspect", lambda connection: inspector)

    report = build_schema_parity_report(FakeConnection(inspector))  # type: ignore[arg-type]

    assert report["status"] == "FAIL"
    assert any(
        issue["category"] == "missing_column"
        and issue["scope"] == "documents.document_chunks"
        and issue["object"] == "content"
        for issue in report["issues"]
    )


def test_checker_targets_only_the_eight_cicero_schemas() -> None:
    assert CICERO_SCHEMAS == {
        "auth",
        "cases",
        "documents",
        "intelligence",
        "research",
        "agents",
        "evidence",
        "memory",
    }
