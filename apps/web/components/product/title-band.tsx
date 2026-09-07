import { PageContainer } from '@/components/product/page-container';

export type TitleBandProps = {
  title: string;
  description: string;
  breadcrumb: string;
};

export function TitleBand({ title, description, breadcrumb }: TitleBandProps) {
  return (
    <section className="app-title-band">
      <PageContainer className="relative flex h-full items-center">
        <div className="min-w-0 pb-1">
          <h1 className="text-[32px] font-semibold leading-[44px] tracking-[-0.035em] text-[var(--product-ink)]">
            {title}
          </h1>
          <p className="mt-1 text-[14px] leading-[21px] text-[var(--product-muted)]">{description}</p>
        </div>
        <p className="absolute right-[var(--product-shell-gutter)] bottom-7 hidden text-[12px] text-[var(--product-faint)] md:block">
          {breadcrumb}
        </p>
      </PageContainer>
    </section>
  );
}
