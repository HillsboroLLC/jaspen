import React, { useState } from 'react';
import './Footer.css';

export default function Footer() {
  const [email, setEmail] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [modalEmail, setModalEmail] = useState('');

  const openModal = e => {
    e.preventDefault();
    setModalEmail(email);
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
    setModalEmail('');
  };

  const handleModalSubmit = e => {
    e.preventDefault();
    console.log('Newsletter signup:', modalEmail);
    alert('Thank you for subscribing!');
    closeModal();
  };

  return (
    <>
      <footer className="footer" id="contact">
        <div className="container footer-content">
          <div className="footer-brand">
            <h4>Jaspen</h4>
            <p>Unlimited business analysis platform. Lifetime access. One payment.</p>
          </div>
          <div className="footer-newsletter">
            <h4>Get founder updates & insights</h4>
            <form className="newsletter-form" onSubmit={openModal}>
              <input
                type="email"
                placeholder="Enter your email"
                required
                value={email}
                onChange={e => setEmail(e.target.value)}
              />
              <button type="submit" className="btn btn-primary">
                Subscribe
              </button>
            </form>
          </div>
          <div className="footer-contact">
            <h4>Contact</h4>
            <p>Email: hello@jaspen.ai</p>
          </div>
        </div>
        <div className="footer-bottom">
          <p>&copy; 2025 Jaspen. All rights reserved.</p>
        </div>
      </footer>

      {showModal && (
        <div className="modal-overlay">
          <div className="modal-content newsletter-modal">
            <button className="close" onClick={closeModal}>&times;</button>
            <h3>Subscribe to Jaspen Newsletter</h3>
            <p>Stay updated with founder insights and product news.</p>
            <form onSubmit={handleModalSubmit} className="modal-form">
              <input
                type="email"
                placeholder="Your email address"
                required
                value={modalEmail}
                onChange={e => setModalEmail(e.target.value)}
              />
              <button type="submit" className="btn btn-primary modal-submit">
                Confirm Subscribe
              </button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
