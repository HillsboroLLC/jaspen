// Formatting helpers for the Cost of Turnover utility. Kept separate so the
// engine stays presentation-free.

export function formatCurrency(value, { round = true } = {}) {
  const n = Number(value) || 0;
  const rounded = round ? Math.round(n) : n;
  return rounded.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  });
}

// Compact currency for big hero numbers, e.g. $86,694 -> "$86.7K", $1,240,000 -> "$1.24M".
export function formatCurrencyCompact(value) {
  const n = Math.round(Number(value) || 0);
  if (Math.abs(n) >= 1_000_000) {
    return `$${(n / 1_000_000).toLocaleString('en-US', { maximumFractionDigits: 2 })}M`;
  }
  if (Math.abs(n) >= 10_000) {
    return `$${(n / 1_000).toLocaleString('en-US', { maximumFractionDigits: 0 })}K`;
  }
  return formatCurrency(n);
}

export function formatPercent(value, digits = 0) {
  const n = Number(value) || 0;
  return `${n.toFixed(digits)}%`;
}

export function formatRange(low, high) {
  return `${formatCurrency(low)} – ${formatCurrency(high)}`;
}
