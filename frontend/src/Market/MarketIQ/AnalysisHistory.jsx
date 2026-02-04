// src/pages/MarketIQ/AnalysisHistory.jsx
import React from 'react';
import { storage } from '../../lib/MarketIQClient';
import '../styles/MarketIQ.css';  // Correct path

const AnalysisHistory = ({ onClose, onSelectAnalysis }) => {
  const items = storage.getHistory();
  return (
    <div className="history-panel">
      <div className="history-header">
        <h3>Analysis History</h3>
        <button onClick={onClose}>Close</button>
      </div>
      {items.length === 0 ? (
        <div className="history-empty">No saved analyses yet.</div>
      ) : (
        <ul className="history-list">
          {items.map((it, idx) => (
            <li key={idx} className="history-item">
              <div className="history-title">{it.result?.project_name || `Analysis ${it.id}`}</div>
              <div className="history-meta">{new Date(it.createdAt).toLocaleString()}</div>
              <button className="history-open" onClick={()=>onSelectAnalysis(it.result)}>Open</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default AnalysisHistory;
