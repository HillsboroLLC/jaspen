import React from 'react';
import './FounderModal.css';

export default function FounderModal({ isOpen, onClose }) {
  if (!isOpen) return null;
  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <button className="close" onClick={onClose}>&times;</button>
        <h4><i className="fas fa-crown"></i> Founder Lifetime Access</h4>
        <p>Founder billing is managed through secure checkout. Continue to pricing to complete setup.</p>
        <div className="founder-modal-actions">
          <a className="founder-modal-primary" href="/pages/pricing">Open Pricing</a>
          <button type="button" className="founder-modal-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
