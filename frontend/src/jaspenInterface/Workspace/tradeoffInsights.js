// Shared trade-off insight computation — single source of truth so the inline
// chat card, the right-side insights panel, and the Workspace TradeoffView all
// show the SAME "what separates them" content (card ↔ workspace parity).
//
// Input: an array of { name, dimensions } where dimensions is a map of
//   { key: { label, score, is_risk } } (0–100 scores).
// Output: { keyDifferentiator: { label, spread } | null, perOption: [{ name, bestLabel, worstLabel }] }

export function computeTradeoffInsights(items) {
  const rows = (Array.isArray(items) ? items : [])
    .map((it) => ({
      name: String(it?.name || '').trim(),
      dims: (it?.dimensions && typeof it.dimensions === 'object') ? it.dimensions : null,
    }))
    .filter((r) => r.dims && Object.keys(r.dims).length > 0);

  if (rows.length < 2) return { keyDifferentiator: null, perOption: [], criteriaComparable: false };

  const dimKeys = [...new Set(rows.flatMap((r) => Object.keys(r.dims)))];
  const labelOf = (k) => rows.find((r) => r.dims[k])?.dims[k]?.label || k;

  // Key differentiator = the criterion with the widest spread across options.
  let keyDifferentiator = null;
  let bestSpread = -1;
  dimKeys.forEach((k) => {
    // A missing criterion is not a zero. Only compare a criterion when every
    // displayed project was actually scored on it.
    const vals = rows
      .map((r) => r.dims[k]?.score)
      .filter((value) => value !== undefined && value !== null)
      .map(Number)
      .filter(Number.isFinite);
    if (vals.length !== rows.length) return;
    const spread = Math.max(...vals) - Math.min(...vals);
    if (spread > bestSpread) {
      bestSpread = spread;
      keyDifferentiator = { label: labelOf(k), spread: Math.round(spread) };
    }
  });

  // Per option: strongest and weakest criterion.
  const perOption = rows.map((r) => {
    const entries = Object.values(r.dims)
      .map((v) => ({ label: v?.label || '', score: Number(v?.score) }))
      .filter((e) => e.label && Number.isFinite(e.score));
    if (entries.length < 2) return { name: r.name, bestLabel: null, worstLabel: null };
    const best = entries.reduce((a, b) => (b.score > a.score ? b : a));
    const worst = entries.reduce((a, b) => (b.score < a.score ? b : a));
    const same = best.label === worst.label;
    return { name: r.name, bestLabel: same ? null : best.label, worstLabel: same ? null : worst.label };
  });

  return { keyDifferentiator, perOption, criteriaComparable: Boolean(keyDifferentiator) };
}
