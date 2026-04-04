export function ScoreGauge({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));
  return (
    <div className="space-y-1">
      <div
        className="h-2 w-full overflow-hidden rounded bg-[var(--primary-100)]"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`QA score ${pct} percent`}
      >
        <div className="h-full bg-[var(--accent-blue)]" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-[var(--text-muted)]">QA score: {pct}%</p>
    </div>
  );
}
