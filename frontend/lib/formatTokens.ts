export function formatCostCompact(costUsd: number | null | undefined): string {
  if (costUsd === null || costUsd === undefined) return "$0.00";
  if (costUsd === 0) return "$0.00";
  if (costUsd < 0.001) return "<$0.001";
  if (costUsd < 1) return `$${costUsd.toFixed(3)}`;
  return `$${costUsd.toFixed(2)}`;
}

export function formatTokenCount(n: number): string {
  if (n === 0) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export type TokenBreakdownRow = {
  label: string;
  tokens: number;
  rate: string;
  cost: string;
};

/** Accepts both RunRow field names (tokens_input) and LiveUsage field names (input_tokens). */
export function buildTokenBreakdown(run: {
  tokens_input?: number | null;
  tokens_output?: number | null;
  tokens_cache_read?: number | null;
  tokens_cache_creation?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read_tokens?: number | null;
  cache_creation_tokens?: number | null;
  cost_usd?: number | null;
}): TokenBreakdownRow[] | null {
  const inp = (run.tokens_input ?? run.input_tokens) ?? 0;
  const out = (run.tokens_output ?? run.output_tokens) ?? 0;
  const cr = (run.tokens_cache_read ?? run.cache_read_tokens) ?? 0;
  const cc = (run.tokens_cache_creation ?? run.cache_creation_tokens) ?? 0;
  if (!inp && !out && !cr && !cc) return null;
  const fmt = (n: number, rate: number) => `$${((n * rate) / 1e6).toFixed(4)}`;
  return [
    { label: "Input", tokens: inp, rate: "$3.00/MTok", cost: fmt(inp, 3.0) },
    { label: "Output", tokens: out, rate: "$15.00/MTok", cost: fmt(out, 15.0) },
    { label: "Cache read", tokens: cr, rate: "$0.30/MTok", cost: fmt(cr, 0.3) },
    { label: "Cache write", tokens: cc, rate: "$3.75/MTok", cost: fmt(cc, 3.75) },
  ].filter((r) => r.tokens > 0);
}
