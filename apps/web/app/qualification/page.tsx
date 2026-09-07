'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, FileSearch, GitCompareArrows, LoaderCircle, Play, RefreshCw } from 'lucide-react';

import { ConclusionBox } from '@/components/product/conclusion-box';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { QualificationRow, type QualificationRowStatus } from '@/components/product/qualification-row';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import {
  getNoticeVersions,
  getPreflightCase,
  listNotices,
  listPreflightCases,
  type BidNoticeSummary,
  type BidNoticeVersion,
  type PreflightCase,
} from '@/lib/api';
import {
  createPreflightCaseWithCompany,
  getQualificationAnalysis,
  getQualificationJudgment,
  listCompanies,
  listQualificationAnalyses,
  listQualificationJudgments,
  listQualificationQuestions,
  runQualificationAnalysis,
  runQualificationJudgment,
  runQualificationRevalidation,
  type CanonicalRequirement,
  type CompanyProfile,
  type QualificationAnalysisRun,
  type QualificationAnalysisSummary,
  type QualificationJudgment,
  type QualificationJudgmentRun,
  type QualificationQuestion,
  type QualificationRevalidation,
} from '@/lib/qualification-api';

type Busy = 'load' | 'create' | 'analysis' | 'judgment' | 'revalidation' | null;

type RequirementView = {
  requirement: CanonicalRequirement;
  judgment: QualificationJudgment | null;
  evidenceLabel: string;
  evidenceQuote: string | null;
};

const TYPE_LABELS: Record<string, string> = {
  INDUSTRY: '업종',
  REGION: '소재지',
  COMPANY_SIZE: '기업 구분',
  STAFF: '인력',
  PERFORMANCE_COUNT: '수행실적 건수',
  PERFORMANCE_AMOUNT: '수행실적 금액',
  REGISTRATION_CERTIFICATION: '인증 · 등록',
  EXPERIENCE_FIELD: '경험 분야',
};

function judgmentStatus(value: QualificationJudgment | null): QualificationRowStatus {
  return value?.status ?? 'UNJUDGED';
}

function overallCopy(status: QualificationJudgmentRun['overall_status'] | undefined) {
  if (status === 'eligible') return ['참가 가능', '현재 판정된 필수 항목에서 미달이 없습니다.'];
  if (status === 'ineligible') return ['참가 불가', '미달 항목이 있어 현재 상태로는 참가 자격을 충족하지 못합니다.'];
  if (status === 'insufficient_data') return ['확인 필요', '회사 정보가 부족하거나 근거가 불충분한 항목을 확인해야 합니다.'];
  return ['판정 전', '먼저 공고 자격요건을 분석한 뒤 회사 프로필 기준 판정을 실행하세요.'];
}

function companyValue(requirement: CanonicalRequirement, company: CompanyProfile | null) {
  if (!company) return '회사 프로필 없음';
  switch (requirement.type) {
    case 'INDUSTRY':
      return company.industries.length ? company.industries.map((item) => `${item.code} · ${item.name}`).join(', ') : '비어 있음';
    case 'REGION':
      return company.region_name ?? company.region_code ?? '비어 있음';
    case 'COMPANY_SIZE':
      return company.company_size;
    case 'STAFF':
      return company.staff ? `${company.staff.total_count}명${company.staff.roles.length ? ` · ${company.staff.roles.map((role) => `${role.role_name} ${role.headcount}명`).join(', ')}` : ''}` : '비어 있음';
    case 'PERFORMANCE_COUNT':
      return `${company.performances.length}건`;
    case 'PERFORMANCE_AMOUNT': {
      const total = company.performances.reduce((sum, item) => sum + item.amount, 0);
      const max = Math.max(0, ...company.performances.map((item) => item.amount));
      return company.performances.length ? `합계 ${(total / 100_000_000).toFixed(1)}억 · 단일 최대 ${(max / 100_000_000).toFixed(1)}억` : '비어 있음';
    }
    case 'REGISTRATION_CERTIFICATION':
      return company.certifications.length ? company.certifications.map((item) => item.name).join(', ') : '비어 있음';
    case 'EXPERIENCE_FIELD': {
      const fields = [...new Set(company.performances.flatMap((item) => item.fields))];
      return fields.length ? fields.join(', ') : '비어 있음';
    }
    default:
      return '프로필 값 확인';
  }
}

export default function QualificationPage() {
  const searchParams = useSearchParams();
  const requestedCaseId = searchParams.get('caseId');

  const [notices, setNotices] = useState<BidNoticeSummary[]>([]);
  const [companies, setCompanies] = useState<CompanyProfile[]>([]);
  const [cases, setCases] = useState<PreflightCase[]>([]);
  const [noticeId, setNoticeId] = useState('');
  const [companyId, setCompanyId] = useState('');
  const [activeCase, setActiveCase] = useState<PreflightCase | null>(null);
  const [versions, setVersions] = useState<BidNoticeVersion[]>([]);
  const [baselineAnalysis, setBaselineAnalysis] = useState<QualificationAnalysisSummary | null>(null);
  const [currentAnalysis, setCurrentAnalysis] = useState<QualificationAnalysisSummary | null>(null);
  const [analysisDetail, setAnalysisDetail] = useState<QualificationAnalysisRun | null>(null);
  const [sourceJudgment, setSourceJudgment] = useState<QualificationJudgmentRun | null>(null);
  const [displayJudgment, setDisplayJudgment] = useState<QualificationJudgmentRun | null>(null);
  const [questions, setQuestions] = useState<QualificationQuestion[]>([]);
  const [revalidation, setRevalidation] = useState<QualificationRevalidation | null>(null);
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>('load');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const selectedNotice = useMemo(() => notices.find((item) => item.id === noticeId) ?? null, [noticeId, notices]);
  const company = useMemo(() => companies.find((item) => item.id === companyId) ?? null, [companies, companyId]);
  const baselineVersion = useMemo(() => versions.find((item) => item.version_number === activeCase?.baseline_version_number) ?? null, [activeCase, versions]);

  async function loadAnalysisDetail(summary: QualificationAnalysisSummary | null) {
    if (!summary) {
      setAnalysisDetail(null);
      return;
    }
    setAnalysisDetail(await getQualificationAnalysis(summary.id));
  }

  async function hydrateCase(caseId: string) {
    const selected = await getPreflightCase(caseId);
    const fetchedVersions = await getNoticeVersions(selected.notice_id);
    setActiveCase(selected);
    setNoticeId(selected.notice_id);
    setCompanyId(selected.company_id ?? '');
    setVersions(fetchedVersions);
    setRevalidation(null);

    const [currentAnalyses, baselineAnalyses, judgmentSummaries] = await Promise.all([
      listQualificationAnalyses(selected.notice_id, selected.current_version_number),
      selected.baseline_version_number ? listQualificationAnalyses(selected.notice_id, selected.baseline_version_number) : Promise.resolve([]),
      listQualificationJudgments(selected.id),
    ]);
    const current = currentAnalyses[0] ?? null;
    const baseline = baselineAnalyses[0] ?? null;
    setCurrentAnalysis(current);
    setBaselineAnalysis(baseline);
    await loadAnalysisDetail(current);

    const baselineVersionId = fetchedVersions.find((item) => item.version_number === selected.baseline_version_number)?.id;
    const currentVersionId = fetchedVersions.find((item) => item.version_number === selected.current_version_number)?.id;
    const baselineSummary = baselineVersionId ? judgmentSummaries.find((item) => item.notice_version_id === baselineVersionId) : null;
    const latestSummary = judgmentSummaries[0] ?? null;
    const sourceSummary = baselineSummary ?? latestSummary;
    const displaySummary = judgmentSummaries.find((item) => item.notice_version_id === currentVersionId) ?? latestSummary;
    const [source, display] = await Promise.all([
      sourceSummary ? getQualificationJudgment(sourceSummary.id) : Promise.resolve(null),
      displaySummary ? getQualificationJudgment(displaySummary.id) : Promise.resolve(null),
    ]);
    setSourceJudgment(source);
    setDisplayJudgment(display);
    setQuestions(source ? await listQualificationQuestions(selected.id, source.id) : []);
  }

  async function initialize() {
    setBusy('load');
    setError('');
    try {
      const [noticeResult, companyResult, caseResult] = await Promise.all([listNotices(), listCompanies(), listPreflightCases()]);
      setNotices(noticeResult.items);
      setCompanies(companyResult);
      setCases(caseResult.items);
      setNoticeId(noticeResult.items[0]?.id ?? '');
      setCompanyId(companyResult[0]?.id ?? '');
      const targetCase = requestedCaseId && caseResult.items.some((item) => item.id === requestedCaseId)
        ? requestedCaseId
        : caseResult.items[0]?.id;
      if (targetCase) await hydrateCase(targetCase);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '초기 데이터를 불러오지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, [requestedCaseId]);

  async function createCase() {
    if (!selectedNotice || !companyId) return;
    setBusy('create');
    setError('');
    try {
      const fetchedVersions = await getNoticeVersions(selectedNotice.id);
      const current = fetchedVersions.find((item) => item.is_current) ?? fetchedVersions[0];
      if (!current) throw new Error('공고 버전을 찾을 수 없습니다.');
      const baseline = fetchedVersions.filter((item) => item.version_number < current.version_number).sort((a, b) => b.version_number - a.version_number)[0];
      const created = await createPreflightCaseWithCompany({ notice_id: selectedNotice.id, company_id: companyId, baseline_version_number: baseline?.version_number, current_version_number: current.version_number, title: `${selectedNotice.bid_notice_no} 자격 검토` });
      const refreshed = await listPreflightCases();
      setCases(refreshed.items);
      await hydrateCase(created.id);
      setMessage('검토 건을 만들었습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function ensureAnalysis(versionNumber: number) {
    const existing = await listQualificationAnalyses(activeCase!.notice_id, versionNumber);
    return existing[0] ?? (await runQualificationAnalysis(activeCase!.notice_id, versionNumber)).run;
  }

  async function prepareAnalyses() {
    if (!activeCase) return;
    setBusy('analysis');
    setError('');
    try {
      const [baseline, current] = await Promise.all([
        activeCase.baseline_version_number ? ensureAnalysis(activeCase.baseline_version_number) : Promise.resolve(null),
        ensureAnalysis(activeCase.current_version_number),
      ]);
      setBaselineAnalysis(baseline);
      setCurrentAnalysis(current);
      await loadAnalysisDetail(current);
      setMessage('공고 자격요건 분석을 완료했습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '자격요건 분석에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function runInitialJudgment() {
    if (!activeCase) return;
    const target = activeCase.baseline_version_number ? baselineAnalysis : currentAnalysis;
    if (!target) {
      setError('먼저 자격요건 분석을 실행하세요.');
      return;
    }
    setBusy('judgment');
    setError('');
    try {
      const result = await runQualificationJudgment(activeCase.id, target.id);
      setSourceJudgment(result);
      setDisplayJudgment(result);
      setQuestions(await listQualificationQuestions(activeCase.id, result.id));
      setMessage('회사 프로필 기준 판정을 완료했습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '자격 판정에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function revalidate() {
    if (!activeCase || !sourceJudgment || !baselineAnalysis || !currentAnalysis) return;
    setBusy('revalidation');
    setError('');
    try {
      const result = await runQualificationRevalidation(activeCase.id, { source_judgment_run_id: sourceJudgment.id, baseline_analysis_run_id: baselineAnalysis.id, current_analysis_run_id: currentAnalysis.id });
      setRevalidation(result);
      setDisplayJudgment(result.result);
      setMessage(`변경 조건 ${result.revalidated_keys.length}개를 다시 판정했습니다.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '변경공고 재검증에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  const views: RequirementView[] = useMemo(() => {
    if (!analysisDetail) return [];
    return analysisDetail.requirements.map((requirement) => {
      const judgment = displayJudgment?.judgments.find((item) => item.requirement_key === requirement.requirement_key) ?? null;
      const evidenceKey = requirement.evidence_keys[0];
      const evidence = evidenceKey ? analysisDetail.evidence.find((item) => item.evidence_key === evidenceKey) : null;
      return { requirement, judgment, evidenceLabel: evidenceKey ?? '근거 없음', evidenceQuote: evidence?.quote ?? null };
    });
  }, [analysisDetail, displayJudgment]);

  const selectedEvidence = selectedEvidenceKey ? analysisDetail?.evidence.find((item) => item.evidence_key === selectedEvidenceKey) ?? null : null;
  const satisfied = displayJudgment?.judgments.filter((item) => item.status === 'SATISFIED').length ?? 0;
  const unknown = displayJudgment?.judgments.filter((item) => item.status === 'UNKNOWN').length ?? 0;
  const unsatisfied = displayJudgment?.judgments.filter((item) => item.status === 'UNSATISFIED').length ?? 0;
  const [conclusionTitle, conclusionDescription] = overallCopy(displayJudgment?.overall_status);
  const canRevalidate = Boolean(activeCase?.baseline_version_number && baselineAnalysis && currentAnalysis && sourceJudgment && baselineVersion && sourceJudgment.notice_version_id === baselineVersion.id);

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        {(error || message) && (
          <div className={`mb-6 flex items-start gap-2 rounded-[14px] border px-4 py-3 text-[13px] ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
            {error ? <AlertCircle className="mt-0.5 size-4" /> : <CheckCircle2 className="mt-0.5 size-4" />}
            <span>{error || message}</span>
          </div>
        )}

        {!activeCase ? (
          <section className="rounded-[22px] border border-[var(--product-line)] bg-white p-7 shadow-sm">
            <h2 className="text-[24px] font-extrabold tracking-[-0.03em]">새 참가자격 검토</h2>
            <p className="mt-2 text-[14px] text-[var(--product-muted)]">회사 프로필과 공고를 연결해 검토 건을 만듭니다.</p>
            <div className="mt-6 grid gap-4 md:grid-cols-2">
              <NativeSelect value={companyId} onChange={(event) => setCompanyId(event.target.value)}>{companies.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name}</NativeSelectOption>)}</NativeSelect>
              <NativeSelect value={noticeId} onChange={(event) => setNoticeId(event.target.value)}>{notices.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.bid_notice_no} · {item.title}</NativeSelectOption>)}</NativeSelect>
            </div>
            <Button className="mt-4" onClick={() => void createCase()} disabled={!companyId || !noticeId || busy !== null}>검토 건 만들기</Button>
          </section>
        ) : (
          <>
            <section className="flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
              <div className="min-w-0">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">현재 v{activeCase.current_version_number}</Badge>
                  {activeCase.baseline_version_number && <Badge variant="secondary">기준 v{activeCase.baseline_version_number}</Badge>}
                  {analysisDetail?.status && <Badge variant="outline">분석 {analysisDetail.status}</Badge>}
                </div>
                <h2 className="mt-4 text-[28px] font-extrabold leading-10 tracking-[-0.035em] text-[var(--product-ink)]">{selectedNotice?.title ?? activeCase.notice_title}</h2>
                <p className="mt-2 text-[13px] text-[var(--product-muted)]">공고번호 {activeCase.bid_notice_no} · {selectedNotice?.announcing_institution_name ?? '공고기관 미상'}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => void initialize()} disabled={busy !== null}><RefreshCw className={busy === 'load' ? 'animate-spin' : ''} /> 새로고침</Button>
                <Link href="/notices"><Button variant="outline">공고 목록</Button></Link>
              </div>
            </section>

            <section className="mt-8">
              <div className="flex flex-wrap gap-2 border-b border-[var(--product-line)] pb-3">
                <span className="rounded-full bg-[var(--product-accent-deep)] px-5 py-2 text-[13px] font-bold text-white">판정</span>
                <Link href="/evaluation" className="rounded-full px-5 py-2 text-[13px] font-semibold text-[var(--product-muted)]">평가 대응</Link>
                <Link href="/changes" className="rounded-full px-5 py-2 text-[13px] font-semibold text-[var(--product-muted)]">변경 이력</Link>
              </div>
            </section>

            <section className="mt-6 grid gap-4 lg:grid-cols-3">
              <div className="rounded-[18px] border border-[var(--product-line)] p-5"><span className="text-[12px] text-[var(--product-muted)]">회사 프로필</span><strong className="mt-1 block text-[16px]">{company?.name ?? '미연결'}</strong><p className="mt-2 text-[12px] text-[var(--product-muted)]">{company?.region_name ?? '-'} · {company?.company_size ?? '-'}</p></div>
              <div className="rounded-[18px] border border-[var(--product-line)] p-5"><span className="text-[12px] text-[var(--product-muted)]">자격요건 분석</span><strong className="mt-1 block text-[16px]">{currentAnalysis ? `${currentAnalysis.requirement_count}건 구조화` : '분석 전'}</strong><p className="mt-2 text-[12px] text-[var(--product-muted)]">Evidence {currentAnalysis?.evidence_count ?? 0}건</p></div>
              <div className="rounded-[18px] border border-[var(--product-line)] p-5"><span className="text-[12px] text-[var(--product-muted)]">확인 필요</span><strong className="mt-1 block text-[16px]">{questions.length}건</strong><p className="mt-2 text-[12px] text-[var(--product-muted)]">답변 가능한 UNKNOWN 항목</p></div>
            </section>

            <div className="mt-6">
              <ConclusionBox
                title={conclusionTitle}
                description={conclusionDescription}
                satisfied={satisfied}
                unknown={unknown}
                unsatisfied={unsatisfied}
                action={!analysisDetail ? <Button onClick={() => void prepareAnalyses()} disabled={busy !== null}>{busy === 'analysis' ? <LoaderCircle className="animate-spin" /> : <Play />} 자격요건 분석</Button> : !displayJudgment ? <Button onClick={() => void runInitialJudgment()} disabled={busy !== null}>{busy === 'judgment' ? <LoaderCircle className="animate-spin" /> : <CheckCircle2 />} 자격 판정</Button> : undefined}
              />
            </div>

            <section className="mt-9">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
                <div><h2 className="text-[25px] font-extrabold tracking-[-0.035em]">참가 자격 (필수)</h2><p className="mt-1 text-[13px] text-[var(--product-muted)]">Canonical Requirement와 공고 원문 Evidence를 기준으로 표시합니다.</p></div>
                <span className="text-[13px] text-[var(--product-muted)]">구조화 {views.length}건 · 판정 {displayJudgment?.judgments.length ?? 0}건</span>
              </div>

              <div className="mt-4 overflow-hidden rounded-[18px] border border-[var(--product-line)] bg-white">
                <div className="hidden min-h-[45px] grid-cols-[122px_minmax(0,1.9fr)_minmax(190px,0.8fr)_170px_160px] items-center bg-[var(--product-tint)] text-[12px] font-semibold text-[var(--product-muted)] lg:grid">
                  <div className="px-3">판정</div><div className="px-3">참가 자격 조건</div><div className="px-3">귀사 값</div><div className="px-3">근거</div><div className="px-3">조치</div>
                </div>
                {views.length ? views.map(({ requirement, judgment, evidenceLabel }) => (
                  <QualificationRow
                    key={requirement.requirement_key}
                    status={judgmentStatus(judgment)}
                    condition={`${TYPE_LABELS[requirement.type] ?? requirement.type} · ${requirement.raw}`}
                    companyValue={companyValue(requirement, company)}
                    evidenceLabel={evidenceLabel}
                    actionLabel={judgment?.status === 'UNKNOWN' ? '확인하기' : judgment ? '판정 완료' : '판정 필요'}
                    onEvidence={requirement.evidence_keys[0] ? () => setSelectedEvidenceKey(requirement.evidence_keys[0]) : undefined}
                    onAction={judgment?.status === 'UNKNOWN' && questions.some((item) => item.requirement_key === requirement.requirement_key) ? () => { window.location.href = `/ask-back?caseId=${activeCase.id}`; } : undefined}
                  />
                )) : <div className="px-6 py-14 text-center"><FileSearch className="mx-auto size-8 text-[var(--product-faint)]" /><p className="mt-3 text-[14px] font-semibold">아직 구조화된 자격요건이 없습니다.</p><Button className="mt-4" onClick={() => void prepareAnalyses()} disabled={busy !== null}>자격요건 분석 시작</Button></div>}
              </div>
            </section>

            {selectedEvidence && (
              <section className="mt-7">
                <h2 className="mb-3 text-[20px] font-extrabold">선택한 원문 근거</h2>
                <EvidenceQuote label={selectedEvidence.evidence_key} quote={selectedEvidence.quote} note={`문서 ID ${selectedEvidence.document_id}`} />
              </section>
            )}

            <section className="mt-9 grid gap-5 lg:grid-cols-2">
              <div className="rounded-[20px] border border-[var(--product-line)] p-6">
                <h2 className="text-[20px] font-extrabold">분석 완전성</h2>
                <p className="mt-2 text-[13px] leading-6 text-[var(--product-muted)]">분석 실행 상태와 diagnostic을 판정 결과와 분리해서 관리합니다.</p>
                <div className="mt-5 flex flex-wrap gap-3"><Badge variant="outline">상태 {analysisDetail?.status ?? '미실행'}</Badge><Badge variant="outline">Requirement {analysisDetail?.requirements.length ?? 0}</Badge><Badge variant="outline">Evidence {analysisDetail?.evidence.length ?? 0}</Badge></div>
                {analysisDetail?.diagnostics.length ? <div className="mt-4 space-y-2">{analysisDetail.diagnostics.map((item) => <p key={`${item.code}-${item.message}`} className="rounded-xl bg-amber-50 px-3 py-2 text-[12px] text-amber-800">{item.code} · {item.message}</p>)}</div> : null}
              </div>
              <div className="rounded-[20px] border border-[var(--product-line)] p-6">
                <h2 className="text-[20px] font-extrabold">변경공고 영향 재검증</h2>
                <p className="mt-2 text-[13px] leading-6 text-[var(--product-muted)]">기준 차수와 현재 차수가 모두 있으면 변경된 Canonical Requirement만 다시 판정합니다.</p>
                <Button className="mt-5" variant="outline" onClick={() => void revalidate()} disabled={!canRevalidate || busy !== null}>{busy === 'revalidation' ? <LoaderCircle className="animate-spin" /> : <GitCompareArrows />} 변경 재검증</Button>
                {revalidation && <p className="mt-4 text-[13px]">재판정된 Requirement <strong>{revalidation.revalidated_keys.length}건</strong></p>}
              </div>
            </section>

            <section className="mt-9 rounded-[20px] border border-[var(--product-line)] bg-[var(--product-tint)] p-5">
              <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><h2 className="text-[18px] font-extrabold">다른 검토 건</h2><p className="mt-1 text-[12px] text-[var(--product-muted)]">선택한 공고의 Case로 정확히 이동합니다.</p></div><NativeSelect className="sm:w-[420px]" value={activeCase.id} onChange={(event) => void hydrateCase(event.target.value)}>{cases.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.bid_notice_no} · {item.title}</NativeSelectOption>)}</NativeSelect></div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}
