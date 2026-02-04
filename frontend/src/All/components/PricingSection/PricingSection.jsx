import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import './PricingSection.css';

export default function PricingSection() {
  const [showModal, setShowModal] = useState(false);
  const [waitlistData, setWaitlistData] = useState({
    fullName: '',
    email: '',
    company: ''
  });


  const enterprise = [
    {
      name: 'Transform Standard',
      amount: '15,000',
      savings: 'Save $1.3M+',
      features: [
        '5 enterprise seats',
        '100 analysis credits/month',
        'All analysis tools',
        'Buy additional credits',
        'Add more seats',
        'Basic custom programming',
      ],
      buttonText: 'Start Transform Standard',
      buttonClass: 'btn-primary',
      action: 'waitlist'
    },
    {
      name: 'Transform Premium',
      amount: '25,000',
      savings: 'Save $1.2M+',
      features: [
        '10 enterprise seats',
        '250 analysis credits/month',
        'All analysis tools',
        'Buy additional credits',
        'Add more seats',
        'Advanced custom programming',
      ],
      buttonText: 'Start Transform Premium',
      buttonClass: 'btn-primary',
      action: 'waitlist'
    },
    {
      name: 'Transform Enterprise',
      amount: '50,000',
      savings: 'Save $1.8M+',
      features: [
        '25 enterprise seats',
        '500 analysis credits/month',
        'All analysis tools',
        'Buy additional credits',
        'Add more seats',
        'Full custom programming',
      ],
      buttonText: 'Start Transform Enterprise',
      buttonClass: 'btn-primary',
      action: 'waitlist'
    },
  ];

  const data = enterprise;

  const openModal = () => setShowModal(true);
  const closeModal = () => setShowModal(false);

  const handleWaitlistChange = e => {
    const { id, value } = e.target;
    setWaitlistData(prev => ({ ...prev, [id]: value }));
  };

  const handleWaitlistSubmit = e => {
    e.preventDefault();
    console.log('Waitlist submission:', waitlistData);
    alert('Thank you! We will contact you soon.');
    setWaitlistData({ fullName: '', email: '', company: '' });
    closeModal();
  };

  return (
<section className="pricing enterprise-view" id="pricing">
      <div className="container">
        <h2 className="section-title">Choose Your Business Analysis Solution</h2>


<div className="savings-highlight">
  Replace $500K–$2M consulting projects with continuous analysis + custom execution tools
</div>

        <div className="pricing-grid">
          {data.map((p, i) => (
            <div className="pricing-tier" key={i}>
<div className="roi-badge">{p.savings}</div>

              <h3 className="tier-name">{p.name}</h3>


              <div className="tier-price">
                <span className="tier-currency">$</span>
                <span className="tier-amount">{p.amount}</span>
                <span className="tier-period">/month</span>
              </div>

              <ul className="tier-features">
                {p.features.map((f, j) => {
                  const negative = f.toLowerCase().startsWith('no ');
                  return (
                    <li key={j}>
                      <i className={`fas fa-${negative ? 'times' : 'check'}`}></i> {f}
                    </li>
                  );
                })}
              </ul>

              {p.action === 'signup' ? (
                <Link
                  to="/sign-up"
                  className={`btn ${p.buttonClass} tier-cta`}
                >
                  {p.buttonText}
                </Link>
              ) : (
                <button
                  type="button"
                  className={`btn ${p.buttonClass} tier-cta`}
                  onClick={openModal}
                >
                  {p.buttonText}
                </button>
              )}
            </div>
          ))}
        </div>

        {showModal && (
          <div className="modal-overlay" onClick={closeModal}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <button className="close" onClick={closeModal}>&times;</button>
              <h3>Contact Us for Enterprise Plans</h3>
              <form onSubmit={handleWaitlistSubmit} className="waitlist-form">
                <input
                  id="fullName"
                  type="text"
                  placeholder="Full Name"
                  required
                  value={waitlistData.fullName}
                  onChange={handleWaitlistChange}
                />
                <input
                  id="email"
                  type="email"
                  placeholder="Business Email"
                  required
                  value={waitlistData.email}
                  onChange={handleWaitlistChange}
                />
                <input
                  id="company"
                  type="text"
                  placeholder="Company Name"
                  required
                  value={waitlistData.company}
                  onChange={handleWaitlistChange}
                />
                <button type="submit" className="btn btn-primary">
                  Contact Us
                </button>
              </form>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
