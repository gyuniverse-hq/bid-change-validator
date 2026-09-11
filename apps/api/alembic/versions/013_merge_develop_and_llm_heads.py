"""Merge develop migrations with the LLM qualification migration branch."""


revision = "013_merge_develop_llm"
down_revision = ("012_late_penalty_rate", "010_dropped_requirements")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join both migration branches without changing the schema."""


def downgrade() -> None:
    """Split the migration graph back into its two parent heads."""
