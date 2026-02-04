import fs from 'fs';
import postcss from 'postcss';

const INPUT = 'src/Market/styles/MarketIQ.css';
const OUTPUT = 'src/Market/styles/MarketIQ.cleaned.css';

const css = fs.readFileSync(INPUT, 'utf8');
const root = postcss.parse(css, { from: INPUT });

/**
 * We keep a map keyed by:
 *   `${context}::${selector}`
 * where `context` is the chain of @rules (e.g. "@media screen and (max-width: 768px)")
 * This way we never merge rules across different media/containers.
 */
const keyOf = (rule) => {
  // Build context string up the at-rule chain
  let ctx = [];
  let node = rule.parent;
  while (node && node.type !== 'root') {
    if (node.type === 'atrule') {
      ctx.unshift(`@${node.name} ${node.params}`);
    }
    node = node.parent;
  }
  return `${ctx.join(' -> ')}::${rule.selector}`;
};

// For each unique (context, selector) we keep:
// - lastRule: the last occurrence in the file
// - decls: final property->value (last one wins)
// - order: preserve property order of last occurrences (nice to keep readable)
const groups = new Map();

// First pass: collect all declarations while tracking which rule is last
root.walkRules(rule => {
  if (!rule.selector) return;

  const key = keyOf(rule);
  let g = groups.get(key);
  if (!g) g = { lastRule: rule, order: [], decls: new Map() };

  // Inside a single rule block: dedupe properties, keep last occurrence
  const seenInThisRule = new Set();
  rule.walkDecls(decl => {
    // remove earlier same-prop in this rule (we’ll rebuild)
    if (seenInThisRule.has(decl.prop)) return;
    seenInThisRule.add(decl.prop);
  });

  // Walk from top to bottom, but we record values (last wins across rules)
  rule.walkDecls(decl => {
    // overwrite previous value
    g.decls.set(decl.prop, decl.value);
    // track order for pretty output (push if new, move to end if already tracked)
    const idx = g.order.indexOf(decl.prop);
    if (idx >= 0) g.order.splice(idx, 1);
    g.order.push(decl.prop);
  });

  // update last rule reference (so we insert the merged rule here)
  g.lastRule = rule;
  groups.set(key, g);
});

// Second pass: remove all duplicate selector rules;
// we will rebuild only the final one with merged declarations.
root.walkRules(rule => {
  const key = keyOf(rule);
  const g = groups.get(key);
  if (!g) return;
  if (rule !== g.lastRule) {
    rule.remove(); // drop earlier duplicates
  }
});

// Third pass: rebuild the kept rules with merged declarations (deduped props)
for (const [, g] of groups) {
  const { lastRule, order, decls } = g;
  // clear declarations in the kept rule
  lastRule.removeAll();
  // re-add in stable order
  for (const prop of order) {
    lastRule.append({ prop, value: decls.get(prop) });
  }
}

fs.writeFileSync(OUTPUT, root.toString());
console.log(`✔ Deduped CSS written to ${OUTPUT}`);
