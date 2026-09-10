"""Persist source-validation-rejected qualification candidates."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "010_dropped_requirements"
down_revision = "009_qualification_revalidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qualification_analysis_runs",
        sa.Column(
            "dropped_requirements",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "qualification_analysis_runs_dropped_requirements_array",
        "qualification_analysis_runs",
        "jsonb_typeof(dropped_requirements) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "qualification_analysis_runs_dropped_requirements_array",
        "qualification_analysis_runs",
        type_="check",
    )
    op.drop_column("qualification_analysis_runs", "dropped_requirements")
