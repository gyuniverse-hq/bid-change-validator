'use client';

import { useEffect, useState, type ReactNode } from 'react';

import { ProfileRecordsManager } from '@/components/product/profile-records-manager';
import { listCompanies, type CompanyProfile } from '@/lib/qualification-api';

export default function CompanyLayout({ children }: { children: ReactNode }) {
  const [company, setCompany] = useState<CompanyProfile | null>(null);

  async function reload() {
    try {
      const companies = await listCompanies();
      setCompany(companies[0] ?? null);
    } catch {
      setCompany(null);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  return (
    <>
      {children}
      {company && (
        <div className="app-shell-container pb-12">
          <ProfileRecordsManager company={company} onChanged={reload} />
        </div>
      )}
    </>
  );
}
