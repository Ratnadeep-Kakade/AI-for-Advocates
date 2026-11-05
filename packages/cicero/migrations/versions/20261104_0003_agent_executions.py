"""Add agent execution persistence (agents schema).

Revision ID: 20261104_0003
Revises: 20261104_0002
"""

from alembic import op

revision = "20261104_0003"
down_revision = "20261104_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS agents")
    op.execute(
        """CREATE TABLE IF NOT EXISTS agents.executions (
            execution_id uuid PRIMARY KEY,
            organization_id uuid NOT NULL,
            case_id uuid NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            user_request text NOT NULL,
            position text,
            task_spec jsonb NOT NULL DEFAULT '{}'::jsonb,
            plan jsonb NOT NULL DEFAULT '{}'::jsonb,
            final_response text,
            error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz
        )"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS agents.execution_tasks (
            execution_id uuid NOT NULL REFERENCES agents.executions(execution_id) ON DELETE CASCADE,
            task_id text NOT NULL,
            agent_id text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            depends_on jsonb NOT NULL DEFAULT '[]'::jsonb,
            started_at timestamptz,
            completed_at timestamptz,
            PRIMARY KEY (execution_id, task_id)
        )"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS agents.agent_results (
            result_id uuid PRIMARY KEY,
            execution_id uuid NOT NULL REFERENCES agents.executions(execution_id) ON DELETE CASCADE,
            task_id text NOT NULL,
            agent_id text NOT NULL,
            case_id uuid NOT NULL,
            organization_id uuid NOT NULL,
            status text NOT NULL,
            output_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            evidence_references jsonb NOT NULL DEFAULT '[]'::jsonb,
            validation_status text NOT NULL DEFAULT 'pending',
            execution_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agents_executions_case "
        "ON agents.executions (organization_id, case_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agents_results_execution "
        "ON agents.agent_results (execution_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agents.agent_results")
    op.execute("DROP TABLE IF EXISTS agents.execution_tasks")
    op.execute("DROP TABLE IF EXISTS agents.executions")
