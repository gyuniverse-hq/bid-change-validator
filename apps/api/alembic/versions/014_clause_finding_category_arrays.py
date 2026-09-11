"""Add plural category codes and Korean risk labels to clause findings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "014_clause_category_arrays"
down_revision = "013_merge_develop_llm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contract_clause_findings",
        sa.Column("risk_types", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "contract_clause_findings",
        sa.Column("categories", postgresql.JSONB(), nullable=True),
    )
    op.execute(
        """
        UPDATE contract_clause_findings
        SET risk_types = jsonb_build_array(risk_type),
            categories = jsonb_build_array(category)
        """
    )
    op.alter_column("contract_clause_findings", "risk_types", nullable=False)
    op.alter_column("contract_clause_findings", "categories", nullable=False)
    op.create_check_constraint(
        "contract_clause_findings_risk_types_array",
        "contract_clause_findings",
        "jsonb_typeof(risk_types) = 'array' "
        "AND jsonb_array_length(risk_types) >= 1 "
        "AND risk_types ->> 0 = risk_type",
    )
    op.create_check_constraint(
        "contract_clause_findings_categories_array",
        "contract_clause_findings",
        "jsonb_typeof(categories) = 'array' "
        "AND jsonb_array_length(categories) >= 1 "
        "AND categories ->> 0 = category "
        "AND categories <@ '[\"WARRANTY_PERIOD\", \"LATE_PENALTY\", "
        "\"LATE_PENALTY_RATE\", \"COPYRIGHT_OWNERSHIP\", "
        "\"ACCEPTANCE_CRITERIA\", \"SCOPE_AMBIGUITY\", "
        "\"TERMINATION_CONDITION\", \"PAYMENT_TERMS\", "
        "\"LIABILITY_SCOPE\"]'::jsonb",
    )


def downgrade() -> None:
    op.drop_constraint(
        "contract_clause_findings_categories_array",
        "contract_clause_findings",
        type_="check",
    )
    op.drop_constraint(
        "contract_clause_findings_risk_types_array",
        "contract_clause_findings",
        type_="check",
    )
    op.drop_column("contract_clause_findings", "categories")
    op.drop_column("contract_clause_findings", "risk_types")
