// Shared formatting helpers for Jaspen utilities. Presentation-only.

export function formatCurrency(value, { round = true } = {}) {
  const n = Number(value) || 0;
  const rounded = round ? Math.round(n) : n;
  return rounded.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: round ? 0 : 2,
  });
}

// Compact currency for hero figures, e.g. $3,189 -> "$3.2K", $474,714 -> "$475K".
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

// Fraction (0.011) -> "1.10%"
export function formatRate(fraction, digits = 2) {
  return `${((Number(fraction) || 0) * 100).toFixed(digits)}%`;
}

export function formatRange(low, high) {
  return `${formatCurrency(low)} – ${formatCurrency(high)}`;
}
