'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { graphOptions, graphRuns, analyzeGraph, judgeGraph, compareGraphs,
  type GraphList, type GraphComparison, type GraphJudgment, type GraphSide } from '@/lib/qualification-graph-api';

const labels: Record<string,string> = { UNCHANGED:'변경 없음', TEXT_CHANGED:'원문 변경·구조화 의미 동일', MODIFIED:'조건 변경',
  ADDED:'요건 추가', REMOVED:'요건 삭제', SOURCE_ADDED:'원문 추가', SOURCE_REMOVED:'원문 삭제',
  REVIEW_REQUIRED:'확인 필요', ANALYSIS_INCONSISTENCY:'분석 불일치', RELATION_CHANGED:'조건 관계 변경' };
function Side({ title, side }: { title: string; side: GraphSide | null }) {
  return <div className="min-w-0 rounded-xl bg-slate-50 p-4"><h3 className="font-bold">{title}</h3>
    <p className="mt-2 whitespace-pre-wrap break-words text-sm">{side?.quote ?? '대응 원문이 없습니다. 이 사실만으로 요건 추가·삭제를 확정하지 않습니다.'}</p>
    {side && <p className="mt-2 text-xs text-slate-600">블록 {side.block_index} · {side.meaning?.status ?? '처리 누락'} · {side.meaning?.pending_codes.join(', ') || '미해결 코드 없음'}</p>}
    {!!side?.meaning?.predicates.length && <details className="mt-2 text-sm"><summary className="cursor-pointer">구조화된 조건 보기</summary><pre className="overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(side.meaning.predicates,null,2)}</pre></details>}
  </div>;
}
export default function GraphPage() {
  const caseId = useSearchParams().get('caseId');
  return caseId ? <Workspace key={caseId} caseId={caseId} /> : <main className="app-shell-container py-10">검토 건을 먼저 선택해 주세요. <Link href="/notices" className="underline">공고 찾기</Link></main>;
}
function Workspace({caseId}:{caseId:string}) {
  const [data,setData] = useState<GraphList|null>(null);
  const [enabled,setEnabled] = useState(false), [busy,setBusy] = useState(false);
  const [before,setBefore] = useState(''), [after,setAfter] = useState('');
  const [day,setDay] = useState('');
  const [comparison,setComparison] = useState<GraphComparison|null>(null);
  const [judgment,setJudgment] = useState<GraphJudgment|null>(null);
  const [error,setError] = useState(''), [message,setMessage] = useState('');
  const generation = useRef(0), active = useRef<AbortController|null>(null);
  const begin = () => { active.current?.abort(); active.current=new AbortController(); return {n:++generation.current,signal:active.current.signal}; };
  const refresh = useCallback(async () => {
    const job=begin();setBusy(true);setError('');setComparison(null);setJudgment(null);
    try {
      const [options,runs]=await Promise.all([graphOptions(job.signal),graphRuns(caseId,job.signal)]);
      if(job.n!==generation.current)return;
      setEnabled(options.enabled);setData(runs);
      setBefore(old=>runs.items.some(r=>r.id===old)?old:'');setAfter(old=>runs.items.some(r=>r.id===old)?old:'');
    } catch(e) { if(job.n===generation.current){setData(null);setEnabled(false);setError(e instanceof Error?e.message:'조회에 실패했습니다.');} }
    finally {if(job.n===generation.current)setBusy(false);}
  },[caseId]);
  useEffect(()=>{void refresh();return()=>{++generation.current;active.current?.abort();};},[refresh]);
  async function run(kind:'baseline'|'current'|'judge'|'compare') {
    if(busy)return;
    const job=begin();setBusy(true);setError('');setMessage('');setComparison(null);setJudgment(null);
    let savedId:string|null=null;
    try {
      if(kind==='compare') {
        const result=await compareGraphs(caseId,before,after,job.signal);
        if(job.n===generation.current)setComparison(result);
      } else if(kind==='judge') {
        const result=await judgeGraph(caseId,after,day,job.signal);savedId=result.id;
        if(job.n===generation.current){setJudgment(result);setMessage('선택한 공고 그래프를 재사용해 회사 판정을 저장했습니다. 공고는 재분석하지 않았습니다.');}
      } else {
        const result=await analyzeGraph(caseId,kind,job.signal);savedId=result.id;
        const runs=await graphRuns(caseId,job.signal);
        if(job.n!==generation.current)return;
        setData(runs);if(kind==='baseline')setBefore(result.id);else setAfter(result.id);
        setMessage(`그래프 분석을 저장했습니다. 실행 ${result.id} · ${result.status}. 기존 슬롯 판정과는 별도 결과입니다.`);
      }
    } catch(e) {if(job.n===generation.current)setError(`${e instanceof Error?e.message:'요청 오류'}${kind==='compare'?'':savedId?` 저장 응답은 확인했습니다 (${savedId}). 목록 조회만 다시 해주세요.`:' 요청의 저장 여부는 목록에서 확인해 주세요. 자동 재전송하지 않았습니다.'}`);}
    finally {if(job.n===generation.current)setBusy(false);}
  }
  const changed = comparison?.changes.filter(c=>c.change_type!=='UNCHANGED') ?? [];
  return <main className="app-shell-container py-10">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-bold">조건 그래프 · 변경 비교</h1>
      <p className="mt-2 text-sm text-slate-600">원문 → 조건 관계 → 저장 → 회사 판정 → 두 실행 비교. Copilot은 연결하지 않았습니다.</p></div>
      <Link className="underline" href={`/qualification?caseId=${encodeURIComponent(caseId)}`}>참가자격 화면</Link></div>
    <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">실험 경로입니다. 분석 정확도는 별도 검증이 필요하며, 예외·추가 문서가 미해결이면 확인 필요로 남습니다. 기존 저장 판정은 덮어쓰지 않습니다.</p>
    {error && <p role="alert" className="mt-4 whitespace-pre-wrap rounded-xl border border-red-200 p-4 text-red-700">{error}</p>}
    {message && <p role="status" className="mt-4 rounded-xl bg-slate-50 p-4">{message}</p>}
    <section className="mt-6 rounded-2xl border p-5" aria-label="그래프 실행">
      <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={()=>void refresh()}>저장 목록만 조회</Button>
        <Button disabled={busy||!enabled||!data?.baseline_version_id} onClick={()=>void run('baseline')}>기준 차수 그래프 분석</Button>
        <Button disabled={busy||!enabled||!data} onClick={()=>void run('current')}>현재 차수 그래프 분석</Button></div>
      {!enabled && <p className="mt-3 text-sm">서버의 그래프 실행이 비활성 또는 미확인입니다. 분석 옵션과 마이그레이션을 확인해 주세요.</p>}
      <p className="mt-3 text-sm text-slate-600">분석 버튼은 모델 호출 비용과 새 저장 실행을 만듭니다. ‘저장 목록만 조회’와 ‘변경 비교’는 모델을 호출하거나 판정을 저장하지 않습니다.</p>
      {data?.more_may_exist && <p className="mt-2 text-sm text-amber-800">최근 {data.limit}건만 표시합니다. 이 목록이 전체 이력은 아닐 수 있습니다.</p>}
    </section>
    <section className="mt-6 rounded-2xl border p-5" aria-label="저장 그래프 선택">
      <div className="grid gap-4 md:grid-cols-2">{([['이전 분석',before,setBefore],['현재 분석',after,setAfter]] as const).map(([label,value,setter])=><label key={label} className="min-w-0 text-sm font-medium">{label}<NativeSelect aria-label={label} value={value} disabled={busy} onChange={e=>{setter(e.target.value);setComparison(null);setJudgment(null);}}><NativeSelectOption value="">실행을 직접 선택해 주세요</NativeSelectOption>{data?.items.map(r=><NativeSelectOption key={r.id} value={r.id}>{r.notice_version_id===data.current_version_id?'현재 차수':'기준 차수'} · {r.status} · {r.id.slice(0,8)} · {r.created_at}</NativeSelectOption>)}</NativeSelect></label>)}</div>
      <div className="mt-4 flex flex-wrap items-end gap-3"><Button disabled={busy||!before||!after||before===after} onClick={()=>void run('compare')}>저장된 두 실행 변경 비교</Button>
        <label className="text-sm">회사 판정 기준일<input aria-label="회사 판정 기준일" type="date" value={day} onChange={e=>{setDay(e.target.value);setJudgment(null);}} className="ml-2 rounded border p-2" disabled={busy}/></label>
        <Button variant="outline" disabled={busy||!enabled||!after||!day} onClick={()=>void run('judge')}>현재 선택 그래프로 회사 판정</Button></div>
      <p className="mt-2 text-sm text-slate-600">같은 차수의 서로 다른 실행도 비교할 수 있습니다. 원문은 같고 해석만 다르면 공고 변경이 아닌 분석 불일치로 표시합니다.</p>
    </section>
    {busy&&<p role="status" className="mt-4">요청을 처리하고 있습니다. 중복 실행하지 마세요.</p>}
    {judgment&&<section className="mt-6 rounded-2xl border p-5"><h2 className="font-bold">저장한 회사 판정: {({eligible:'응찰 가능',ineligible:'자격 미달',insufficient_data:'확인 필요'} as Record<string,string>)[judgment.result.overall_status]??judgment.result.overall_status}</h2><p className="mt-2 text-sm">기준일 {judgment.result.reference_date} · 그래프 {judgment.graph_run_id} · 전체 원문 입력 {judgment.result.source_complete?'확보':'미완전'} · 관계 {judgment.result.relation_status}</p><p className="mt-2 text-sm text-slate-600">저장 시점 회사와 그래프 기준의 결과입니다. 실제 입찰 적격성을 보증하지 않습니다.</p><details className="mt-3"><summary>조건별 판정 보기</summary><pre className="max-h-96 overflow-auto text-xs">{JSON.stringify(judgment.result.clause_results,null,2)}</pre></details></section>}
    {comparison&&<section className="mt-6" aria-label="그래프 변경 비교 결과"><h2 className="text-xl font-bold">{comparison.comparison_status==='COMPLETE'?'비교 처리 완료':'확인할 비교 항목이 있습니다'}</h2><p className="mt-2">조건 관계: {labels[comparison.relation_change]??comparison.relation_change} · 정규화한 원문 {comparison.same_source_text?'동일':'차이 또는 미확인'}</p><p className="mt-2 text-sm text-slate-600">추출 의미의 정확성이나 변경으로 인한 최종 자격 변화를 이 비교만으로 확정하지 않습니다.</p>{comparison.issues.length>0&&<p className="mt-2 break-words text-sm text-amber-800">{comparison.issues.join(' · ')}</p>}
      <p className="mt-3 text-sm">전체 비교 단위 {comparison.changes.length}개 · 변경·확인 대상 {changed.length}개</p>
      {changed.map(c=><article key={c.id} className="mt-4 rounded-2xl border p-4"><h3 className="font-bold">{labels[c.change_type]??c.change_type}</h3>{c.reason_code&&<p className="mt-1 text-xs text-slate-600">{c.reason_code}</p>}<div className="mt-3 grid gap-3 md:grid-cols-2"><Side title="이전 원문" side={c.before}/><Side title="현재 원문" side={c.after}/></div></article>)}
      <details className="mt-4 rounded-xl border p-4"><summary>저장된 전체 관계와 변경 없음 항목 확인</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({before:comparison.baseline_relations,after:comparison.current_relations,unchanged:comparison.changes.filter(c=>c.change_type==='UNCHANGED')},null,2)}</pre></details></section>}
  </main>;
}
