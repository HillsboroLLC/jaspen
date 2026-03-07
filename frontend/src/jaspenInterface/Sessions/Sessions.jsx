// src/pages/Sessions/Sessions.jsx
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './Sessions.css';

const parseDateValue = (value) => {
  const ts = new Date(value || 0).getTime();
  return Number.isFinite(ts) ? ts : 0;
};

const extractSessionScore = (session) => {
  const candidates = [
    session?.score,
    session?.market_iq_score,
    session?.result?.market_iq_score,
    session?.result?.score,
    session?.result?.compat?.score,
    session?.result?.metrics?.overall_score
  ];
  for (const value of candidates) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.round(parsed);
  }
  return null;
};

const normalizeSession = (session) => ({
  ...session,
  _score: extractSessionScore(session),
  _updatedAt: parseDateValue(session?.timestamp || session?.updated_at || session?.created),
  _createdAt: parseDateValue(session?.created || session?.timestamp),
});

const Sessions = () => {
  const navigate = useNavigate();
  const location = useLocation();
  
  // State management
  const [sessions, setSessions] = useState([]);
  const [filteredSessions, setFilteredSessions] = useState([]);
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortBy, setSortBy] = useState('updated_desc');
  const [view, setView] = useState('list');
  const [currentSession, setCurrentSession] = useState(null);
  const [activeTab, setActiveTab] = useState('summary');
  const [loading, setLoading] = useState(true);

  // Get URL parameters
  const urlParams = new URLSearchParams(location.search);
  const viewParam = urlParams.get('view');
  const sessionIdParam = urlParams.get('session_id');
  const fromParam = urlParams.get('from');
  const isQueueView = viewParam === 'queue';

  // Handle URL parameters
  useEffect(() => {
    if (viewParam === 'review' && sessionIdParam) {
      const session = sessions.find(s => s.session_id === sessionIdParam);
      if (session) {
        setView('review');
        setCurrentSession(session);
      }
      return;
    }
    if (viewParam === 'queue') {
      setView('list');
      setCurrentSession(null);
      setSortBy('score_desc');
    }
  }, [viewParam, sessionIdParam, sessions]);

  // Load sessions from localStorage and API
  const loadSessions = useCallback(async () => {
    try {
      setLoading(true);
      
      // Try to load from API first
      const response = await fetch(`${API_BASE}/api/ai-agent/threads`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          const normalized = (data.sessions || []).map(normalizeSession);
          setSessions(normalized);
          setLoading(false);
          return;
        }
      }

      // Fallback to localStorage
      const localSessions = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith('session_')) {
          try {
            const sessionData = JSON.parse(localStorage.getItem(key));
            localSessions.push(normalizeSession(sessionData));
          } catch (e) {
            console.error('Error parsing session:', e);
          }
        }
      }
      
      // Sort by timestamp descending
      localSessions.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      setSessions(localSessions);
    } catch (error) {
      console.error('Error loading sessions:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  // Filter sessions based on status
  const filterSessions = useCallback(() => {
    let filtered = [...sessions];
    if (statusFilter === 'all') {
      filtered = [...sessions];
    } else {
      filtered = sessions.filter(session => {
        const status = session.status || 'in_progress';
        return status === statusFilter;
      });
    }

    filtered.sort((a, b) => {
      if (sortBy === 'score_desc') {
        return (b._score ?? -1) - (a._score ?? -1);
      }
      if (sortBy === 'score_asc') {
        return (a._score ?? 101) - (b._score ?? 101);
      }
      if (sortBy === 'created_desc') {
        return (b._createdAt || 0) - (a._createdAt || 0);
      }
      if (sortBy === 'created_asc') {
        return (a._createdAt || 0) - (b._createdAt || 0);
      }
      return (b._updatedAt || 0) - (a._updatedAt || 0);
    });

    setFilteredSessions(filtered);
  }, [sessions, statusFilter, sortBy]);

  // Load sessions on component mount
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Filter sessions when filter changes
  useEffect(() => {
    filterSessions();
  }, [filterSessions]);

  // Handle session deletion
  const handleDeleteSession = async (sessionId) => {
    if (!window.confirm('Are you sure you want to delete this session?')) {
      return;
    }

    try {
      // Try to delete from API
      await fetch(`${API_BASE}/api/ai-agent/threads/${sessionId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });

      // Also remove from localStorage
      localStorage.removeItem(`session_${sessionId}`);
      
      // Update local state
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
      
      // If we're viewing this session, go back to list
      if (currentSession && currentSession.session_id === sessionId) {
        setView('list');
        setCurrentSession(null);
        navigate('/sessions');
      }
    } catch (error) {
      console.error('Error deleting session:', error);
      alert('Failed to delete session. Please try again.');
    }
  };

  // Handle continue session
  const handleContinueSession = (sessionId) => {
    navigate(`/new?sid=${encodeURIComponent(sessionId)}`);
  };

  // Handle view session
  const handleViewSession = (session) => {
    setView('review');
    setCurrentSession(session);
    setActiveTab('summary');
    navigate(`/sessions?view=review&session_id=${session.session_id}${isQueueView ? '&from=queue' : ''}`);
  };

  // Handle back to list
  const handleBackToList = () => {
    setView('list');
    setCurrentSession(null);
    navigate(fromParam === 'queue' || isQueueView ? '/sessions?view=queue' : '/sessions');
  };

  // Format date
  const formatDate = (dateString) => {
    if (!dateString) return '';
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Get status display
  const getStatusDisplay = (status) => {
    const actualStatus = status || 'in_progress';
    return {
      completed: { text: 'Completed', color: 'green' },
      in_progress: { text: 'In Progress', color: 'orange' }
    }[actualStatus] || { text: 'In Progress', color: 'orange' };
  };

  // Format document type
  const formatDocumentType = (type) => {
    if (!type) return 'Session';
    return type.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  if (loading) {
    return (
      <div className="sessions-container">
        <div className="loading-state">
          <div className="loading-spinner"></div>
          <p>Loading sessions...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <button 
          onClick={() => navigate('/new')} 
          className="back-link"
        >
          ← Back to Workspace
        </button>
        
        {view === 'review' && currentSession ? (
          <>
            <button onClick={handleBackToList} className="back-link">
              ← All Sessions
            </button>
            <h1>{currentSession.name || currentSession.session_id}</h1>
          </>
        ) : (
          <>
            <h1>{isQueueView ? 'In Queue' : 'Your Sessions'}</h1>
            <p>
              {isQueueView
                ? 'Review scored sessions and prioritize what to run next.'
                : 'Select a session to view details.'}
            </p>
          </>
        )}
      </div>

      {view === 'review' && currentSession ? (
        <div className="session-detail">
          {/* Tab Navigation */}
          <ul className="session-tabs">
            <li 
              className={activeTab === 'summary' ? 'active' : ''}
              onClick={() => setActiveTab('summary')}
            >
              Summary
            </li>
            <li 
              className={activeTab === 'details' ? 'active' : ''}
              onClick={() => setActiveTab('details')}
            >
              Details
            </li>
            <li 
              className={activeTab === 'notes' ? 'active' : ''}
              onClick={() => setActiveTab('notes')}
            >
              Notes
            </li>
          </ul>

          {/* Tab Content */}
          <div className="tab-content">
            {activeTab === 'summary' && (
              <div className="tab-pane active">
                <div className="summary-grid">
                  <div className="summary-item">
                    <strong>Type:</strong> {formatDocumentType(currentSession.document_type)}
                  </div>
                  <div className="summary-item">
                    <strong>Phase:</strong> {currentSession.current_phase || 1}
                  </div>
                  <div className="summary-item">
                    <strong>Status:</strong> 
                    <span className={`status-badge ${currentSession.status || 'in_progress'}`}>
                      {getStatusDisplay(currentSession.status).text}
                    </span>
                  </div>
                  <div className="summary-item">
                    <strong>Created:</strong> {formatDate(currentSession.created)}
                  </div>
                  <div className="summary-item">
                    <strong>Last Updated:</strong> {formatDate(currentSession.timestamp)}
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'details' && (
              <div className="tab-pane active">
                <div className="chat-history-display">
                  {currentSession.chat_history && Array.isArray(currentSession.chat_history) ? (
                    currentSession.chat_history.map((msg, index) => (
                      <div key={index} className={`message ${msg.type}-message`}>
                        {msg.type === 'system' ? (
                          <div dangerouslySetInnerHTML={{ __html: msg.content }} />
                        ) : (
                          <div>{msg.content}</div>
                        )}
                      </div>
                    ))
                  ) : (
                    <div dangerouslySetInnerHTML={{ __html: currentSession.chat_history || '<p>No chat history available.</p>' }} />
                  )}
                </div>
              </div>
            )}

            {activeTab === 'notes' && (
              <div className="tab-pane active">
                <div className="notes-display">
                  {currentSession.notes && Object.keys(currentSession.notes).length > 0 ? (
                    Object.entries(currentSession.notes).map(([phaseKey, notesText]) => (
                      <div key={phaseKey} className="phase-notes">
                        <h4>{phaseKey.replace('phase', 'Phase ')}</h4>
                        {notesText.trim() ? (
                          <p>{notesText}</p>
                        ) : (
                          <p><em>No notes saved for this phase.</em></p>
                        )}
                      </div>
                    ))
                  ) : (
                    <p><em>No notes saved for this session.</em></p>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="session-actions">
            <button 
              onClick={() => handleContinueSession(currentSession.session_id)}
              className="action-button continue-button"
            >
              Continue Session
            </button>
            <button 
              onClick={() => handleDeleteSession(currentSession.session_id)}
              className="action-button delete-button"
            >
              Delete Session
            </button>
          </div>
        </div>
      ) : (
        <div className="sessions-list">
          {/* Filter Controls */}
          <div className="filter-controls">
            <label htmlFor="statusFilter">Show sessions:</label>
            <select 
              id="statusFilter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All</option>
              <option value="in_progress">In Progress</option>
              <option value="completed">Completed</option>
            </select>
            <label htmlFor="sortBy">Sort by:</label>
            <select
              id="sortBy"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              <option value="updated_desc">Last updated</option>
              <option value="score_desc">Highest score</option>
              <option value="score_asc">Lowest score</option>
              <option value="created_desc">Newest created</option>
              <option value="created_asc">Oldest created</option>
            </select>
          </div>

          {/* Sessions Table */}
          {sessions.length === 0 ? (
            <div className="empty-state">
              <p>No saved sessions yet. Start a wizard to create one.</p>
              <button 
                onClick={() => navigate('/new')}
                className="action-button continue-button"
              >
                Start New Analysis
              </button>
            </div>
          ) : filteredSessions.length === 0 ? (
            <div className="empty-state">
              <p>No sessions match "{statusFilter === 'all' ? 'All' : statusFilter.replace('_', ' ')}".</p>
            </div>
          ) : (
            <div className="sessions-table-container">
              <table className="sessions-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Title</th>
                    <th>Score</th>
                    <th>Type</th>
                    <th>Last Updated</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSessions.map((session) => {
                    const statusInfo = getStatusDisplay(session.status);
                    return (
                      <tr key={session.session_id}>
                        <td>
                          <span 
                            className="status-indicator"
                            style={{ color: statusInfo.color }}
                          >
                            {statusInfo.text}
                          </span>
                        </td>
                        <td className="session-title">
                          {session?.result?.project_name || session.name || session.session_id}
                        </td>
                        <td>{session._score == null ? '—' : session._score}</td>
                        <td>{formatDocumentType(session.document_type)}</td>
                        <td>{formatDate(session.timestamp)}</td>
                        <td>{formatDate(session.created)}</td>
                        <td>
                          <div className="table-actions">
                            <button
                              onClick={() => handleContinueSession(session.session_id)}
                              className="action-button continue-button"
                            >
                              Continue
                            </button>
                            <button
                              onClick={() => handleViewSession(session)}
                              className="action-button view-button"
                            >
                              View
                            </button>
                            <button
                              onClick={() => handleDeleteSession(session.session_id)}
                              className="action-button delete-button"
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Sessions;
