// src/pages/SignUp/SignUp.jsx
import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import '@fortawesome/fontawesome-free/css/all.min.css';
import './SignUp.css';

const PLAN_OPTIONS = [
  { key: 'essential', label: 'Essential – $39.99/month (7-day free trial)' },
  { key: 'growth',    label: 'Growth – $99.99/month' },
  { key: 'founder',   label: 'Founder – $2,999 one-time' },
];

export default function SignUp() {
  const [fullname, setFullname]   = useState('');
  const [email, setEmail]         = useState('');
  const [password, setPassword]   = useState('');
  const [confirm, setConfirm]     = useState('');
  const [plan, setPlan]           = useState('');
  const [seatCount, setSeatCount] = useState(0);
  const [showSeats, setShowSeats] = useState(false);
  const [error, setError]         = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    setShowSeats(plan === 'growth');
  }, [plan]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (password !== confirm) return setError('Passwords do not match');
    if (!plan) return setError('Please select a plan');

    try {
      await axios.post('/api/auth/signup', {
        name: fullname,
        email,
        password,
        plan_key: plan,
        extra_seats: seatCount
      });
      navigate(`/pricing?plan=${plan}`);
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.message || 'Signup failed. Please try again.');
    }
  };

  return (
    <div className="signup-layout">
      <div className="form-container">
        <h2>Create Your Account</h2>
        {error && <p className="error">{error}</p>}

        <form onSubmit={handleSubmit}>
          <label>
            Full Name
            <input
              type="text"
              value={fullname}
              required
              onChange={e => setFullname(e.target.value)}
            />
          </label>

          <label>
            Email Address
            <input
              type="email"
              value={email}
              required
              onChange={e => setEmail(e.target.value)}
            />
          </label>

          <label>
            Password
            <input
              type="password"
              value={password}
              required
              onChange={e => setPassword(e.target.value)}
            />
          </label>

          <label>
            Confirm Password
            <input
              type="password"
              value={confirm}
              required
              onChange={e => setConfirm(e.target.value)}
            />
          </label>

          <label>
            Select Plan
            <select
              value={plan}
              required
              onChange={e => setPlan(e.target.value)}
            >
              <option value="">— Choose a plan —</option>
              {PLAN_OPTIONS.map(p => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>

          {showSeats && (
            <label>
              Additional Seats
              <input
                type="number"
                min="0"
                step="1"
                value={seatCount}
                onChange={e => setSeatCount(Number(e.target.value))}
              />
              <small>$99.99 per extra seat/month (1 seat included)</small>
            </label>
          )}

          {/* --- Terms row (fixed alignment & wrapping) --- */}
          <div className="terms">
            <input id="terms" type="checkbox" required />
            <label htmlFor="terms">
              I agree to the{' '}
              <a href="/terms" target="_blank" rel="noopener noreferrer">
                Terms &amp; Conditions
              </a>
            </label>
          </div>

          <button type="submit" className="submit-btn">Sign Up</button>
        </form>

        <p className="login-link">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>

    </div>
  );
}
