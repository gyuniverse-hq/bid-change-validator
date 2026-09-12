'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, FileSearch, GitCompareArrows, LoaderCircle, Play, RefreshCw } from 'lucide-react';

import { loadCaseWorkspace } from '@/lib/case-workspace';
import { ActionCard } from '@/components/copilot/action-card';
import { useActions } from '@/components/copilot/provider';
import { currentRevalidation, isLocked } from '@/lib/copilot-actions';
import { CaseTabs } from '@/components/product/case-header';
import { ConclusionBox } from '@/components/product/conclusion-box';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { ANALYSIS_STATUS_COPY, COMPANY_SIZE_LABEL, DROPPED_REASON_LABEL, OVERALL_STATUS_COPY, REQUIREMENT_TYPE_LABEL, evidenceLocationText, labelOf } from '@/lib/status-copy';
import { QualificationRow, type QualificationRowStatus } from '@/components/product/qualification-row';
import { QualificationSourceOverview } from '@/components/product/qualification-source-overview';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import {
  getNoticeVersions,
  listNotices,
  listPreflightCases,
  type BidNoticeSummary,
  type BidNoticeVersion,
  type PreflightCase,
} from '@/lib/api';
import {
  createPreflightCaseWithCompany,
  getQualificationAnalysis,
  listCompanies,
  listQualificationQuestions,
  runQualificationAnalysis,
  runQualificationJudgment,
  type CanonicalRequirement,
  type CompanyProfile,
  type QualificationAnalysisRun,
  type QualificationAnalysisSummary,
  type QualificationJudgment,
  type QualificationJudgmentRun,
  type QualificationQuestion,
} from '@/lib/qualification-api';

type Busy = 'load' | 'create' | 'review' | null;
type ReviewStep = 'idle' | 'analysis' | 'judgment' | 'done';
type RequirementView = {
  requirement: CanonicalRequirement;
  judgment: QualificationJudgment | null;
  evidenceLabel: string;
};


function judgmentStatus(value: QualificationJudgment | null): QualificationRowStatus {
  return value?.status ?? 'UNJUDGED';
}

function overallCopy(status: QualificationJudgmentRun['overall_status'] | undefined) {
  const copy = status ? OVERALL_STATUS_COPY[status] : null;
  if (copy) return [copy.label, copy.description];
  return ['검토 전', '검토를 시작하면 공고 원문 분석과 회사 프로필 비교를 순서대로 실행합니다.'];
}

function companyValue(requirement: CanonicalRequirement, company: CompanyProfile | null, judgment: QualificationJudgment | null) {
  if (judgment?.basis_type === 'USER_ANSWER') return '사용자 답변으로 판정 · 회사 프로필에는 반영하지 않음';
  if (!company) return '회사 프로필 없음';
  switch (requirement.type) {
    case 'INDUSTRY': return company.industries.length ? company.industries.map((item) => `${item.code} · ${item.name}`).join(', ') : '비어 있음';
    case 'REGION': return company.region_name ?? company.region_code ?? '비어 있음';
    case 'COMPANY_SIZE': return company.company_size;
    case 'STAFF': return company.staff ? `${company.staff.total_count}명${company.staff.roles.length ? ` · ${company.staff.roles.map((role) => `${role.role_name} ${role.headcount}명`).join(', ')}` : ''}` : '비어 있음';
    case 'PERFORMANCE_COUNT': return `${company.performances.length}건`;
    case 'PERFORMANCE_AMOUNT': {
      const total = company.performances.reduce((sum, item) => sum + item.amount, 0);
      const max = Math.max(0, ...company.performances.map((item) => item.amount));
      return company.performances.length ? `합계 ${(total / 100_000_000).toFixed(1)}억 · 단일 최대 ${(max / 100_000_000).toFixed(1)}억` : '비어 있음';
    }
    case 'REGISTRATION_CERTIFICATION': return company.certifications.length ? company.certifications.map((item) => item.name).join(', ') : '비어 있음';
    case 'EXPERIENCE_FIELD': {
      const fields = [...new Set(company.performances.flatMap((item) => item.fields))];
      return fields.length ? fields.join(', ') : '비어 있음';
    }
    default: return '프로필 값 확인';
  }
}

function canReuseAnalysis(summary: QualificationAnalysisSummary | null) {
  return Boolean(summary && summary.status === 'SUCCEEDED' && summary.requirement_count > 0);
}

export default function QualificationPage() {
  const requestedCaseId = useSearchParams().get('caseId');
  return <QualificationWorkspace key={requestedCaseId} requestedCaseId={requestedCaseId} />;
}

function QualificationWorkspace({ requestedCaseId }: { requestedCaseId: string | null }) {
  const router = useRouter();
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
  const { controller, action } = useActions(requestedCaseId ?? '');
  const actionLocked = isLocked(action);
  const revalidation = currentRevalidation(action.result, {
    caseId: requestedCaseId ?? '', baselineAnalysisId: baselineAnalysis?.id,
    currentAnalysisId: currentAnalysis?.id, judgmentId: displayJudgment?.id,
  });
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>('load');
  const [reviewStep, setReviewStep] = useState<ReviewStep>('idle');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  // 판정 밖 조건은 10건 넘게 나오는 게 보통이라, 다 펼쳐두면 판정 2건보다 블록이 다섯 배 커진다.
  // 기본은 접어두고 필요할 때 편다. 건수는 접혀 있어도 제목에 그대로 보인다.
  const [showAllUnjudged, setShowAllUnjudged] = useState(false);

  const selectedNotice = useMemo(() => notices.find((item) => item.id === noticeId) ?? null, [noticeId, notices]);
  const company = useMemo(() => companies.find((item) => item.id === companyId) ?? null, [companies, companyId]);
  const currentVersion = useMemo(() => versions.find((item) => item.version_number === activeCase?.current_version_number) ?? null, [activeCase, versions]);
  const baselineVersion = useMemo(() => versions.find((item) => item.version_number === activeCase?.baseline_version_number) ?? null, [activeCase, versions]);

  async function loadAnalysisDetail(summary: QualificationAnalysisSummary | QualificationAnalysisRun | null, request: number) {
    if (!summary) return setAnalysisDetail(null);
    if ('requirements' in summary) return setAnalysisDetail(summary);
    const detail = await getQualificationAnalysis(summary.id);
    if (request === generation.current) setAnalysisDetail(detail);
  }

  const generation = useRef(0);

  const initialize = useCallback(async () => {
    async function hydrateCase(caseId: string, request: number) {
      const workspace = await loadCaseWorkspace(caseId);
      if (request !== generation.current) return;
      setActiveCase(workspace.caseItem);
      setNoticeId(workspace.caseItem.notice_id);
      setCompanyId(workspace.caseItem.company_id ?? '');
      setVersions(workspace.versions);
      setBaselineAnalysis(workspace.baselineAnalysis);
      setCurrentAnalysis(workspace.currentAnalysis);
      setAnalysisDetail(workspace.currentAnalysisDetail);
      setSourceJudgment(workspace.sourceJudgment);
      setDisplayJudgment(workspace.displayJudgment);
      setQuestions(workspace.questions);
      setReviewStep(workspace.displayJudgment ? 'done' : 'idle');
      setSelectedEvidenceKey(null);
    }

    generation.current += 1;
    const request = generation.current;
    setActiveCase(null);
    setAnalysisDetail(null);
    setDisplayJudgment(null);
    setSourceJudgment(null);
    setQuestions([]);
    setMessage('');
    setBusy('load');
    setError('');
    try {
      const [noticeResult, companyResult, caseResult] = await Promise.all([listNotices(), listCompanies(), listPreflightCases()]);
      if (request !== generation.current) return;
      setNotices(noticeResult.items);
      setCompanies(companyResult);
      setCases(caseResult.items);
      setNoticeId(noticeResult.items[0]?.id ?? '');
      setCompanyId(companyResult[0]?.id ?? '');
      const targetCase = requestedCaseId;
      if (targetCase) await hydrateCase(targetCase, request);
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : '초기 데이터를 불러오지 못했습니다.');
    } finally {
      if (request === generation.current) setBusy(null);
    }
  }, [requestedCaseId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => { window.clearTimeout(timer); generation.current += 1; };
  }, [initialize]);

  useEffect(() => {
    if (action.stage !== 'COMPLETED') return;
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, [action.stage, action.result?.result_judgment_run_id, initialize]);

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
      router.push(`/qualification?caseId=${created.id}`);
      setMessage('검토 건을 만들었습니다. 이제 참가자격 검토를 시작할 수 있습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function getOrRunAnalysis(versionNumber: number, existing: QualificationAnalysisSummary | null, force: boolean) {
    if (!force && canReuseAnalysis(existing)) return existing!;
    return runQualificationAnalysis(activeCase!.notice_id, versionNumber);
  }

  async function runFullReview(force = false) {
    if (!activeCase || busy !== null || isLocked(controller.get(activeCase.id))) return;
    if (!controller.acquireReview(activeCase.id)) return;
    setBusy('review');
    setError('');
    setMessage('');
    const request = generation.current;
    setDisplayJudgment(null);
    setSourceJudgment(null);
    setQuestions([]);
    setReviewStep('analysis');
    try {
      const [baseline, current] = await Promise.all([
        activeCase.baseline_version_number
          ? getOrRunAnalysis(activeCase.baseline_version_number, baselineAnalysis, force)
          : Promise.resolve(null),
        getOrRunAnalysis(activeCase.current_version_number, currentAnalysis, force),
      ]);
      if (request !== generation.current) return;
      setBaselineAnalysis(baseline);
      setCurrentAnalysis(current);
      await loadAnalysisDetail(current, request);
      if (request !== generation.current) return;

      setReviewStep('judgment');
      let baselineJudgment: QualificationJudgmentRun | null = null;
      if (baseline) baselineJudgment = await runQualificationJudgment(activeCase.id, baseline.id);
      if (request !== generation.current) return;
      const currentJudgment = await runQualificationJudgment(activeCase.id, current.id);

      if (request !== generation.current) return;
      setSourceJudgment(baselineJudgment ?? currentJudgment);
      setDisplayJudgment(currentJudgment);
      const nextQuestions = await listQualificationQuestions(activeCase.id, currentJudgment.id);
      if (request !== generation.current) return;
      setQuestions(nextQuestions);
      setReviewStep('done');
      setMessage(`참가자격 검토를 완료했습니다. 자격조건 ${'requirements' in current && Array.isArray(current.requirements) ? current.requirements.length : current.requirement_count}건을 분석하고 회사 프로필 기준 판정을 반영했습니다.`);
    } catch (cause) {
      if (request !== generation.current) return;
      setReviewStep('idle');
      setError(cause instanceof Error ? cause.message : '참가자격 검토에 실패했습니다.');
    } finally {
      controller.releaseReview(activeCase.id);
      if (request === generation.current) setBusy(null);
    }
  }

  const views: RequirementView[] = useMemo(() => {
    if (!analysisDetail) return [];
    return analysisDetail.requirements.map((requirement) => {
      const judgment = displayJudgment?.judgments.find((item) => item.requirement_key === requirement.requirement_key) ?? null;
      const evidenceKey = requirement.evidence_keys[0];
      return { requirement, judgment, evidenceLabel: evidenceKey ?? '근거 없음' };
    });
  }, [analysisDetail, displayJudgment]);

  const selectedEvidence = selectedEvidenceKey ? analysisDetail?.evidence.find((item) => item.evidence_key === selectedEvidenceKey) ?? null : null;
  const satisfied = displayJudgment?.judgments.filter((item) => item.status === 'SATISFIED').length ?? 0;
  const unknown = displayJudgment?.judgments.filter((item) => item.status === 'UNKNOWN').length ?? 0;
  const unsatisfied = displayJudgment?.judgments.filter((item) => item.status === 'UNSATISFIED').length ?? 0;
  const [conclusionTitle, conclusionDescription] = overallCopy(displayJudgment?.overall_status);
  const canRevalidate = Boolean(activeCase?.baseline_version_number && baselineAnalysis && currentAnalysis && sourceJudgment && baselineVersion && sourceJudgment.notice_version_id === baselineVersion.id);
  const askableQuestionKeys = new Set(questions.filter((item) => item.askable).map((item) => item.requirement_key));
  const analysisNeedsRetry = Boolean(analysisDetail && (analysisDetail.status !== 'SUCCEEDED' || analysisDetail.requirements.length === 0));

  const reviewProgress = reviewStep === 'analysis'
    ? '1/2 공고 원문에서 자격조건과 근거를 분석하고 있습니다.'
    : reviewStep === 'judgment'
      ? '2/2 회사 프로필과 자격조건을 비교해 판정하고 있습니다.'
      : reviewStep === 'done'
        ? '분석과 판정이 완료되었습니다.'
        : null;

  // P0-5 · 판정에 들어가지 못한 조건은 두 갈래로 들어온다. 성격이 달라서 한 자리에 섞어 그리면 안 된다.
  //  · NOTICE_FACT 진단 — 공고에서 확인했지만 회사 프로필과 대조할 수 없는 사실. 근거(evidence_keys)가 있다.
  //  · dropped_requirements — 공고 원문 대조를 통과하지 못해 구조화에서 빠진 후보. raw·reason_code만 온다.
  const noticeFacts = analysisDetail?.diagnostics.filter((item) => item.kind === 'NOTICE_FACT') ?? [];
  const pipelineDiagnostics = analysisDetail?.diagnostics.filter((item) => item.kind !== 'NOTICE_FACT') ?? [];
  const droppedRequirements = analysisDetail?.dropped_requirements ?? [];

  // 판정 밖 조건도 셋으로 갈린다 — 아직 안 돌렸다 / 못 읽었다 / 확인했더니 없다.
  // 0건일 때도 이 자리에서 말해야 한다. 아무 말도 안 하면 「빠진 게 없다」를 사용자가 알 수 없다.
  const unjudgedCount = noticeFacts.length + droppedRequirements.length;
  const unjudgedState: 'NOT_RUN' | 'FAILED' | 'DONE' = !analysisDetail
    ? 'NOT_RUN'
    : analysisDetail.status === 'FAILED'
      ? 'FAILED'
      : 'DONE';

  // 접었을 때 보여줄 개수. 공고 쪽 확인사항을 먼저 채우고 남으면 제외 요건을 채운다.
  const UNJUDGED_PREVIEW = 3;
  const previewNoticeFacts = showAllUnjudged ? noticeFacts : noticeFacts.slice(0, UNJUDGED_PREVIEW);
  const previewDropped = showAllUnjudged
    ? droppedRequirements
    : droppedRequirements.slice(0, Math.max(0, UNJUDGED_PREVIEW - previewNoticeFacts.length));
  const hiddenUnjudgedCount = unjudgedCount - previewNoticeFacts.length - previewDropped.length;

  // message는 code별 고정 문구다. 걸린 code가 하나뿐이면 열 줄 모두 같은 문장이 되므로
  // 항목마다 반복하지 않고 목록 머리에 한 번만 쓴다. 종류가 섞여 있으면 항목별로 둔다.
  const noticeFactMessages = Array.from(new Set(noticeFacts.map((item) => item.message)));
  const sharedNoticeFactMessage = noticeFactMessages.length === 1 ? noticeFactMessages[0] : null;

  // 실행 전·실패는 「세어본 적이 없는」 상태다. 0으로 적으면 확인 후 0건으로 읽힌다 — #119 리뷰.
  const countedAnalysis = analysisDetail && analysisDetail.status !== 'FAILED' ? analysisDetail : null;

  // 분석이 실패했을 때 「없습니다」라고 하면 「확인했는데 없더라」로 읽힌다.
  // 「확인하지 못했다」와 구분한다 — 화면필드명세 공통원칙 3.
  const emptyRequirementCopy = busy === 'review'
    ? '자격요건을 분석하고 있습니다. 잠시만 기다려 주세요.'
    : !analysisDetail
      ? '아직 자격검토를 실행하지 않았습니다.'
      : analysisDetail.status === 'FAILED'
        ? '분석이 완료되지 않아 자격요건을 표시할 수 없습니다. 위 안내를 확인해 주세요.'
        : '이번 분석에서 안전하게 구조화된 자격요건이 없습니다.';

  if (busy === 'load' || (requestedCaseId && activeCase?.id !== requestedCaseId && !error)) return <main className="app-shell-container py-12">
    {requestedCaseId && <ActionCard caseId={requestedCaseId} />}
    <output>검토 데이터를 불러오고 있습니다.</output>
  </main>;
  if (requestedCaseId && !activeCase) return <main className="app-shell-container py-12">
    <ActionCard caseId={requestedCaseId} />
    <p role="alert">{error || '검토 건을 찾을 수 없습니다.'}</p>
    <Button variant="outline" className="mt-4" onClick={() => void initialize()}>화면 정보 다시 조회</Button>
    <Link href="/notices" className="ml-4 underline">공고 찾기</Link>
  </main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        {(error || message) && <div className={`mb-6 flex items-start gap-2 rounded-[14px] border px-4 py-3 text-[13px] ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error ? <AlertCircle className="mt-0.5 size-4" /> : <CheckCircle2 className="mt-0.5 size-4" />}<span>{error || message}</span></div>}

        {!activeCase ? (
          <section className="rounded-[22px] border border-[var(--product-line)] bg-white p-7 shadow-sm">
            <h2 className="text-[24px] font-extrabold tracking-[-0.03em]">새 참가자격 검토</h2>
            <p className="mt-2 text-[14px] text-[var(--product-muted)]">회사 프로필과 공고를 연결해 검토 건을 만듭니다.</p>
            <div className="mt-6 grid gap-4 md:grid-cols-2"><NativeSelect value={companyId} onChange={(event) => setCompanyId(event.target.value)}>{companies.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name}</NativeSelectOption>)}</NativeSelect><NativeSelect value={noticeId} onChange={(event) => setNoticeId(event.target.value)}>{notices.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.bid_notice_no} · {item.title}</NativeSelectOption>)}</NativeSelect></div>
            <Button className="mt-4" onClick={() => void createCase()} disabled={!companyId || !noticeId || busy !== null}>검토 건 만들기</Button>
          </section>
        ) : (
          <>
            {/* ── 1 공고 · 검토 건 ── */}
            <section className="flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
              <div className="min-w-0"><div className="flex flex-wrap gap-2"><Badge variant="outline">현재 v{activeCase.current_version_number}</Badge>{activeCase.baseline_version_number && <Badge variant="secondary">기준 v{activeCase.baseline_version_number}</Badge>}{analysisDetail?.status && <Badge variant="outline">분석 {analysisDetail.status}</Badge>}</div><h2 className="mt-4 text-[28px] font-extrabold leading-10 tracking-[-0.035em] text-[var(--product-ink)]">{selectedNotice?.title ?? activeCase.notice_title}</h2><p className="mt-2 text-[13px] text-[var(--product-muted)]">공고번호 {activeCase.bid_notice_no} · {selectedNotice?.announcing_institution_name ?? '공고기관 미상'}</p></div>
              <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => void initialize()} disabled={busy !== null}><RefreshCw /> 새로고침</Button><Link href="/notices"><Button variant="outline">공고 목록</Button></Link></div>
            </section>

            <CaseTabs caseId={activeCase.id} active="qualification" />

            {/* ── 2 결론 — 이 화면에 온 이유에 먼저 답한다 ── */}
            <div className="mt-6"><ConclusionBox title={conclusionTitle} description={conclusionDescription} satisfied={satisfied} unknown={unknown} unsatisfied={unsatisfied} action={<div className="flex gap-2"><Button onClick={() => void runFullReview(Boolean(analysisDetail))} disabled={busy !== null || actionLocked}>{busy === 'review' ? <LoaderCircle className="animate-spin" /> : <Play />}{displayJudgment ? '다시 검토' : '참가자격 검토 시작'}</Button>{analysisNeedsRetry && <Badge className="self-center bg-amber-100 text-amber-800">기존 분석 {analysisDetail?.status} · 새로 분석합니다</Badge>}</div>} /></div>

            {/* ── 3 결론의 신뢰도 — 첨부를 다 읽지 못했으면 여기서 말한다 ── */}
            {/* S-9 · 첨부를 다 읽지 못한 경우를 판정과 같은 화면에서 말한다. PARTIAL을 SUCCEEDED처럼 그리면 빠진 조건이 사용자에게 안 보인다. */}
            {currentAnalysis && currentAnalysis.status !== 'SUCCEEDED' && (
              <section className="mt-6 rounded-[18px] border border-[var(--product-warn-line)] bg-[var(--product-warn-soft)] px-5 py-4">
                <strong className="text-[14px] text-[var(--product-warn)]">{ANALYSIS_STATUS_COPY[currentAnalysis.status].label}</strong>
                <p className="mt-1 text-[13px] leading-6 text-[var(--product-body)]">{ANALYSIS_STATUS_COPY[currentAnalysis.status].description}</p>
              </section>
            )}

            {reviewProgress && <section className="mt-6 rounded-[18px] border border-[#d9def7] bg-[#f5f6ff] px-5 py-4"><div className="flex items-center gap-3">{busy === 'review' ? <LoaderCircle className="size-5 animate-spin text-[var(--product-accent)]" /> : <CheckCircle2 className="size-5 text-emerald-600" />}<div><strong className="text-[14px]">{reviewProgress}</strong>{busy === 'review' && <p className="mt-1 text-[12px] text-[var(--product-muted)]">완료되면 새로고침 없이 이 화면에 즉시 결과가 반영됩니다.</p>}</div></div></section>}

            {/* ── 4 물어보기 ── */}
            <ActionCard caseId={activeCase.id} />

            {/* ── 5 왜 그 결론인지 — 요건별 판정과 근거 ── */}
            <section className="mt-9">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><h2 className="text-[25px] font-extrabold tracking-[-0.035em]">참가 자격 (필수)</h2><p className="mt-1 text-[13px] text-[var(--product-muted)]">Canonical Requirement와 공고 원문 Evidence를 기준으로 표시합니다.</p></div><span className="text-[13px] text-[var(--product-muted)]">구조화 {views.length}건 · 판정 {displayJudgment?.judgments.length ?? 0}건</span></div>
              <div className="mt-4 overflow-hidden rounded-[18px] border border-[var(--product-line)] bg-white">
                <div className="hidden min-h-[45px] grid-cols-[152px_minmax(0,1.9fr)_minmax(190px,0.8fr)_170px_160px] items-center bg-[var(--product-tint)] text-[12px] font-semibold text-[var(--product-muted)] lg:grid"><div className="px-3">판정</div><div className="px-3">참가 자격 조건</div><div className="px-3">비교 값 / 판정 근거</div><div className="px-3">근거</div><div className="px-3">조치</div></div>
                {views.length ? views.map(({ requirement, judgment, evidenceLabel }) => {
                  const askable = askableQuestionKeys.has(requirement.requirement_key);
                  const evidenceHref = `/evidence?caseId=${activeCase.id}${requirement.evidence_keys[0] ? `&evidence=${encodeURIComponent(requirement.evidence_keys[0])}` : ''}`;
                  return <QualificationRow key={requirement.requirement_key} status={judgmentStatus(judgment)} basisType={judgment?.basis_type ?? 'NONE'} condition={`${labelOf(REQUIREMENT_TYPE_LABEL, requirement.type)} · ${requirement.raw}`} companyValue={companyValue(requirement, company, judgment)} evidenceLabel={evidenceLabel} actionLabel={judgment?.status === 'UNKNOWN' ? (askable ? '확인하기' : '원문 확인') : judgment ? '판정 완료' : '판정 필요'} onEvidence={requirement.evidence_keys[0] ? () => setSelectedEvidenceKey(requirement.evidence_keys[0]) : undefined} onAction={judgment?.status === 'UNKNOWN' ? () => { router.push(askable ? `/ask-back?caseId=${activeCase.id}` : evidenceHref); } : undefined} />;
                }) : <div className="px-6 py-14 text-center">{busy === 'review' ? <LoaderCircle className="mx-auto size-8 animate-spin text-[var(--product-accent)]" /> : <FileSearch className="mx-auto size-8 text-[var(--product-faint)]" />}<p className="mt-3 text-[14px] font-semibold">{emptyRequirementCopy}</p><Button className="mt-4" onClick={() => void runFullReview(Boolean(analysisDetail))} disabled={busy !== null || actionLocked}>{busy === 'review' ? <LoaderCircle className="animate-spin" /> : <Play />}{analysisDetail ? '새로 분석하고 판정' : '참가자격 검토 시작'}</Button></div>}              </div>
            </section>

            {/* ── 6 판정 밖 조건 — 위 표에 없는 것 ── */}
            {/* P0-5 · 위 표에 없는 조건을 말한다. 이걸 안 그리면 사용자는 빠진 조건이 있는 줄 모른 채 판정을 믿는다 (NFR-1). */}
            <section id="analysis-scope" className={`mt-7 rounded-[20px] border px-6 py-5 ${unjudgedCount > 0 ? 'border-[var(--product-warn-line)] bg-[var(--product-warn-soft)]' : 'border-[var(--product-line)] bg-white'}`}>
                <h2 className="text-[18px] font-extrabold text-[var(--product-ink)]">판정에 들어가지 않은 조건{unjudgedCount > 0 ? ` ${unjudgedCount}건` : ''}</h2>
                <p className="mt-1 text-[13px] leading-6 text-[var(--product-body)]">{unjudgedState === 'NOT_RUN'
                  ? '아직 자격검토를 실행하지 않았습니다. 검토를 실행하면 판정에서 빠진 조건을 여기에 표시합니다.'
                  : unjudgedState === 'FAILED'
                    ? unjudgedCount
                      // 실패했어도 중단 전까지 잡힌 항목은 남는다. 「확인 못 했다」로 끝내면 아래 목록과 말이 어긋난다.
                      ? '분석이 끝나지 않았습니다. 아래는 중단되기 전까지 확인된 항목이라 이 목록이 전부가 아닙니다.'
                      : '분석이 완료되지 않아 판정에서 빠진 조건을 확인하지 못했습니다.'
                    : unjudgedCount
                      ? '아래 항목은 위 표의 판정에 반영되지 않았습니다. 제출 전에 공고 원문에서 직접 확인해 주세요.'
                      : '이번 분석에서 판정 밖으로 빠진 조건이 없습니다.'}</p>

                {previewNoticeFacts.length > 0 && (
                  <div className="mt-4">
                    <strong className="text-[13px] text-[var(--product-warn)]">판정 대상이 아닌 확인사항 {noticeFacts.length}건</strong>
                    {sharedNoticeFactMessage && <p className="mt-1 text-[13px] leading-6 text-[var(--product-body)]">{sharedNoticeFactMessage}</p>}
                    <ul className="mt-2 space-y-2">
                      {/* 무엇이 걸렸는지는 근거 원문으로만 구분된다. 공통 문구는 위에서 한 번 말했다. */}
                      {previewNoticeFacts.map((item, index) => {
                        const evidenceKey = item.evidence_keys[0];
                        const evidence = evidenceKey ? analysisDetail?.evidence.find((row) => row.evidence_key === evidenceKey) ?? null : null;
                        const locationText = evidence ? evidenceLocationText(evidence.location) : null;
                        return (
                          <li key={`${item.code}-${index}`} className="rounded-[14px] border border-[var(--product-line)] bg-white px-4 py-3">
                            {evidence && <p className="text-[13.5px] leading-6 text-[var(--product-ink)]">「{evidence.quote}」</p>}
                            {!sharedNoticeFactMessage && <p className={evidence ? 'mt-1 text-[13px] leading-6 text-[var(--product-body)]' : 'text-[13px] leading-6 text-[var(--product-body)]'}>{item.message}</p>}
                            {locationText && <p className="mt-1 text-[12px] text-[var(--product-muted)]">근거 위치 — {locationText}</p>}
                            {/* evidence_key만 보고 버튼을 띄우면 실제 Evidence가 없을 때 눌러도 아무것도 안 열린다. 객체가 resolve된 경우에만 노출한다. */}
                            {evidence && <Button variant="outline" size="sm" className="mt-2 rounded-full" onClick={() => setSelectedEvidenceKey(evidence.evidence_key)}>근거 원문 보기</Button>}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {previewDropped.length > 0 && (
                  <div className="mt-4">
                    <strong className="text-[13px] text-[var(--product-warn)]">구조화에서 제외된 요건 {droppedRequirements.length}건</strong>
                    <ul className="mt-2 space-y-2">
                      {/* MISSING_RAW는 raw가 비어 있을 수 있다. 빈 따옴표만 남기지 않고 확보하지 못했다고 말한다. */}
                      {previewDropped.map((item, index) => {
                        const raw = item.raw.trim();
                        return (
                          <li key={`${item.reason_code}-${index}`} className="rounded-[14px] border border-[var(--product-line)] bg-white px-4 py-3">
                            {raw
                              ? <p className="text-[13.5px] leading-6 text-[var(--product-ink)]">「{raw}」</p>
                              : <p className="text-[13.5px] leading-6 text-[var(--product-faint)]">원문 문구를 확보하지 못했습니다.</p>}
                            <p className="mt-1 text-[12.5px] text-[var(--product-muted)]">{labelOf(DROPPED_REASON_LABEL, item.reason_code)}</p>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {hiddenUnjudgedCount > 0 && (
                  <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full bg-white" onClick={() => setShowAllUnjudged(true)}>
                    <ChevronDown /> 나머지 {hiddenUnjudgedCount}건 더 보기
                  </Button>
                )}
                {showAllUnjudged && unjudgedCount > UNJUDGED_PREVIEW && (
                  <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full bg-white" onClick={() => setShowAllUnjudged(false)}>
                    <ChevronUp /> 접기
                  </Button>
                )}
            </section>

            {selectedEvidence && <section className="mt-7"><h2 className="mb-3 text-[20px] font-extrabold">선택한 원문 근거</h2><EvidenceQuote quote={selectedEvidence.quote} location={selectedEvidence.location} /></section>}

            {/* ── 7 분석 완전성 · 변경공고 재검증 ── */}
            <section className="mt-9 grid gap-5 lg:grid-cols-2">
              <div className="rounded-[20px] border border-[var(--product-line)] p-6"><h2 className="text-[20px] font-extrabold">분석 완전성</h2><p className="mt-2 text-[13px] leading-6 text-[var(--product-muted)]">분석 실행 상태와 diagnostic을 판정 결과와 분리해서 관리합니다.</p><div className="mt-5 flex flex-wrap gap-3"><Badge variant="outline">상태 {analysisDetail?.status ?? '미실행'}</Badge><Badge variant="outline">Requirement {countedAnalysis ? countedAnalysis.requirements.length : '-'}</Badge><Badge variant="outline">Evidence {countedAnalysis ? countedAnalysis.evidence.length : '-'}</Badge></div>{pipelineDiagnostics.length ? <div className="mt-4 space-y-2">{pipelineDiagnostics.map((item, index) => <p key={`${item.code}-${index}`} className="rounded-xl bg-amber-50 px-3 py-2 text-[12px] text-amber-800">{item.code} · {item.message}</p>)}</div> : null}</div>
              <div className="rounded-[20px] border border-[var(--product-line)] p-6"><h2 className="text-[20px] font-extrabold">변경공고 영향 재검증</h2><p className="mt-2 text-[13px] leading-6 text-[var(--product-muted)]">기준 차수와 현재 차수가 모두 있으면 변경된 Canonical Requirement만 다시 판정합니다.</p><Button className="mt-5" variant="outline" onClick={() => void controller.propose(activeCase.id, true)} disabled={!canRevalidate || busy !== null || actionLocked}>{actionLocked ? <LoaderCircle className="animate-spin" /> : <GitCompareArrows />} 전체 변경 요건 재검증 제안</Button>{revalidation && <p className="mt-4 text-[13px]">재판정된 Requirement <strong>{revalidation.revalidated_keys.length}건</strong></p>}</div>
            </section>

            {/* ── 8 판정에 쓴 입력값 ── */}
            <section className="mt-7 grid gap-4 lg:grid-cols-3">
              <div className="rounded-[18px] border border-[var(--product-line)] p-5"><span className="text-[12px] text-[var(--product-muted)]">회사 프로필</span><strong className="mt-1 block text-[16px]">{company?.name ?? '미연결'}</strong><p className="mt-2 text-[12px] text-[var(--product-muted)]">{company?.region_name ?? '-'} · {labelOf(COMPANY_SIZE_LABEL, company?.company_size)}</p></div>
              <div className="rounded-[18px] border border-[var(--product-line)] p-5"><span className="text-[12px] text-[var(--product-muted)]">자격요건 분석</span><strong className="mt-1 block text-[16px]">{currentAnalysis?.requirement_count != null ? `${currentAnalysis.requirement_count}건 구조화` : '분석 전'}</strong><p className="mt-2 text-[12px] text-[var(--product-muted)]">Evidence {currentAnalysis?.evidence_count ?? 0}건 · {analysisNeedsRetry ? '재분석 권장' : currentAnalysis ? '사용 가능' : '미실행'}</p></div>
              <div className="rounded-[18px] border border-[var(--product-line)] p-5"><span className="text-[12px] text-[var(--product-muted)]">확인 필요</span><strong className="mt-1 block text-[16px]">{unknown}건</strong><p className="mt-2 text-[12px] text-[var(--product-muted)]">사용자 질문 가능 {questions.filter((item) => item.askable).length}건</p></div>
            </section>

            {/* ── 9 공고 원본 정보 ── */}
            <QualificationSourceOverview caseItem={activeCase} notice={selectedNotice} version={currentVersion} />

            <section className="mt-9 rounded-[20px] border border-[var(--product-line)] bg-[var(--product-tint)] p-5"><div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><h2 className="text-[18px] font-extrabold">다른 검토 건</h2><p className="mt-1 text-[12px] text-[var(--product-muted)]">선택한 공고의 Case로 정확히 이동합니다.</p></div><NativeSelect className="sm:w-[420px]" value={activeCase.id} onChange={(event) => router.push(`/qualification?caseId=${encodeURIComponent(event.target.value)}`)}>{cases.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.bid_notice_no} · {item.title}</NativeSelectOption>)}</NativeSelect></div></section>
          </>
        )}
      </div>
    </main>
  );
}
