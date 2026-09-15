"""그래프 실행 테이블의 backend role 권한을 append-only로 고정한다.

023은 SELECT/INSERT만 명시했지만 Supabase의 기본 table privilege가 먼저 적용된
환경에서는 bidcheck_app에 UPDATE/DELETE가 남을 수 있다. 이미 적용된 023의 이력을
수정하지 않고 후속 migration에서 역할의 table privilege를 정확히 다시 설정한다.
"""
from alembic import op

revision = "024_graph_append_only_acl"
down_revision = "023_qualification_graphs"
branch_labels = None
depends_on = None

_TABLES = (
    "qualification_graph_runs",
    "qualification_graph_judgment_runs",
)


def _set_privileges(grants: str) -> None:
    for table in _TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bidcheck_app') THEN
                    REVOKE ALL PRIVILEGES ON TABLE public.{table} FROM bidcheck_app;
                    GRANT {grants} ON TABLE public.{table} TO bidcheck_app;
                END IF;
            END
            $$;
            """
        )


def upgrade():
    _set_privileges("SELECT, INSERT")


def downgrade():
    # 023이 실제 Supabase 기본 privilege와 결합됐을 때의 상태로 되돌린다.
    _set_privileges("SELECT, INSERT, UPDATE, DELETE")
