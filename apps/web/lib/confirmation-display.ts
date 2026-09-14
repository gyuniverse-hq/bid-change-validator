// Display only a recognized, complete contract; never interpret arbitrary JSON as eligibility.
export function confirmationDisplay(value: string | null) {
  try {
    const parsed = JSON.parse(value ?? '');
    if (typeof parsed.basis !== 'string' || !parsed.answers || Object.keys(parsed).sort().join() !== 'answers,basis') return null;
    const visit = { site_visited: '현장 방문 완료', visit_certificate: '현장 방문 확인서 제출' };
    const transport = { disposal_permit: '처분·재활용업 허가 보유', legal_transport_permission: '직접 운반의 법적 허가 조건 충족', required_equipment: '필요한 운반 장비 조건 충족' };
    const keys = Object.keys(parsed.answers).sort().join();
    const labels: Record<string, string> | null = keys === Object.keys(visit).sort().join() ? visit : keys === Object.keys(transport).sort().join() ? transport : null;
    if (!labels || Object.values(parsed.answers).some(v => typeof v !== 'boolean')) return null;
    return { title: labels === visit ? '현장 방문 및 확인서 제출' : '폐기물 직접 운반 예외 조건',
      text: Object.entries(labels).map(([key, label]) => `${label}: ${parsed.answers[key] ? '예' : '아니요'}`).join(' / ') };
  } catch { return null; }
}
