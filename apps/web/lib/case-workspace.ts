import {
  getNotice,
  getNoticeVersions,
  getPreflightCase,
  type BidNoticeDetail,
  type BidNoticeVersion,
  type PreflightCase,
} from '@/lib/api';
import {
  getQualificationAnalysis,
  getQualificationJudgment,
  listCompanies,
  listQualificationAnalyses,
  listQualificationJudgments,
  listQualificationQuestions,
  type CompanyProfile,
  type QualificationAnalysisRun,
  type QualificationAnalysisSummary,
  type QualificationJudgmentRun,
  type QualificationQuestion,
} from '@/lib/qualification-api';

export type CaseWorkspace = {
  caseItem: PreflightCase;
  notice: BidNoticeDetail;
  versions: BidNoticeVersion[];
  company: CompanyProfile | null;
  baselineAnalysis: QualificationAnalysisSummary | null;
  currentAnalysis: QualificationAnalysisSummary | null;
  currentAnalysisDetail: QualificationAnalysisRun | null;
  sourceJudgment: QualificationJudgmentRun | null;
  displayJudgment: QualificationJudgmentRun | null;
  questions: QualificationQuestion[];
};

export async function loadCaseWorkspace(caseId: string): Promise<CaseWorkspace> {
  const caseItem = await getPreflightCase(caseId);
  const [notice, versions, companies, currentAnalyses, baselineAnalyses, judgmentSummaries] =
    await Promise.all([
      getNotice(caseItem.notice_id),
      getNoticeVersions(caseItem.notice_id),
      listCompanies(),
      listQualificationAnalyses(caseItem.notice_id, caseItem.current_version_number),
      caseItem.baseline_version_number
        ? listQualificationAnalyses(caseItem.notice_id, caseItem.baseline_version_number)
        : Promise.resolve([]),
      listQualificationJudgments(caseItem.id),
    ]);

  const currentAnalysis = currentAnalyses[0] ?? null;
  const baselineAnalysis = baselineAnalyses[0] ?? null;
  const currentAnalysisDetail = currentAnalysis
    ? await getQualificationAnalysis(currentAnalysis.id)
    : null;

  const baselineVersionId = versions.find(
    (item) => item.version_number === caseItem.baseline_version_number,
  )?.id;
  const currentVersionId = versions.find(
    (item) => item.version_number === caseItem.current_version_number,
  )?.id;
  const baselineSummary = baselineVersionId
    ? judgmentSummaries.find((item) => item.notice_version_id === baselineVersionId)
    : null;
  const latestSummary = judgmentSummaries[0] ?? null;
  const sourceSummary = baselineSummary ?? latestSummary;
  const displaySummary =
    judgmentSummaries.find((item) => item.notice_version_id === currentVersionId) ?? latestSummary;

  const [sourceJudgment, displayJudgment] = await Promise.all([
    sourceSummary ? getQualificationJudgment(sourceSummary.id) : Promise.resolve(null),
    displaySummary ? getQualificationJudgment(displaySummary.id) : Promise.resolve(null),
  ]);

  const questions = sourceJudgment
    ? await listQualificationQuestions(caseItem.id, sourceJudgment.id)
    : [];

  return {
    caseItem,
    notice,
    versions,
    company: companies.find((item) => item.id === caseItem.company_id) ?? null,
    baselineAnalysis,
    currentAnalysis,
    currentAnalysisDetail,
    sourceJudgment,
    displayJudgment,
    questions,
  };
}

export function currentVersion(workspace: CaseWorkspace) {
  return (
    workspace.versions.find(
      (item) => item.version_number === workspace.caseItem.current_version_number,
    ) ?? workspace.notice.latest
  );
}

export function baselineVersion(workspace: CaseWorkspace) {
  return workspace.caseItem.baseline_version_number
    ? workspace.versions.find(
        (item) => item.version_number === workspace.caseItem.baseline_version_number,
      ) ?? null
    : null;
}

export function workspaceHref(path: string, caseId: string) {
  return `${path}?caseId=${encodeURIComponent(caseId)}`;
}
