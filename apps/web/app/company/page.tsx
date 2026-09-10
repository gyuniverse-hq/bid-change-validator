'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  BadgeCheck,
  Building2,
  CheckCircle2,
  FileBadge2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { COMPANY_SIZE_LABEL } from '@/lib/status-copy';
import {
  createCompany,
  listCompanies,
  searchIndustryCodes,
  type CompanyCreatePayload,
  type CompanyProfile,
  type CompanySize,
  type MasterCode,
} from '@/lib/qualification-api';

type Busy = 'load' | 'create' | null;

function companyRows(company: CompanyProfile) {
  const performanceTotal = company.performances.reduce((sum, item) => sum + item.amount, 0);
  return [
    {
      label: '업종 코드',
      value: company.industries.length
        ? company.industries.map((item) => `${item.code} · ${item.name}`).join(', ')
        : '비어 있음 · 판정하지 않습니다',
      source: company.industries.length ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'INDUSTRY',
    },
    {
      label: '소재지',
      value: company.region_name || company.region_code || '비어 있음 · 판정하지 않습니다',
      source: company.region_name || company.region_code ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'REGION',
    },
    {
      label: '기업 구분',
      value: COMPANY_SIZE_LABEL[company.company_size],
      source: '회사 입력',
      updated: company.updated_at,
      use: 'COMPANY_SIZE',
    },
    {
      label: '상시 근로자 수',
      value: company.staff ? `${company.staff.total_count.toLocaleString()}명` : '비어 있음 · 판정하지 않습니다',
      source: company.staff ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'STAFF',
    },
    {
      label: '최근 수행 실적 건수',
      value: `${company.performances.length}건`,
      source: company.performances.length ? '회사 입력' : '없음',
      updated: company.performances[0]?.updated_at ?? company.updated_at,
      use: 'PERFORMANCE_COUNT',
    },
    {
      label: '최근 수행 실적 금액',
      value: company.performances.length ? `합계 ${performanceTotal.toLocaleString()}원` : '비어 있음 · 판정하지 않습니다',
      source: company.performances.length ? '회사 입력' : '없음',
      updated: company.performances[0]?.updated_at ?? company.updated_at,
      use: 'PERFORMANCE_AMOUNT',
    },
    {
      label: '인증 · 등록',
      value: company.certifications.length
        ? company.certifications.map((item) => item.name).join(', ')
        : '비어 있음 · 판정하지 않습니다',
      source: company.certifications.length ? '회사 입력' : '없음',
      updated: company.certifications[0]?.updated_at ?? company.updated_at,
      use: 'REGISTRATION_CERTIFICATION',
    },
  ];
}

export default function CompanyPage() {
  const [companies, setCompanies] = useState<CompanyProfile[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [busy, setBusy] = useState<Busy>('load');
  const [error, setError] = useState('');
  const [industryQuery, setIndustryQuery] = useState('');
  const [industryOptions, setIndustryOptions] = useState<MasterCode[]>([]);
  const [selectedIndustry, setSelectedIndustry] = useState('');
  const [form, setForm] = useState({
    name: '',
    business_registration_number: '',
    region_code: '11',
    region_name: '서울특별시',
    company_size: 'SMALL' as CompanySize,
    staff_total: '8',
    developer_count: '5',
  });

  const company = useMemo(
    () => companies.find((item) => item.id === selectedId) ?? companies[0] ?? null,
    [companies, selectedId],
  );

  const rows = company ? companyRows(company) : [];
  const filledRows = rows.filter((row) => !row.value.startsWith('비어 있음')).length;
  const missingRows = rows.filter((row) => row.value.startsWith('비어 있음'));

  async function initialize() {
    setBusy('load');
    setError('');
    try {
      const [companyItems, industryResult] = await Promise.all([
        listCompanies(),
        searchIndustryCodes(),
      ]);
      setCompanies(companyItems);
      if (companyItems[0]) setSelectedId((value) => value || companyItems[0].id);
      setIndustryOptions(industryResult.items);
      setSelectedIndustry((value) => value || industryResult.items[0]?.code || '');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 프로필을 불러오지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function searchIndustries() {
    try {
      const result = await searchIndustryCodes(industryQuery);
      setIndustryOptions(result.items);
      if (result.items[0]) setSelectedIndustry(result.items[0].code);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '업종 검색에 실패했습니다.');
    }
  }

  async function submitCompany() {
    if (!selectedIndustry) {
      setError('업종 코드를 선택해주세요.');
      return;
    }
    setBusy('create');
    setError('');
    try {
      const payload: CompanyCreatePayload = {
        name: form.name,
        business_registration_number: form.business_registration_number || undefined,
        region_code: form.region_code,
        region_name: form.region_name || undefined,
        company_size: form.company_size,
        industry_codes: [selectedIndustry],
        staff: {
          total_count: Number(form.staff_total || 0),
          verified: false,
          roles: [
            {
              role_name: '개발자',
              headcount: Number(form.developer_count || 0),
              verified: false,
            },
          ],
        },
      };
      const created = await createCompany(payload);
      const refreshed = await listCompanies();
      setCompanies(refreshed);
      setSelectedId(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 프로필 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10 md:py-12">
        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!company ? (
          <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
            <div className="rounded-[24px] border border-[var(--product-line)] bg-white p-8 shadow-[0_12px_35px_rgba(35,50,90,0.06)]">
              <Badge className="bg-[#eef1ff] text-[var(--product-accent-deep)]">회사 프로필 생성</Badge>
              <h1 className="mt-4 text-[32px] font-extrabold tracking-[-0.04em] text-[var(--product-ink)]">판정을 시작하려면 회사 프로필이 필요합니다</h1>
              <p className="mt-3 max-w-3xl text-[14px] leading-7 text-[var(--product-muted)]">
                업종, 지역, 기업 규모, 인력 정보를 먼저 저장하면 공고 참가자격 판정에서 실제 비교값으로 사용합니다.
              </p>

              <div className="mt-8 grid gap-5 sm:grid-cols-2">
                <label className="text-sm font-medium">회사명<Input className="mt-2" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="예: 그린브릿지 글로벌 주식회사" /></label>
                <label className="text-sm font-medium">사업자등록번호<Input className="mt-2" value={form.business_registration_number} onChange={(event) => setForm({ ...form, business_registration_number: event.target.value })} placeholder="10자리 숫자" /></label>
                <label className="text-sm font-medium">지역 코드<Input className="mt-2" value={form.region_code} onChange={(event) => setForm({ ...form, region_code: event.target.value })} /></label>
                <label className="text-sm font-medium">소재지<Input className="mt-2" value={form.region_name} onChange={(event) => setForm({ ...form, region_name: event.target.value })} /></label>
                <label className="text-sm font-medium">전체 인원<Input className="mt-2" type="number" min="0" value={form.staff_total} onChange={(event) => setForm({ ...form, staff_total: event.target.value })} /></label>
                <label className="text-sm font-medium">개발자 인원<Input className="mt-2" type="number" min="0" value={form.developer_count} onChange={(event) => setForm({ ...form, developer_count: event.target.value })} /></label>
              </div>

              <div className="mt-6">
                <span className="text-sm font-medium">업종</span>
                <div className="mt-2 flex gap-2">
                  <Input value={industryQuery} onChange={(event) => setIndustryQuery(event.target.value)} placeholder="업종명 또는 코드 검색" />
                  <Button variant="outline" onClick={() => void searchIndustries()}><Search />검색</Button>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {industryOptions.slice(0, 6).map((item) => (
                    <button key={item.code} type="button" onClick={() => setSelectedIndustry(item.code)} className={`rounded-xl border px-4 py-3 text-left text-sm ${selectedIndustry === item.code ? 'border-[var(--product-accent)] bg-[#f3f5ff]' : 'border-[var(--product-line)]'}`}>
                      <strong>{item.code}</strong><span className="ml-2 text-[var(--product-muted)]">{item.name}</span>
                    </button>
                  ))}
                </div>
              </div>

              <Button className="mt-8 rounded-full px-6" onClick={() => void submitCompany()} disabled={!form.name.trim() || busy !== null}>
                {busy === 'create' ? <LoaderCircle className="animate-spin" /> : <Plus />}
                회사 프로필 만들기
              </Button>
            </div>

            <aside className="rounded-[24px] bg-[var(--product-accent-deep)] p-8 text-white">
              <Building2 className="size-9 text-white/80" />
              <h2 className="mt-6 text-[28px] font-extrabold">프로필 값이 판정 근거가 됩니다</h2>
              <div className="mt-7 space-y-4 text-sm text-white/78">
                <p>업종 → INDUSTRY</p>
                <p>지역 → REGION</p>
                <p>기업 규모 → COMPANY_SIZE</p>
                <p>인력 → STAFF</p>
                <p>수행 실적 → PERFORMANCE</p>
                <p>인증·등록 → REGISTRATION</p>
              </div>
            </aside>
          </section>
        ) : (
          <>
            <section className="rounded-[22px] border border-[var(--product-line)] bg-white p-6 shadow-[0_10px_28px_rgba(35,50,90,0.05)]">
              <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
                <div>
                  <h1 className="text-[28px] font-extrabold tracking-[-0.035em] text-[var(--product-ink)]">{rows.length}개 영역 중 {filledRows}개를 채웠습니다</h1>
                  <p className="mt-2 text-[14px] text-[var(--product-muted)]">비어 있는 값은 미달로 만들지 않고 확인 필요로 남깁니다.</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{company.name}</Badge>
                  <Button variant="outline" size="sm" onClick={() => void initialize()} disabled={busy !== null}><RefreshCw className={busy === 'load' ? 'animate-spin' : ''} />새로고침</Button>
                </div>
              </div>
            </section>

            {missingRows.length > 0 && (
              <section className="mt-5 rounded-[22px] border border-[#e2d9a9] bg-[#fffaf0] p-6">
                <div className="flex items-center gap-2"><FileBadge2 className="size-5 text-amber-700" /><h2 className="text-[20px] font-bold">비어 있는 항목 {missingRows.length}건</h2></div>
                <div className="mt-4 divide-y divide-[#eee3bd]">
                  {missingRows.map((row) => <div key={row.label} className="flex items-center justify-between gap-4 py-4"><div><strong>{row.label}</strong><p className="mt-1 text-sm text-[var(--product-muted)]">이 값을 요구하는 공고는 확인 필요로 남습니다.</p></div><Badge className="bg-amber-100 text-amber-800">확인 필요</Badge></div>)}
                </div>
              </section>
            )}

            <section className="mt-7">
              <div className="flex items-center gap-3"><h2 className="text-[27px] font-extrabold tracking-[-0.035em]">프로필 항목</h2><span className="text-[14px] text-[var(--product-muted)]">값마다 어디서 왔는지 표시합니다</span></div>
              <div className="mt-4 overflow-hidden rounded-[20px] border border-[var(--product-line)] bg-white">
                <div className="grid grid-cols-[1.2fr_1.8fr_0.9fr_0.9fr_1.1fr] bg-[var(--product-tint)] px-4 py-3 text-[12px] font-bold text-[var(--product-muted)]"><span>항목</span><span>값</span><span>출처</span><span>갱신일</span><span>이 값을 쓰는 곳</span></div>
                {rows.map((row) => (
                  <div key={row.label} className="grid grid-cols-1 gap-2 border-t border-[var(--product-line-2)] px-4 py-4 text-sm md:grid-cols-[1.2fr_1.8fr_0.9fr_0.9fr_1.1fr] md:items-center">
                    <strong>{row.label}</strong>
                    <span className={row.value.startsWith('비어 있음') ? 'text-amber-700' : ''}>{row.value}</span>
                    <span><Badge variant="outline">{row.source}</Badge></span>
                    <span>{new Date(row.updated).toLocaleDateString('ko-KR')}</span>
                    <span className="text-[12px] font-semibold text-[var(--product-accent-deep)]">{row.use}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="mt-7 grid gap-5 md:grid-cols-3">
              <div className="rounded-[20px] border border-[var(--product-line)] p-6"><Users className="size-6 text-[var(--product-accent)]" /><h3 className="mt-3 font-bold">인력</h3><p className="mt-2 text-sm text-[var(--product-muted)]">총 {company.staff?.total_count ?? 0}명 · {company.staff?.roles.map((role) => `${role.role_name} ${role.headcount}명`).join(', ') || '역할 정보 없음'}</p></div>
              <div className="rounded-[20px] border border-[var(--product-line)] p-6"><CheckCircle2 className="size-6 text-[var(--product-accent)]" /><h3 className="mt-3 font-bold">수행 실적</h3><p className="mt-2 text-sm text-[var(--product-muted)]">{company.performances.length}건 저장됨</p></div>
              <div className="rounded-[20px] border border-[var(--product-line)] p-6"><BadgeCheck className="size-6 text-[var(--product-accent)]" /><h3 className="mt-3 font-bold">인증 · 등록</h3><p className="mt-2 text-sm text-[var(--product-muted)]">{company.certifications.length}건 저장됨</p></div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}
