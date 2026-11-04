from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, MetaData, inspect
from sqlalchemy.schema import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

# Importing the package registers all ORM models on Base.metadata.
import cicero.db.models  # noqa: F401
from cicero.db.base import Base


def test_all_existing_models_are_registered():
    expected = {
        "auth.users",
        "auth.organizations",
        "auth.organization_members",
        "cases.cases",
        "cases.case_members",
        "cases.case_parties",
        "documents.documents",
        "documents.document_versions",
        "documents.document_processing_runs",
        "documents.document_extractions",
        "documents.document_chunks",
    }
    assert set(Base.metadata.tables.keys()) == expected


CICERO_SCHEMAS = frozenset(
    {
        "auth",
        "cases",
        "documents",
        "intelligence",
        "research",
        "agents",
        "evidence",
        "memory",
    }
)


def _normalize_sql(value: str | None) -> str | None:
    """Normalize harmless PostgreSQL formatting/casts for structural comparisons."""
    if value is None:
        return None
    normalized = value.strip().lower()
    normalized = re.sub(
        r"::(?:text|character varying|varchar|character|char|boolean|integer|bigint|smallint)\b",
        "",
        normalized,
    )
    normalized = re.sub(r"\s+", "", normalized)
    # PostgreSQL may wrap an otherwise identical default in outer parentheses.
    while normalized.startswith("(") and normalized.endswith(")"):
        depth = 0
        encloses_all = True
        for index, char in enumerate(normalized):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(normalized) - 1:
                    encloses_all = False
                    break
        if not encloses_all or depth != 0:
            break
        normalized = normalized[1:-1]
    return normalized


def _compile_type(type_: Any, dialect: Any) -> str:
    return str(type_.compile(dialect=dialect)).upper()


def _compile_sql_expression(expression: Any, dialect: Any) -> str:
    if hasattr(expression, "compile"):
        return str(expression.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    return str(expression)


def _expected_default(column: Any, dialect: Any) -> str | None:
    if column.server_default is None:
        return None
    return _compile_sql_expression(column.server_default.arg, dialect)


def _actual_fk_signature(foreign_key: dict[str, Any], local_schema: str) -> tuple[Any, ...]:
    options = foreign_key.get("options") or {}
    return (
        foreign_key.get("name"),
        tuple(foreign_key.get("constrained_columns") or ()),
        foreign_key.get("referred_schema") or local_schema,
        foreign_key.get("referred_table"),
        tuple(foreign_key.get("referred_columns") or ()),
        (options.get("ondelete") or "").upper(),
    )


def _expected_fk_signature(constraint: ForeignKeyConstraint) -> tuple[Any, ...]:
    elements = list(constraint.elements)
    if not elements:
        return (constraint.name, (), None, None, (), (constraint.ondelete or "").upper())
    remote_table = elements[0].column.table
    return (
        constraint.name,
        tuple(element.parent.name for element in elements),
        remote_table.schema,
        remote_table.name,
        tuple(element.column.name for element in elements),
        (constraint.ondelete or "").upper(),
    )


def _expected_index_signature(index: Index, dialect: Any) -> tuple[Any, ...]:
    columns: list[str] = []
    expressions: list[str] = []
    for expression in index.expressions:
        if getattr(expression, "name", None) and getattr(expression, "table", None) is not None:
            columns.append(expression.name)
        else:
            expressions.append(_normalize_sql(_compile_sql_expression(expression, dialect)) or "")
    where = index.dialect_options["postgresql"].get("where")
    where_sql = (
        _normalize_sql(_compile_sql_expression(where, dialect)) if where is not None else None
    )
    return (index.name, bool(index.unique), tuple(columns), tuple(expressions), where_sql)


def _actual_index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    dialect_options = index.get("dialect_options") or {}
    where = dialect_options.get("postgresql_where")
    expressions = index.get("expressions") or []
    return (
        index.get("name"),
        bool(index.get("unique")),
        tuple(column for column in (index.get("column_names") or []) if column is not None),
        tuple(_normalize_sql(expression) or "" for expression in expressions),
        _normalize_sql(str(where)) if where is not None else None,
    )


def _sorted_signatures(values: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return sorted(values, key=lambda value: repr(value))


def build_schema_parity_report(
    connection: Connection,
    *,
    metadata: MetaData = Base.metadata,
    target_schemas: Iterable[str] = CICERO_SCHEMAS,
) -> dict[str, Any]:
    """Compare live PostgreSQL structure with ORM metadata without issuing DDL.

    The caller is responsible for opening a read-only transaction. This function
    only uses SQLAlchemy inspection/reflection methods (catalog SELECTs).
    """
    inspector = inspect(connection)
    dialect = connection.dialect
    schemas = sorted(set(target_schemas))
    actual_schemas = set(inspector.get_schema_names())
    expected_tables_by_schema: dict[str, dict[str, Any]] = {schema: {} for schema in schemas}

    for table in metadata.tables.values():
        if table.schema in expected_tables_by_schema:
            expected_tables_by_schema[table.schema][table.name] = table

    issues: list[dict[str, Any]] = []
    table_reports: list[dict[str, Any]] = []

    def issue(scope: str, category: str, object_name: str, expected: Any, actual: Any) -> None:
        issues.append(
            {
                "scope": scope,
                "category": category,
                "object": object_name,
                "expected": expected,
                "actual": actual,
            }
        )

    for schema in schemas:
        if schema not in actual_schemas:
            issue("schema", "missing_schema", schema, "present", "missing")
            continue

        actual_table_names = set(inspector.get_table_names(schema=schema))
        expected_tables = expected_tables_by_schema[schema]
        for table_name in sorted(set(expected_tables) - actual_table_names):
            issue(schema, "missing_table", table_name, "present", "missing")
        for table_name in sorted(actual_table_names - set(expected_tables)):
            issue(schema, "unexpected_table", table_name, "not mapped", "present")

        for table_name in sorted(set(expected_tables) & actual_table_names):
            table = expected_tables[table_name]
            scope = f"{schema}.{table_name}"
            table_issue_start = len(issues)

            actual_columns_list = inspector.get_columns(table_name, schema=schema)
            actual_columns = {column["name"]: column for column in actual_columns_list}
            expected_columns = {column.name: column for column in table.columns}

            for column_name in sorted(set(expected_columns) - set(actual_columns)):
                issue(scope, "missing_column", column_name, "present", "missing")
            for column_name in sorted(set(actual_columns) - set(expected_columns)):
                issue(scope, "unexpected_column", column_name, "not mapped", "present")

            for column_name in sorted(set(expected_columns) & set(actual_columns)):
                expected_column = expected_columns[column_name]
                actual_column = actual_columns[column_name]
                expected_type = _compile_type(expected_column.type, dialect)
                actual_type = _compile_type(actual_column["type"], dialect)
                if expected_type != actual_type:
                    issue(scope, "column_type_mismatch", column_name, expected_type, actual_type)
                if bool(expected_column.nullable) != bool(actual_column["nullable"]):
                    issue(
                        scope,
                        "column_nullability_mismatch",
                        column_name,
                        bool(expected_column.nullable),
                        bool(actual_column["nullable"]),
                    )
                expected_default = _normalize_sql(_expected_default(expected_column, dialect))
                actual_default = _normalize_sql(actual_column.get("default"))
                if expected_default != actual_default:
                    issue(
                        scope,
                        "column_server_default_mismatch",
                        column_name,
                        expected_default,
                        actual_default,
                    )

            actual_pk = inspector.get_pk_constraint(table_name, schema=schema)
            expected_pk_columns = tuple(column.name for column in table.primary_key.columns)
            actual_pk_columns = tuple(actual_pk.get("constrained_columns") or ())
            if expected_pk_columns != actual_pk_columns:
                issue(
                    scope,
                    "primary_key_mismatch",
                    "primary_key",
                    expected_pk_columns,
                    actual_pk_columns,
                )

            expected_fks = _sorted_signatures(
                _expected_fk_signature(constraint) for constraint in table.foreign_key_constraints
            )
            actual_fks = _sorted_signatures(
                _actual_fk_signature(foreign_key, schema)
                for foreign_key in inspector.get_foreign_keys(table_name, schema=schema)
            )
            if expected_fks != actual_fks:
                issue(scope, "foreign_key_mismatch", "foreign_keys", expected_fks, actual_fks)

            expected_uniques = _sorted_signatures(
                (constraint.name, tuple(column.name for column in constraint.columns))
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            )
            actual_uniques = _sorted_signatures(
                (constraint.get("name"), tuple(constraint.get("column_names") or ()))
                for constraint in inspector.get_unique_constraints(table_name, schema=schema)
            )
            if expected_uniques != actual_uniques:
                issue(
                    scope,
                    "unique_constraint_mismatch",
                    "unique_constraints",
                    expected_uniques,
                    actual_uniques,
                )

            expected_checks = _sorted_signatures(
                (
                    constraint.name,
                    _normalize_sql(_compile_sql_expression(constraint.sqltext, dialect)),
                )
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
            )
            actual_checks = _sorted_signatures(
                (constraint.get("name"), _normalize_sql(constraint.get("sqltext")))
                for constraint in inspector.get_check_constraints(table_name, schema=schema)
            )
            if expected_checks != actual_checks:
                issue(
                    scope,
                    "check_constraint_mismatch",
                    "check_constraints",
                    expected_checks,
                    actual_checks,
                )

            expected_indexes = _sorted_signatures(
                _expected_index_signature(index, dialect) for index in table.indexes
            )
            actual_indexes = _sorted_signatures(
                _actual_index_signature(index)
                for index in inspector.get_indexes(table_name, schema=schema)
                if not index.get("duplicates_constraint")
            )
            if expected_indexes != actual_indexes:
                issue(scope, "index_mismatch", "indexes", expected_indexes, actual_indexes)

            table_issues = issues[table_issue_start:]
            table_reports.append(
                {
                    "schema": schema,
                    "table": table_name,
                    "status": "FAIL" if table_issues else "PASS",
                    "issue_count": len(table_issues),
                }
            )

    summary = {
        "schemas_checked": len(schemas),
        "schemas_found": sum(schema in actual_schemas for schema in schemas),
        "tables_expected": sum(len(tables) for tables in expected_tables_by_schema.values()),
        "tables_compared": len(table_reports),
        "tables_with_drift": sum(report["status"] == "FAIL" for report in table_reports),
        "issue_count": len(issues),
    }
    return {
        "status": "PASS" if not issues else "FAIL",
        "summary": summary,
        "schemas": schemas,
        "tables": table_reports,
        "issues": issues,
        "read_only": True,
    }
