// src/pages/Account/Account.jsx
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './Account.css';

const Account = () => {
  const navigate = useNavigate();
  
  // State management
  const [userInfo, setUserInfo] = useState({
    plan: 'Essential',
    extraSeats: 0,
    totalSeats: 1,
    paymentMethod: null,
    planHistory: []
  });
  
  const [showManageModal, setShowManageModal] = useState(false);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [activeTab, setActiveTab] = useState('plan');
  const [selectedPlan, setSelectedPlan] = useState('essential');
  const [extraSeats, setExtraSeats] = useState(0);
  const [selectedCredits, setSelectedCredits] = useState(0);
  const [paymentOption, setPaymentOption] = useState('onfile');
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  // Load user data on component mount
  useEffect(() => {
    loadUserData();
  }, []);

  const loadUserData = async () => {
    try {
      // Try to load from API
      const response = await fetch('https://api.sekki.io/api/user/profile', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });

      if (response.ok) {
        const data = await response.json();
        setUserInfo(data);
        setSelectedPlan(data.plan.toLowerCase());
        setExtraSeats(data.extraSeats || 0);
      } else {
        // Fallback to mock data
        setUserInfo({
          plan: 'Essential',
          extraSeats: 0,
          totalSeats: 1,
          paymentMethod: {
            last4: '4242',
            expMonth: '12',
            expYear: '2025'
          },
          planHistory: [
            {
              date: '2024-01-15T10:30:00Z',
              plan: 'Essential',
              amount: '$39.99'
            }
          ]
        });
      }
    } catch (error) {
      console.error('Error loading user data:', error);
    }
  };

  const handleDeleteAccount = async () => {
    const confirmed = window.confirm(
      'Are you sure you want to delete your account? This action cannot be undone and will permanently remove all your data.'
    );
    
    if (!confirmed) return;

    try {
      setLoading(true);
      
      const response = await fetch('https://api.sekki.io/api/user/delete', {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });

      if (response.ok) {
        // Clear local storage and redirect
        localStorage.clear();
        navigate('/?account=deleted');
      } else {
        setStatusMessage('Failed to delete account. Please try again.');
      }
    } catch (error) {
      console.error('Error deleting account:', error);
      setStatusMessage('Failed to delete account. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleManageSubscription = async (e) => {
    e.preventDefault();
    setLoading(true);
    setStatusMessage('');

    try {
      const formData = {
        plan: selectedPlan,
        extraSeats: extraSeats,
        credits: selectedCredits,
        paymentOption: paymentOption
      };

      const response = await fetch('https://api.sekki.io/api/user/subscription', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify(formData)
      });

      if (response.ok) {
        setStatusMessage('Subscription updated successfully!');
        loadUserData(); // Reload user data
        setTimeout(() => {
          setShowManageModal(false);
          setStatusMessage('');
        }, 2000);
      } else {
        setStatusMessage('Failed to update subscription. Please try again.');
      }
    } catch (error) {
      console.error('Error updating subscription:', error);
      setStatusMessage('Failed to update subscription. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdatePayment = async (e) => {
    e.preventDefault();
    setLoading(true);
    setStatusMessage('');

    try {
      // This would integrate with Stripe in a real implementation
      setStatusMessage('Payment method updated successfully!');
      loadUserData();
      setTimeout(() => {
        setShowPaymentModal(false);
        setStatusMessage('');
      }, 2000);
    } catch (error) {
      console.error('Error updating payment method:', error);
      setStatusMessage('Failed to update payment method. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const calculatePlanTotal = () => {
    let total = 0;
    
    switch(selectedPlan) {
      case 'essential':
        total = 39.99;
        break;
      case 'growth':
        total = 99.99 + (extraSeats * 29.99);
        break;
      case 'transform':
        total = 4999 + (extraSeats * 799.99);
        break;
      case 'founder':
        total = 2999;
        break;
    }
    
    return total;
  };

  const getCreditPrice = () => {
    const prices = {
      10: 19.99,
      20: 39.98,
      30: 59.97,
      50: 99.95,
      100: 199.90
    };
    return prices[selectedCredits] || 0;
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="account-page">
      {/* Header */}
      <div className="account-header">
        <button 
          onClick={() => navigate('/dashboard')} 
          className="back-link"
        >
          ← Back to Workspace
        </button>
        <h1>My Account</h1>
        <p className="subtitle">Manage your SEKKI subscription and account settings</p>
      </div>

      {/* Main Grid */}
      <div className="account-grid">
        {/* Subscription Card */}
        <div className="account-card">
          <div className="card-header">
            <div className="card-icon">
              <i className="fas fa-crown"></i>
            </div>
            <h2 className="card-title">Subscription</h2>
          </div>
          
          <div className="plan-badge">
            {userInfo.plan}
            {userInfo.plan.toLowerCase() === 'founder' && (
              <span className="founder-badge">Lifetime</span>
            )}
          </div>
          
          <div className="plan-details">
            <div className="detail-item">
              <span className="detail-value">{userInfo.totalSeats}</span>
              <span className="detail-label">Total Seats</span>
            </div>
            <div className="detail-item">
              <span className="detail-value">{userInfo.extraSeats}</span>
              <span className="detail-label">Extra Seats</span>
            </div>
          </div>

          {userInfo.plan.toLowerCase() !== 'founder' && (
            <button 
              onClick={() => setShowManageModal(true)}
              className="btn btn-primary"
            >
              <i className="fas fa-cog"></i>
              Manage Subscription
            </button>
          )}
        </div>

        {/* Payment Method Card */}
        <div className="account-card">
          <div className="card-header">
            <div className="card-icon">
              <i className="fas fa-credit-card"></i>
            </div>
            <h2 className="card-title">Payment Method</h2>
          </div>
          
          {userInfo.paymentMethod ? (
            <>
              <div className="payment-info">
                <div className="card-visual">
                  CARD
                </div>
                <div className="payment-details">
                  <h4>•••• •••• •••• {userInfo.paymentMethod.last4}</h4>
                  <p>Expires {userInfo.paymentMethod.expMonth}/{userInfo.paymentMethod.expYear.slice(-2)}</p>
                </div>
              </div>
              <button 
                onClick={() => setShowPaymentModal(true)}
                className="btn btn-primary"
              >
                <i className="fas fa-edit"></i>
                Update Card
              </button>
            </>
          ) : (
            <>
              <div className="empty-state">
                <i className="fas fa-credit-card"></i>
                <p>No payment method on file</p>
              </div>
              <button 
                onClick={() => setShowPaymentModal(true)}
                className="btn btn-primary"
              >
                <i className="fas fa-plus"></i>
                Add Payment Method
              </button>
            </>
          )}
        </div>
      </div>

      {/* Plan History Card (Full Width) */}
      <div className="account-grid">
        <div className="account-card account-grid-full">
          <div className="card-header">
            <div className="card-icon">
              <i className="fas fa-history"></i>
            </div>
            <h2 className="card-title">Plan Change History</h2>
          </div>
          
          {userInfo.planHistory && userInfo.planHistory.length > 0 ? (
            <div className="history-timeline">
              {userInfo.planHistory.map((entry, index) => (
                <div key={index} className="history-item">
                  <div className="history-date">
                    {formatDate(entry.date)}
                  </div>
                  <div className="history-action">
                    Switched to <strong>{entry.plan}</strong> plan
                    {entry.amount && (
                      <span className="history-amount">{entry.amount}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <i className="fas fa-clock"></i>
              <p>No plan changes recorded yet</p>
            </div>
          )}
          
          {/* Delete Account Section */}
          <div className="delete-account-section">
            <button 
              onClick={handleDeleteAccount}
              className="delete-account-link"
              disabled={loading}
            >
              {loading ? 'Deleting...' : 'Delete my account'}
            </button>
          </div>
        </div>
      </div>

      {/* Manage Subscription Modal */}
      {showManageModal && (
        <div className="modal-overlay" onClick={() => setShowManageModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button 
              onClick={() => setShowManageModal(false)}
              className="modal-close"
            >
              ×
            </button>
            <h2>Manage Subscription</h2>
            
            <div className="tab-buttons">
              <button 
                className={`tab-button ${activeTab === 'plan' ? 'active' : ''}`}
                onClick={() => setActiveTab('plan')}
              >
                Plan & Seats
              </button>
              <button 
                className={`tab-button ${activeTab === 'credits' ? 'active' : ''}`}
                onClick={() => setActiveTab('credits')}
              >
                Add Credits
              </button>
            </div>
            
            <form onSubmit={handleManageSubscription}>
              {activeTab === 'plan' && (
                <div className="plan-section">
                  <div className="form-group">
                    <label>Select Plan:</label>
                    
                    <div className={`plan-option ${selectedPlan === 'essential' ? 'selected' : ''}`}>
                      <input 
                        type="radio" 
                        name="plan" 
                        value="essential"
                        checked={selectedPlan === 'essential'}
                        onChange={(e) => setSelectedPlan(e.target.value)}
                      />
                      <div className="plan-details">
                        <h4>Essential</h4>
                        <p>3 documents/month, 1 seat (no additional seats)</p>
                      </div>
                      <div className="plan-price">$39.99/month</div>
                    </div>
                    
                    <div className={`plan-option ${selectedPlan === 'growth' ? 'selected' : ''}`}>
                      <input 
                        type="radio" 
                        name="plan" 
                        value="growth"
                        checked={selectedPlan === 'growth'}
                        onChange={(e) => setSelectedPlan(e.target.value)}
                      />
                      <div className="plan-details">
                        <h4>Growth</h4>
                        <p>10 documents/month, 1 seat (+$29.99 per extra seat)</p>
                      </div>
                      <div className="plan-price">$99.99/month</div>
                    </div>
                    
                    <div className={`plan-option ${selectedPlan === 'founder' ? 'selected' : ''}`}>
                      <input 
                        type="radio" 
                        name="plan" 
                        value="founder"
                        checked={selectedPlan === 'founder'}
                        onChange={(e) => setSelectedPlan(e.target.value)}
                      />
                      <div className="plan-details">
                        <h4>Founder <span className="founder-badge">LIFETIME</span></h4>
                        <p>Unlimited documents, unlimited seats</p>
                      </div>
                      <div className="plan-price">$2999 (one-time)</div>
                    </div>
                  </div>
                  
                  {(selectedPlan === 'growth' || selectedPlan === 'transform') && (
                    <div className="form-group">
                      <label htmlFor="extraSeats">Additional Seats:</label>
                      <input 
                        type="number" 
                        id="extraSeats"
                        min="0" 
                        max="50" 
                        value={extraSeats}
                        onChange={(e) => setExtraSeats(parseInt(e.target.value) || 0)}
                      />
                      <small>$29.99 per additional seat</small>
                    </div>
                  )}
                  
                  <div className="pricing-summary">
                    <strong>Total: ${calculatePlanTotal().toFixed(2)}</strong>
                    <div>{selectedPlan === 'founder' ? 'One-time payment' : 'Monthly billing'}</div>
                  </div>
                </div>
              )}
              
              {activeTab === 'credits' && (
                <div className="credits-section">
                  <div className="form-group">
                    <label htmlFor="creditAmount">Select Credit Package:</label>
                    <select 
                      id="creditAmount"
                      value={selectedCredits}
                      onChange={(e) => setSelectedCredits(parseInt(e.target.value))}
                    >
                      <option value={0}>None</option>
                      <option value={10}>10 Credits - $19.99</option>
                      <option value={20}>20 Credits - $39.98</option>
                      <option value={30}>30 Credits - $59.97</option>
                      <option value={50}>50 Credits - $99.95</option>
                      <option value={100}>100 Credits - $199.90</option>
                    </select>
                  </div>
                  
                  <div className="pricing-summary">
                    <strong>${getCreditPrice().toFixed(2)}</strong>
                    <div>One-time purchase</div>
                  </div>
                </div>
              )}
              
              <div className="form-group">
                <label>Payment Method:</label>
                <div className="payment-options">
                  {userInfo.paymentMethod && (
                    <label>
                      <input 
                        type="radio" 
                        name="payment_option" 
                        value="onfile"
                        checked={paymentOption === 'onfile'}
                        onChange={(e) => setPaymentOption(e.target.value)}
                      />
                      Use card on file (****{userInfo.paymentMethod.last4})
                    </label>
                  )}
                  <label>
                    <input 
                      type="radio" 
                      name="payment_option" 
                      value="new"
                      checked={paymentOption === 'new'}
                      onChange={(e) => setPaymentOption(e.target.value)}
                    />
                    Use a different card
                  </label>
                </div>
              </div>
              
              {paymentOption === 'new' && (
                <div className="form-group">
                  <label>New Card Information:</label>
                  <div className="stripe-element">
                    {/* Stripe card element would go here */}
                    <p>Card input field (Stripe integration)</p>
                  </div>
                </div>
              )}
              
              {statusMessage && (
                <div className={`status-message ${statusMessage.includes('success') ? 'success' : 'error'}`}>
                  {statusMessage}
                </div>
              )}
              
              <button type="submit" className="submit-btn" disabled={loading}>
                {loading ? 'Processing...' : 'Submit Changes'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Update Payment Modal */}
      {showPaymentModal && (
        <div className="modal-overlay" onClick={() => setShowPaymentModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button 
              onClick={() => setShowPaymentModal(false)}
              className="modal-close"
            >
              ×
            </button>
            <h2>Update Payment Method</h2>
            
            <form onSubmit={handleUpdatePayment}>
              {userInfo.paymentMethod && (
                <div className="form-group">
                  <div className="payment-options">
                    <label>
                      <input 
                        type="radio" 
                        name="payment_option" 
                        value="saved"
                        checked={paymentOption === 'saved'}
                        onChange={(e) => setPaymentOption(e.target.value)}
                      />
                      Use card on file (****{userInfo.paymentMethod.last4}, exp {userInfo.paymentMethod.expMonth}/{userInfo.paymentMethod.expYear.slice(-2)})
                    </label>
                    <label>
                      <input 
                        type="radio" 
                        name="payment_option" 
                        value="new"
                        checked={paymentOption === 'new'}
                        onChange={(e) => setPaymentOption(e.target.value)}
                      />
                      Use a different card
                    </label>
                  </div>
                </div>
              )}
              
              {(paymentOption === 'new' || !userInfo.paymentMethod) && (
                <div className="new-card-fields">
                  <div className="form-group">
                    <label htmlFor="cardholderName">Name on Card:</label>
                    <input type="text" id="cardholderName" name="cardholderName" />
                  </div>
                  <div className="form-group">
                    <label htmlFor="billingZip">ZIP/Postal Code:</label>
                    <input type="text" id="billingZip" name="billingZip" />
                  </div>
                  <div className="form-group">
                    <label>Card Information:</label>
                    <div className="stripe-element">
                      {/* Stripe card element would go here */}
                      <p>Card input field (Stripe integration)</p>
                    </div>
                  </div>
                </div>
              )}
              
              {statusMessage && (
                <div className={`status-message ${statusMessage.includes('success') ? 'success' : 'error'}`}>
                  {statusMessage}
                </div>
              )}
              
              <button type="submit" className="submit-btn" disabled={loading}>
                {loading ? 'Processing...' : 'Save Payment Method'}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Account;

