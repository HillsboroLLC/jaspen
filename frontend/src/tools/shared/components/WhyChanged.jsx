import React, { useEffect } from 'react';
import { formatCurrency } from '../formatting';

// "Why your estimate changed" — appears once the user overrides a benchmark.
// Explains, per change, what moved and its dollar impact vs. the recommended
// default. `items` is [{ key, label, fromText, toText, delta }] where delta is
// the signed dollar change to the headline monthly (or total) figure.
export default function WhyChanged({ items, unitLabel = 'monthly cost', onView }) {
  useEffect(() => {
    if (items.length > 0 && onView) onView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length]);

  if (!items.length) return null;

  return (
    <section className="tool-why" aria-labelledby="tool-why-title">
      <h3 id="tool-why-title">Why your estimate changed</h3>
      <p className="tool-help" style={{ margin: '0 0 8px' }}>
        You adjusted {items.length} assumption{items.length === 1 ? '' : 's'} from the recommended
        defaults. Here is what each change did to your {unitLabel}.
      </p>
      {items.map((it) => {
        const up = it.delta > 0;
        const negligible = Math.abs(it.delta) < 0.5;
        return (
          <div className="tool-why-item" key={it.key}>
            <span>
              <strong>{it.label}</strong>: {it.fromText} → {it.toText}
            </span>
            <span className={up ? 'tool-why-delta-up' : 'tool-why-delta-down'}>
              {negligible ? 'no change' : `${up ? '+' : '−'}${formatCurrency(Math.abs(it.delta))}`}
            </span>
          </div>
        );
      })}
    </section>
  );
}
