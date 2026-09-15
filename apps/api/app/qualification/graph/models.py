"""기존 슬롯 분석/판정과 분리한 의미 그래프 저장. 업데이트 API는 제공하지 않는다."""
from datetime import date, datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from ...models import Base


class QualificationGraphRun(Base):
    __tablename__ = 'qualification_graph_runs'
    __table_args__ = (CheckConstraint("status IN ('SUCCEEDED','PARTIAL','FAILED')", name='qualification_graph_status_valid'),
                     Index('idx_qualification_graph_version', 'notice_version_id', 'created_at'))
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()'))
    notice_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('bid_notice_versions.id', ondelete='CASCADE'))
    contract_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    source_basis_sha256: Mapped[str] = mapped_column(Text)
    snapshot_sha256: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))


class QualificationGraphJudgmentRun(Base):
    __tablename__ = 'qualification_graph_judgment_runs'
    __table_args__ = (Index('idx_qualification_graph_judgment_case', 'preflight_case_id', 'created_at'),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()'))
    preflight_case_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('preflight_cases.id', ondelete='CASCADE'))
    graph_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('qualification_graph_runs.id', ondelete='CASCADE'))
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('companies.id', ondelete='CASCADE'))
    rule_version: Mapped[str] = mapped_column(Text)
    reference_date: Mapped[date] = mapped_column(Date)
    profile_snapshot: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))
