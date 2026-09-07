'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, GitCompareArrows, LoaderCircle, Play, RefreshCw } from 'lucide-react';

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
  answerQualificationQuestion,
  createPreflightCaseWithCompany,
  getQualificationJudgment,
  listCompanies,
  listQualificationAnalyses,
  listQualificationJudgments,
  listQualificationQuestions,
  runQualificationAnalysis,
  runQualificationJudgment,
  runQualificationRevalidation,
  type CompanyProfile,
  type QualificationAnalysisSummary,
  type QualificationJudgmentRun,
  type QualificationQuestion,
  type QualificationRevalidation,
} from '@/lib/qualification-api';

type Busy = 'load' | 'create' | 'analysis' | 'judgment' | 'answer' | 'revalidation' | null;

function overallLabel(status: QualificationJudgmentRun['overall_status'] | undefined) {
  if (status === 'eligible') return '참가 가능';
  if (status === 'ineligible') return '참가 불가';
  if (status === 'insufficient_data') return '정보 확인 필요';
  return '미판정';
}

function judgmentLabel(status: string) {
  if (status === 'SATISFIED') return '충족';
  if (status === 'UNSATISFIED') return '미달';
  if (status === 'UNKNOWN') return '확인 필요';
  return status;
}

function judgmentBadge(status: string): 'default' | 'destructive' | 'secondary' | 'outline' {
  if (status === 'SATISFIED') return 'default';
  if (status === 'UNSATISFIED') return 'destructive';
  if (status === 'UNKNOWN') return 'secondary';
  return 'outline';
}

export default function QualificationIntegrationPage() {
  const [notices, setNotices] = useState<BidNoticeSummary[]>([]);
  const [companies, setCompanies] = useState<CompanyProfile[]>([]);
  const [cases, setCases] = useState<PreflightCase[]>([]);
  const [noticeId, setNoticeId] = useState('');
  const [companyId, setCompanyId] = useState('');
  const [activeCase, setActiveCase] = useState<PreflightCase | null>(null);
  const [versions, setVersions] = useState<BidNoticeVersion[]>([]);
  const [baselineAnalysis, setBaselineAnalysis] = useState<QualificationAnalysisSummary | null>(null);
  const [currentAnalysis, setCurrentAnalysis] = useState<QualificationAnalysisSummary | null>(null);
  const [sourceJudgment, setSourceJudgment] = useState<QualificationJudgmentRun | null>(null);
  const [displayJudgment, setDisplayJudgment] = useState<QualificationJudgmentRun | null>(null);
  const [questions, setQuestions] = useState<QualificationQuestion[]>([]);
  const [revalidation, setRevalidation] = useState<QualificationRevalidation | null>(null);
  const [busy, setBusy] = useState<Busy>('load');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const selectedNotice = useMemo(
    () => notices.find((item) => item.id === noticeId) ?? null,
    [noticeId, notices],
  );
  const baselineVersion = useMemo(
    () => versions.find((item) => item.version_number === activeCase?.baseline_version_number) ?? null,
    [activeCase, versions],
  );
  const currentVersion = useMemo(
    () => versions.find((item) => item.version_number === activeCase?.current_version_number) ?? null,
    [activeCase, versions],
  );

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
      selected.baseline_version_number
        ? listQualificationAnalyses(selected.notice_id, selected.baseline_version_number)
        : Promise.resolve([]),
      listQualificationJudgments(selected.id),
    ]);
    setCurrentAnalysis(currentAnalyses[0] ?? null);
    setBaselineAnalysis(baselineAnalyses[0] ?? null);

    const baselineVersionId = fetchedVersions.find(
      (item) => item.version_number === selected.baseline_version_number,
    )?.id;
    const currentVersionId = fetchedVersions.find(
      (item) => item.version_number === selected.current_version_number,
    )?.id;
    const baselineSummary = baselineVersionId
      ? judgmentSummaries.find((item) => item.notice_version_id === baselineVersionId)
      : null;
    const latestSummary = judgmentSummaries[0] ?? null;
    const sourceSummary = baselineSummary ?? latestSummary;
    const displaySummary =
      judgmentSummaries.find((item) => item.notice_version_id === currentVersionId) ?? latestSummary;

    const [source, display] = await Promise.all([
      sourceSummary ? getQualificationJudgment(sourceSummary.id) : Promise.resolve(null),
      displaySummary ? getQualificationJudgment(displaySummary.id) : Promise.resolve(null),
    ]);
    setSourceJudgment(source);
    setDisplayJudgment(display);
    setQuestions(
      source ? await listQualificationQuestions(selected.id, source.id) : [],
    );
  }

  async function initialize() {
    setBusy('load');
    setError('');
    try {
      const [noticeResult, companyResult, caseResult] = await Promise.all([
        listNotices(),
        listCompanies(),
        listPreflightCases(),
      ]);
      setNotices(noticeResult.items);
      setCompanies(companyResult);
      setCases(caseResult.items);
      setNoticeId(noticeResult.items[0]?.id ?? '');
      setCompanyId(companyResult[0]?.id ?? '');
      if (caseResult.items[0]) await hydrateCase(caseResult.items[0].id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '초기 데이터를 불러오지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function createCase() {
    if (!selectedNotice || !companyId) return;
    setBusy('create');
    setError('');
    setMessage('');
    try {
      const fetchedVersions = await getNoticeVersions(selectedNotice.id);
      const current = fetchedVersions.find((item) => item.is_current) ?? fetchedVersions[0];
      if (!current) throw new Error('공고 버전을 찾을 수 없습니다.');
      const baseline = fetchedVersions
        .filter((item) => item.version_number < current.version_number)
        .sort((a, b) => b.version_number - a.version_number)[0];
      const created = await createPreflightCaseWithCompany({
        notice_id: selectedNotice.id,
        company_id: companyId,
        baseline_version_number: baseline?.version_number,
        current_version_number: current.version_number,
        title: `${selectedNotice.bid_notice_no} 자격 검토`,
      });
      const refreshed = await listPreflightCases();
      setCases(refreshed.items);
      await hydrateCase(created.id);
      setMessage('회사 프로필과 공고를 연결한 검토 건을 만들었습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function ensureAnalysis(versionNumber: number) {
    const existing = await listQualificationAnalyses(activeCase!.notice_id, versionNumber);
    if (existing[0]) return existing[0];
    const created = await runQualificationAnalysis(activeCase!.notice_id, versionNumber);
    return created.run;
  }

  async function prepareAnalyses() {
    if (!activeCase) return;
    setBusy('analysis');
    setError('');
    setMessage('');
    try {
      const [baseline, current] = await Promise.all([
        activeCase.baseline_version_number
          ? ensureAnalysis(activeCase.baseline_version_number)
          : Promise.resolve(null),
        ensureAnalysis(activeCase.current_version_number),
      ]);
      setBaselineAnalysis(baseline);
      setCurrentAnalysis(current);
      setMessage('자격요건 분석 결과가 준비됐습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '자격요건 분석에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function runInitialJudgment() {
    if (!activeCase) return;
    const targetAnalysis = activeCase.baseline_version_number ? baselineAnalysis : currentAnalysis;
    if (!targetAnalysis) {
      setError('먼저 공고 자격요건 분석을 준비하세요.');
      return;
    }
    setBusy('judgment');
    setError('');
    setMessage('');
    try {
      const result = await runQualificationJudgment(activeCase.id, targetAnalysis.id);
      setSourceJudgment(result);
      setDisplayJudgment(result);
      setQuestions(await listQualificationQuestions(activeCase.id, result.id));
      setMessage('회사 프로필 기준 자격 판정을 완료했습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '자격 판정에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function answer(question: QualificationQuestion, satisfies: boolean) {
    if (!activeCase || !sourceJudgment) return;
    setBusy('answer');
    setError('');
    try {
      const answered = await answerQualificationQuestion(activeCase.id, {
        source_judgment_run_id: sourceJudgment.id,
        requirement_key: question.requirement_key,
        satisfies_requirement: satisfies,
        normalized_value: satisfies ? question.raw_requirement : undefined,
        evidence_held: satisfies,
      });
      setSourceJudgment(answered.result);
      setDisplayJudgment(answered.result);
      setQuestions(await listQualificationQuestions(activeCase.id, answered.result.id));
      setMessage('답변한 조건만 부분 재판정했습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '답변 저장에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function revalidate() {
    if (!activeCase || !sourceJudgment || !baselineAnalysis || !currentAnalysis) return;
    setBusy('revalidation');
    setError('');
    setMessage('');
    try {
      const result = await runQualificationRevalidation(activeCase.id, {
        source_judgment_run_id: sourceJudgment.id,
        baseline_analysis_run_id: baselineAnalysis.id,
        current_analysis_run_id: currentAnalysis.id,
      });
      setRevalidation(result);
      setDisplayJudgment(result.result);
      setMessage(`변경 조건 ${result.revalidated_keys.length}개를 다시 판정했습니다.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '변경공고 재검증에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  const canRevalidate = Boolean(
    activeCase?.baseline_version_number &&
      baselineAnalysis &&
      currentAnalysis &&
      sourceJudgment &&
      baselineVersion &&
      sourceJudgment.notice_version_id === baselineVersion.id,
  );

  return (
    <main className="min-h-screen bg-background p-4 text-foreground md:p-6">
      <div className="mx-auto max-w-7xl space-y-4">
        <header className="flex flex-col justify-between gap-3 rounded-xl border bg-card p-4 md:flex-row md:items-center">
          <div>
            <div className="flex items-center gap-2">
              <Badge variant="outline">MVP Integration</Badge>
              <span className="text-xs text-muted-foreground">Qualification Vertical Slice</span>
            </div>
            <h1 className="mt-2 text-xl font-semibold">참가 자격 판정 · 실제 API 연결</h1>
            <p className="mt-1 text-sm text-muted-foreground">분석 → 판정 → 확인 질문 → 변경공고 재검증을 한 화면에서 검증합니다.</p>
          </div>
          <Button variant="outline" onClick={() => void initialize()} disabled={busy !== null}>
            <RefreshCw className={busy === 'load' ? 'animate-spin' : ''} /> 새로고침
          </Button>
        </header>

        {(error || message) && (
          <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${error ? 'border-destructive/30 bg-destructive/5 text-destructive' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>
            {error ? <AlertCircle className="size-4" /> : <CheckCircle2 className="size-4" />}
            {error || message}
          </div>
        )}

        <section className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="space-y-5 rounded-xl border bg-card p-4">
            <div>
              <h2 className="text-sm font-semibold">새 검토 건</h2>
              <label className="mt-3 block text-xs text-muted-foreground">회사 프로필</label>
              <NativeSelect className="mt-1 w-full" value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
                {!companies.length && <NativeSelectOption value="">회사 없음</NativeSelectOption>}
                {companies.map((company) => <NativeSelectOption key={company.id} value={company.id}>{company.name} · {company.region_name ?? '-'}</NativeSelectOption>)}
              </NativeSelect>
              <label className="mt-3 block text-xs text-muted-foreground">공고</label>
              <NativeSelect className="mt-1 w-full" value={noticeId} onChange={(event) => setNoticeId(event.target.value)}>
                {!notices.length && <NativeSelectOption value="">공고 없음</NativeSelectOption>}
                {notices.map((notice) => <NativeSelectOption key={notice.id} value={notice.id}>{notice.bid_notice_no} · {notice.title}</NativeSelectOption>)}
              </NativeSelect>
              <Button className="mt-3 w-full" onClick={() => void createCase()} disabled={!companyId || !noticeId || busy !== null}>검토 건 만들기</Button>
            </div>

            <div className="border-t pt-4">
              <h2 className="mb-2 text-sm font-semibold">검토 건 목록</h2>
              <div className="max-h-80 space-y-2 overflow-y-auto">
                {cases.map((item) => (
                  <button key={item.id} type="button" onClick={() => void hydrateCase(item.id)} className={`w-full rounded-lg border p-3 text-left text-sm ${activeCase?.id === item.id ? 'border-primary bg-primary/5' : ''}`}>
                    <strong className="block truncate">{item.title}</strong>
                    <span className="mt-1 block text-xs text-muted-foreground">v{item.baseline_version_number ?? '-'} → v{item.current_version_number} · {item.company_id ? '회사 연결' : '회사 미연결'}</span>
                  </button>
                ))}
              </div>
            </div>
          </aside>

          <div className="space-y-4">
            <section className="rounded-xl border bg-card p-4">
              <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
                <div>
                  <span className="text-xs font-medium text-muted-foreground">01 · Analysis</span>
                  <h2 className="mt-1 font-semibold">공고 자격요건 분석</h2>
                  <p className="mt-1 text-sm text-muted-foreground">baseline/current 공고를 Canonical Requirement로 구조화합니다.</p>
                </div>
                <Button onClick={() => void prepareAnalyses()} disabled={!activeCase || busy !== null}>
                  {busy === 'analysis' ? <LoaderCircle className="animate-spin" /> : <Play />} 분석 준비
                </Button>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border p-3"><span className="text-xs text-muted-foreground">기준 공고</span><p className="mt-1 text-sm font-medium">{activeCase?.baseline_version_number ? `v${activeCase.baseline_version_number}` : '없음'} · {baselineAnalysis?.status ?? '-'}</p><p className="mt-1 text-xs text-muted-foreground">Requirement {baselineAnalysis?.requirement_count ?? 0}개</p></div>
                <div className="rounded-lg border p-3"><span className="text-xs text-muted-foreground">현재 공고</span><p className="mt-1 text-sm font-medium">{activeCase ? `v${activeCase.current_version_number}` : '-'} · {currentAnalysis?.status ?? '-'}</p><p className="mt-1 text-xs text-muted-foreground">Requirement {currentAnalysis?.requirement_count ?? 0}개</p></div>
              </div>
            </section>

            <section className="rounded-xl border bg-card p-4">
              <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
                <div>
                  <span className="text-xs font-medium text-muted-foreground">02 · Judgment</span>
                  <h2 className="mt-1 font-semibold">회사 프로필 자격 판정</h2>
                  <p className="mt-1 text-sm text-muted-foreground">LLM이 아니라 결정적 규칙으로 SATISFIED / UNSATISFIED / UNKNOWN을 계산합니다.</p>
                </div>
                <Button variant="outline" onClick={() => void runInitialJudgment()} disabled={!activeCase || busy !== null}>
                  {busy === 'judgment' ? <LoaderCircle className="animate-spin" /> : <CheckCircle2 />} {activeCase?.baseline_version_number ? '기준 판정' : '현재 판정'}
                </Button>
              </div>

              <div className="mt-4 rounded-xl border p-4">
                <div className="flex items-center justify-between gap-3">
                  <div><span className="text-xs text-muted-foreground">종합 결과</span><p className="mt-1 text-lg font-semibold">{overallLabel(displayJudgment?.overall_status)}</p></div>
                  {displayJudgment && <Badge variant={displayJudgment.overall_status === 'ineligible' ? 'destructive' : displayJudgment.overall_status === 'eligible' ? 'default' : 'secondary'}>{displayJudgment.overall_status}</Badge>}
                </div>
                <div className="mt-4 space-y-2">
                  {displayJudgment?.judgments.map((item) => (
                    <div key={item.requirement_key} className="flex items-center justify-between gap-3 rounded-lg bg-muted/60 px-3 py-2 text-sm">
                      <div className="min-w-0"><strong className="block truncate">{item.requirement_key}</strong><span className="text-xs text-muted-foreground">{item.basis_type} · {item.reason_code}</span></div>
                      <Badge variant={judgmentBadge(item.status)}>{judgmentLabel(item.status)}</Badge>
                    </div>
                  )) ?? <p className="text-sm text-muted-foreground">아직 판정 결과가 없습니다.</p>}
                </div>
              </div>
            </section>

            <section className="rounded-xl border bg-card p-4">
              <div><span className="text-xs font-medium text-muted-foreground">03 · Ask-back</span><h2 className="mt-1 font-semibold">확인 필요 정보</h2></div>
              <div className="mt-4 space-y-3">
                {questions.map((question) => (
                  <div key={question.requirement_key} className="rounded-lg border p-3">
                    <p className="text-sm font-medium">{question.question}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{question.raw_requirement}</p>
                    <div className="mt-3 flex gap-2"><Button size="sm" onClick={() => void answer(question, true)} disabled={busy !== null}>예, 충족합니다</Button><Button size="sm" variant="outline" onClick={() => void answer(question, false)} disabled={busy !== null}>아니요</Button></div>
                  </div>
                ))}
                {!questions.length && <p className="text-sm text-muted-foreground">UNKNOWN 조건이 없거나 아직 기준 판정을 실행하지 않았습니다.</p>}
              </div>
            </section>

            <section className="rounded-xl border bg-card p-4">
              <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
                <div><span className="text-xs font-medium text-muted-foreground">04 · Change Revalidation</span><h2 className="mt-1 font-semibold">변경공고 영향 재검증</h2><p className="mt-1 text-sm text-muted-foreground">Canonical Diff로 바뀐 조건만 다시 판정합니다.</p></div>
                <Button variant="outline" onClick={() => void revalidate()} disabled={!canRevalidate || busy !== null}>{busy === 'revalidation' ? <LoaderCircle className="animate-spin" /> : <GitCompareArrows />} 변경 재검증</Button>
              </div>
              {revalidation ? (
                <div className="mt-4 space-y-2">
                  <p className="text-sm">실제 재판정: <strong>{revalidation.revalidated_keys.length}개</strong></p>
                  {revalidation.changes.filter((item) => item.change_type !== 'UNCHANGED').map((item) => <div key={item.identity} className="flex justify-between rounded-lg bg-muted px-3 py-2 text-sm"><span>{item.current_key ?? item.baseline_key}</span><Badge variant="outline">{item.change_type}</Badge></div>)}
                </div>
              ) : <p className="mt-4 text-sm text-muted-foreground">baseline과 current가 모두 있고 기준 판정이 준비되면 실행할 수 있습니다.</p>}
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
