/** Restore a scorecard layout without rewriting the coordinates the user saved. */
export function mergePersistedSectionLayout(saved, defaults, generatedPrefix = 'criterion:') {
  const rows = Array.isArray(saved) ? saved : [];
  const base = Array.isArray(defaults) ? defaults : [];
  if (rows.length === 0) {
    return base.map((section) => ({ ...section, collapsed: false }));
  }

  // The grid already resolved collisions when the user dropped a card. Moving
  // only full-width rows during hydration creates new collisions and lets the
  // grid produce a different arrangement after refresh. Persisted x/y/w/h are
  // therefore authoritative.
  let cursor = rows.reduce((bottom, row) => {
    const y = Number.isFinite(row?.y) ? row.y : 0;
    const h = Number.isFinite(row?.h) ? row.h : 5;
    return Math.max(bottom, y + h);
  }, 0);

  const merged = base.map((section) => {
    const found = rows.find((row) => row && row.key === section.key);
    if (found) return { ...section, ...found };

    // A section introduced after an older layout was saved is appended below
    // it. Migration may add a card, but it must never reposition saved cards.
    const added = { ...section, x: 0, y: cursor, collapsed: false };
    cursor += Number.isFinite(added.h) ? added.h : 5;
    return added;
  });

  // Generated criterion cards are not in the static defaults.
  rows.forEach((row) => {
    if (row && typeof row.key === 'string' && row.key.startsWith(generatedPrefix)) {
      if (!merged.some((section) => section.key === row.key)) merged.push({ ...row });
    }
  });
  return merged;
}
