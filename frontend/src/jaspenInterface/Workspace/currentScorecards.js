// Resolve all scorecard displays against current persisted snapshots by stable ID.
export const scorecardId = (card) => String(card?.id || card?.analysis_id || card?.analysisId || '').trim();

export function refreshScorecardMessages(messages, cards) {
  const current = new Map((cards || []).map(card => [scorecardId(card), card]));
  return (messages || []).filter(message => !message?._isProactiveHint).map(message => {
    if (message?.artifact?.type !== 'scorecard') return message;
    const card = current.get(scorecardId(message.artifact.data));
    return card ? { ...message, artifact: { ...message.artifact, data: card } } : message;
  });
}

export function selectCurrentScorecard(cards, explicitlySelectedId = '') {
  const candidates = (cards || []).filter(card => card && Number.isFinite(Number(card.jaspen_score ?? card.score)));
  if (explicitlySelectedId) return candidates.find(card => scorecardId(card) === explicitlySelectedId) || null;
  return candidates.reduce((leader, card) => !leader || Number(card.jaspen_score ?? card.score) > Number(leader.jaspen_score ?? leader.score) ? card : leader, null);
}
