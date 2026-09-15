"""공고 의미 그래프와 회사 판정을 독립된 추가 테이블에 저장한다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '023_qualification_graphs'
down_revision = '022_notice_history_backfill'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('qualification_graph_runs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('notice_version_id', pg.UUID(as_uuid=True), sa.ForeignKey('bid_notice_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contract_version', sa.Text(), nullable=False), sa.Column('status', sa.Text(), nullable=False),
        sa.Column('source_basis_sha256', sa.Text(), nullable=False), sa.Column('snapshot_sha256', sa.Text(), nullable=False),
        sa.Column('payload', pg.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("status IN ('SUCCEEDED','PARTIAL','FAILED')", name='qualification_graph_status_valid'))
    op.create_index('idx_qualification_graph_version', 'qualification_graph_runs', ['notice_version_id','created_at'])
    op.create_table('qualification_graph_judgment_runs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('preflight_case_id', pg.UUID(as_uuid=True), sa.ForeignKey('preflight_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('graph_run_id', pg.UUID(as_uuid=True), sa.ForeignKey('qualification_graph_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', pg.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rule_version', sa.Text(), nullable=False), sa.Column('reference_date', sa.Date(), nullable=False),
        sa.Column('profile_snapshot', pg.JSONB(), nullable=False), sa.Column('payload_sha256', sa.Text(), nullable=False),
        sa.Column('payload', pg.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')))
    op.create_index('idx_qualification_graph_judgment_case', 'qualification_graph_judgment_runs', ['preflight_case_id','created_at'])
    for table in ('qualification_graph_runs','qualification_graph_judgment_runs'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bidcheck_app') THEN
            GRANT SELECT, INSERT ON {table} TO bidcheck_app;
            CREATE POLICY {table}_backend_read ON {table} FOR SELECT TO bidcheck_app USING (true);
            CREATE POLICY {table}_backend_insert ON {table} FOR INSERT TO bidcheck_app WITH CHECK (true);
            END IF; END $$;""")


def downgrade():
    op.drop_table('qualification_graph_judgment_runs')
    op.drop_table('qualification_graph_runs')
