import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowUpRightFromSquare,
  faCloudArrowUp,
  faLock,
  faSpinner,
  faTimes,
  faWandMagicSparkles,
} from '@fortawesome/free-solid-svg-icons';

import { Jaspen } from '../JaspenClient';
import './BatchIdeaManager.css';

const LAST_BATCH_KEY = 'jaspen:lastBatchIdeasId';
const BATCH_UPLOAD_ACCEPTED_EXTENSIONS = ['.csv', '.xlsx', '.xls', '.doc', '.docx'];

function storeLastBatchId(batchId) {
  try {
    if (!batchId) {
      localStorage.removeItem(LAST_BATCH_KEY);
      return;
    }
    localStorage.setItem(LAST_BATCH_KEY, String(batchId));
  } catch {}
}

function getLastBatchId() {
  try {
    return localStorage.getItem(LAST_BATCH_KEY) || '';
  } catch {
    return '';
  }
}

function normalizeIdeas(batch) {
  const ideas = Array.isArray(batch?.ideas)
    ? batch.ideas
    : Array.isArray(batch?.ranking_result?.ranked_ideas)
      ? batch.ranking_result.ranked_ideas
      : [];
  return ideas;
}

function isAcceptedBatchFile(file) {
  const name = String(file?.name || '').toLowerCase();
  return BATCH_UPLOAD_ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

export default function BatchIdeaManager({
  open,
  onClose,
  onOpenBilling,
  onOpenThread,
  onRefreshSessions,
  canUseBatchIdeas,
  isLocked,
  canPromoteBatchIdeas,
  lockReason,
  showToast,
  onBatchActivity,
}) {
  const [uploading, setUploading] = useState(false);
  const [ranking, setRanking] = useState(false);
  const [promotingAll, setPromotingAll] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(false);
  const [batch, setBatch] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [clarifyDrafts, setClarifyDrafts] = useState({});
  const [busyIdeaId, setBusyIdeaId] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const dragDepthRef = useRef(0);

  const ideas = useMemo(() => normalizeIdeas(batch), [batch]);
  const readyIdeas = useMemo(
    () => ideas.filter((idea) => idea?.scoreable && !idea?.thread_id),
    [ideas]
  );

  useEffect(() => {
    if (!open || !canUseBatchIdeas) return;
    const lastBatchId = getLastBatchId();
    if (!lastBatchId || batch?.batch_id === lastBatchId) return;
    let cancelled = false;
    setLoadingExisting(true);
    Jaspen.getBatchIdeas(lastBatchId)
      .then((payload) => {
        if (!cancelled) setBatch(payload);
      })
      .catch(() => {
        if (!cancelled) storeLastBatchId('');
      })
      .finally(() => {
        if (!cancelled) setLoadingExisting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, canUseBatchIdeas, batch?.batch_id]);

  useEffect(() => {
    if (batch?.batch_id) storeLastBatchId(batch.batch_id);
  }, [batch?.batch_id]);

  if (!open) return null;

  const onFileChange = (event) => {
    const next = event.target.files?.[0] || null;
    if (next && !isAcceptedBatchFile(next)) {
      showToast?.('Unsupported file type. Use CSV, Excel, or Word.', 'error');
      return;
    }
    setSelectedFile(next);
  };

  const onDragEnter = (event) => {
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current += 1;
    setDragActive(true);
  };

  const onDragOver = (event) => {
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'copy';
  };

  const onDragLeave = (event) => {
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragActive(false);
  };

  const onDrop = (event) => {
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = 0;
    setDragActive(false);
    const dropped = event.dataTransfer?.files?.[0] || null;
    if (!dropped) return;
    if (!isAcceptedBatchFile(dropped)) {
      showToast?.('Unsupported file type. Use CSV, Excel, or Word.', 'error');
      return;
    }
    setSelectedFile(dropped);
    showToast?.(`Selected ${dropped.name}`, 'success');
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      showToast?.('Choose a CSV, Excel, or Word document.', 'info');
      return;
    }
    setUploading(true);
    try {
      const payload = await Jaspen.uploadBatchIdeas(selectedFile);
      setBatch(payload);
      showToast?.(`Uploaded ${payload.total_count || 0} ideas`, 'success');
      onBatchActivity?.({
        type: 'batch_upload_complete',
        batchId: payload?.batch_id || '',
        filename: selectedFile?.name || payload?.filename || '',
        totalCount: Number(payload?.total_count || 0),
      });
    } catch (error) {
      showToast?.(error?.message || 'Failed to upload batch ideas.', 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleRank = async () => {
    if (!batch?.batch_id) return;
    setRanking(true);
    try {
      const payload = await Jaspen.rankBatchIdeas(batch.batch_id);
      setBatch((prev) => ({
        ...(prev || {}),
        ...payload,
        ideas: payload.ranked_ideas || prev?.ideas || [],
      }));
      showToast?.('Ideas ranked and saved.', 'success');
      onBatchActivity?.({
        type: 'batch_rank_complete',
        batchId: batch?.batch_id || '',
        rankedCount: Array.isArray(payload?.ranked_ideas) ? payload.ranked_ideas.length : ideas.length,
      });
    } catch (error) {
      showToast?.(error?.message || 'Failed to rank ideas.', 'error');
    } finally {
      setRanking(false);
    }
  };

  const handleClarify = async (idea) => {
    const questionMap = clarifyDrafts[idea.idea_id] || {};
    const answers = Object.fromEntries(
      Object.entries(questionMap).filter(([, value]) => String(value || '').trim())
    );
    if (Object.keys(answers).length === 0) {
      showToast?.('Answer at least one clarifying question first.', 'info');
      return;
    }
    setBusyIdeaId(idea.idea_id);
    try {
      const payload = await Jaspen.clarifyIdea(batch.batch_id, idea.idea_id, answers);
      setBatch((prev) => ({
        ...(prev || {}),
        status: payload.status || prev?.status,
        ideas: normalizeIdeas({
          ideas: (prev?.ideas || []).map((item) => (
            item.idea_id === payload.idea.idea_id ? payload.idea : item
          )),
        }),
      }));
      setClarifyDrafts((prev) => {
        const next = { ...(prev || {}) };
        delete next[idea.idea_id];
        return next;
      });
      showToast?.('Clarification saved.', 'success');
    } catch (error) {
      showToast?.(error?.message || 'Failed to clarify idea.', 'error');
    } finally {
      setBusyIdeaId('');
    }
  };

  const handlePromoteIdea = async (idea) => {
    setBusyIdeaId(idea.idea_id);
    try {
      const payload = await Jaspen.promoteIdea(batch.batch_id, idea.idea_id);
      const promotedThreadId = payload.thread_id;
      setBatch((prev) => ({
        ...(prev || {}),
        status: payload.status || prev?.status,
        ideas: (prev?.ideas || []).map((item) => (
          item.idea_id === idea.idea_id
            ? { ...item, thread_id: promotedThreadId, promoted_at: new Date().toISOString() }
            : item
        )),
      }));
      await onRefreshSessions?.();
      showToast?.('Idea promoted into a project thread.', 'success');
    } catch (error) {
      showToast?.(error?.message || 'Failed to promote idea.', 'error');
    } finally {
      setBusyIdeaId('');
    }
  };

  const handlePromoteAll = async () => {
    if (!batch?.batch_id || readyIdeas.length === 0) return;
    setPromotingAll(true);
    try {
      const payload = await Jaspen.promoteAllIdeas(batch.batch_id);
      const byIdeaId = new Map((payload.promoted || []).map((item) => [item.idea_id, item.thread_id]));
      setBatch((prev) => ({
        ...(prev || {}),
        status: payload.status || prev?.status,
        ideas: (prev?.ideas || []).map((item) => (
          byIdeaId.has(item.idea_id)
            ? { ...item, thread_id: byIdeaId.get(item.idea_id), promoted_at: new Date().toISOString() }
            : item
        )),
      }));
      await onRefreshSessions?.();
      showToast?.(
        payload.has_more
          ? 'Promoted the next 10 ready ideas. Run again to continue.'
          : 'Promoted all ready ideas.',
        'success'
      );
      onBatchActivity?.({
        type: 'batch_promote_complete',
        batchId: batch?.batch_id || '',
        promotedCount: Array.isArray(payload?.promoted) ? payload.promoted.length : 0,
        hasMore: Boolean(payload?.has_more),
      });
    } catch (error) {
      showToast?.(error?.message || 'Failed to promote ready ideas.', 'error');
    } finally {
      setPromotingAll(false);
    }
  };

  const setDraftAnswer = (ideaId, question, value) => {
    setClarifyDrafts((prev) => ({
      ...(prev || {}),
      [ideaId]: {
        ...(prev?.[ideaId] || {}),
        [question]: value,
      },
    }));
  };

  return (
    <div className="jas-modal-overlay" role="dialog" aria-modal="true" aria-label="Batch ideas manager">
      <div className="jas-modal-card jas-batch-ideas-modal">
        <div className="jas-modal-head">
          <div>
            <h3>Batch Ideas</h3>
            <p>Upload a CSV, Excel, or Word document, rank ideas, answer clarifications, and promote ready ideas into project threads.</p>
          </div>
          <button type="button" className="jas-ai-mini-btn" onClick={onClose}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {isLocked && (
          <div className="jas-batch-locked">
            <div className="jas-batch-locked-icon">
              <FontAwesomeIcon icon={faLock} />
            </div>
            <div>
              <strong>
                {lockReason === 'role'
                  ? 'Only creators and admins can use Batch Ideas.'
                  : 'Batch Ideas is available on Team and Enterprise.'}
              </strong>
              <p>
                {lockReason === 'role'
                  ? 'Ask a team admin to change your role if you need to upload and promote ideas into projects.'
                  : 'Upgrade to batch-upload and triage portfolios of ideas with AI ranking and one-click project promotion.'}
              </p>
            </div>
            {lockReason === 'plan' && (
              <button type="button" className="jas-ai-mini-btn primary" onClick={onOpenBilling}>
                Upgrade
              </button>
            )}
          </div>
        )}

        {!isLocked && (
          <div className="jas-batch-body">
            <div
              className={`jas-batch-upload ${dragActive ? 'is-dragging' : ''}`}
              onDragEnter={onDragEnter}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
            >
              <label className="jas-batch-file-picker">
                <input type="file" accept=".csv,.xlsx,.xls,.doc,.docx" onChange={onFileChange} />
                <span><FontAwesomeIcon icon={faCloudArrowUp} /> Choose CSV, Excel, or Word</span>
              </label>
              <span className="jas-batch-file-name">{selectedFile?.name || batch?.filename || 'No file selected'}</span>
              <button type="button" className="jas-ai-mini-btn primary" onClick={handleUpload} disabled={uploading || !selectedFile} aria-disabled={uploading || !selectedFile}>
                <FontAwesomeIcon icon={uploading ? faSpinner : faCloudArrowUp} spin={uploading} />
                <span>{uploading ? 'Uploading…' : 'Upload Ideas'}</span>
              </button>
              {batch?.batch_id && (
                <button type="button" className="jas-ai-mini-btn secondary" onClick={handleRank} disabled={ranking} aria-disabled={ranking}>
                  <FontAwesomeIcon icon={ranking ? faSpinner : faWandMagicSparkles} spin={ranking} />
                  <span>{ranking ? 'Ranking…' : 'Rank Ideas'}</span>
                </button>
              )}
              {readyIdeas.length > 0 && (
                <button
                  type="button"
                  className="jas-ai-mini-btn secondary"
                  onClick={handlePromoteAll}
                  disabled={promotingAll || !canPromoteBatchIdeas} aria-disabled={promotingAll || !canPromoteBatchIdeas}
                  title={canPromoteBatchIdeas ? 'Promote the next 10 ready ideas' : 'Only creators and admins can promote ideas into projects'}
                >
                  <FontAwesomeIcon icon={promotingAll ? faSpinner : faArrowUpRightFromSquare} spin={promotingAll} />
                  <span>{promotingAll ? 'Promoting…' : `Score All Ready (${readyIdeas.length})`}</span>
                </button>
              )}
            </div>

            {loadingExisting && !batch && (
              <div className="jas-batch-empty">Loading your last saved batch…</div>
            )}

            {!loadingExisting && !batch && (
              <div className="jas-batch-empty">
                <strong>No batch uploaded yet.</strong>
                <p>Upload a list of ideas to rank them, ask clarifying questions, and turn ready ideas into projects.</p>
              </div>
            )}

            {batch && (
              <>
                <div className="jas-batch-summary">
                  <div><strong>{batch.total_count || ideas.length}</strong><span>Ideas</span></div>
                  <div><strong>{batch.status || 'uploaded'}</strong><span>Status</span></div>
                  <div><strong>{readyIdeas.length}</strong><span>Ready now</span></div>
                </div>

                <div className="jas-batch-table">
                  {ideas.map((idea) => {
                    const questions = Array.isArray(idea?.clarifying_questions) ? idea.clarifying_questions : [];
                    const clarificationDraft = clarifyDrafts[idea.idea_id] || {};
                    const isBusy = busyIdeaId === idea.idea_id;
                    return (
                      <div key={idea.idea_id} className="jas-batch-row">
                        <div className="jas-batch-row-head">
                          <div>
                            <h4>{idea.title || 'Untitled idea'}</h4>
                            <div className="jas-batch-row-meta">
                              <span>Rank: {idea.rank || '—'}</span>
                              <span>Score: {idea.preliminary_score ?? '—'}</span>
                              <span>{idea.scoreable ? 'Ready to score' : 'Needs clarification'}</span>
                            </div>
                          </div>
                          <div className="jas-batch-row-actions">
                            {idea.thread_id ? (
                              <button type="button" className="jas-ai-mini-btn secondary" onClick={() => onOpenThread?.(idea.thread_id)}>
                                Open Project
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="jas-ai-mini-btn primary"
                                onClick={() => handlePromoteIdea(idea)}
                                disabled={!idea.scoreable || isBusy || !canPromoteBatchIdeas} aria-disabled={!idea.scoreable || isBusy || !canPromoteBatchIdeas}
                                title={canPromoteBatchIdeas ? 'Promote this idea into its own project thread' : 'Only creators and admins can promote ideas into projects'}
                              >
                                <FontAwesomeIcon icon={isBusy ? faSpinner : faArrowUpRightFromSquare} spin={isBusy} />
                                <span>Score This Idea</span>
                              </button>
                            )}
                          </div>
                        </div>

                        {idea.rationale && (
                          <p className="jas-batch-rationale">{idea.rationale}</p>
                        )}

                        <div className="jas-batch-metadata">
                          {Object.entries(idea.metadata || {}).slice(0, 8).map(([key, value]) => (
                            <span key={`${idea.idea_id}-${key}`} className="jas-batch-chip">{key}: {String(value)}</span>
                          ))}
                        </div>

                        {questions.length > 0 && !idea.thread_id && (
                          <div className="jas-batch-clarifications">
                            <h5>Clarifying questions</h5>
                            {questions.map((question) => (
                              <label key={`${idea.idea_id}-${question}`} className="jas-batch-question">
                                <span>{question}</span>
                                <input
                                  type="text"
                                  value={clarificationDraft[question] || ''}
                                  onChange={(event) => setDraftAnswer(idea.idea_id, question, event.target.value)}
                                  placeholder="Type your answer"
                                />
                              </label>
                            ))}
                            <button type="button" className="jas-ai-mini-btn secondary" onClick={() => handleClarify(idea)} disabled={isBusy} aria-disabled={isBusy}>
                              <FontAwesomeIcon icon={isBusy ? faSpinner : faWandMagicSparkles} spin={isBusy} />
                              <span>Save Clarifications</span>
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
