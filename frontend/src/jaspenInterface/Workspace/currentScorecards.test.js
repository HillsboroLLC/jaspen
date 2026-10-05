import { refreshScorecardMessages, selectCurrentScorecard } from './currentScorecards';

test('re-score updates existing inline artifact by stable ID without mutating history', () => {
  const old = { id: 'city', jaspen_score: 59, top_risks: ['old'] };
  const current = { id: 'city', jaspen_score: 61, top_risks: ['current'] };
  const history = [{ artifact: { type: 'scorecard', data: old } }, { text: 'This scores 72', _isProactiveHint: true }];
  const visible = refreshScorecardMessages(history, [current]);
  expect(visible).toHaveLength(1);
  expect(visible[0].artifact.data).toBe(current);
  expect(history[0].artifact.data.jaspen_score).toBe(59);
});

test('leader uses current scores while explicit selection retains its own details', () => {
  const aurora = { id: 'aurora', jaspen_score: 30, top_risks: ['Aurora risk'] };
  const city = { id: 'city', jaspen_score: 72, top_risks: ['City risk'] };
  const cards = [aurora, city, { id: 'last', jaspen_score: 40 }];
  expect(selectCurrentScorecard(cards)).toBe(city);
  expect(selectCurrentScorecard(cards, 'aurora').top_risks).toEqual(['Aurora risk']);
  expect(selectCurrentScorecard(cards, 'missing')).toBeNull();
  expect(selectCurrentScorecard([aurora, { ...city, jaspen_score: 20 }])).toBe(aurora);
});
