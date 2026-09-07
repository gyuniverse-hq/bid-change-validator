type EvidenceQuoteProps = {
  label: string;
  quote: string;
  note?: string;
};

export function EvidenceQuote({ label, quote, note }: EvidenceQuoteProps) {
  return (
    <div className="rounded-[14px] border border-[var(--product-line)] bg-[#f8f9fc] px-4 py-3">
      <p className="text-[12px] font-semibold text-[var(--product-accent-deep)]">{label}</p>
      <p className="mt-1.5 text-[14px] leading-6 text-[var(--product-body)]">“{quote}”</p>
      {note && <p className="mt-1 text-[12px] leading-5 text-[var(--product-muted)]">{note}</p>}
    </div>
  );
}
