// filepath: src/All/Login/Login.jsx
import React, { useState } from 'react';
import { Link, useNavigate, Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../shared/auth/AuthContext';
import '@fortawesome/fontawesome-free/css/all.min.css'; // ensure FA is available
import './Login.css';

export default function Login() {
  const [email, setEmail]               = useState('');
  const [password, setPassword]         = useState('');
  const [remember, setRemember]         = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const { login, user, loading }        = useAuth();
  const navigate                        = useNavigate();
  const loc                             = useLocation();

  // Respect ?next= for post-login redirect
  const params = new URLSearchParams(loc.search);
  const next = params.get('next') || '/pages/home';

  if (user) return <Navigate to={next} replace />;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMessage('');

    if (!email || !password) {
      setErrorMessage('Please fill in all fields');
      return;
    }

    const result = await login(email, password);
    if (result.success) {
      if (remember) localStorage.setItem('rememberMe', 'true');
      navigate(next, { replace: true });
    } else {
      setErrorMessage(result.error || 'Login failed');
    }
  };

  return (
    <div className="login-page-wrapper">
      {errorMessage && <div className="login-error">{errorMessage}</div>}

      <div className="login-container">
        <div className="heading">
          <h2>Login</h2>
          <p>Welcome back! Please log in to your account.</p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email Address</label>
            <input
              type="email"
              id="email"
              name="email"
              required
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={loading}
              autoComplete="username"
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              type="password"
              id="password"
              name="password"
              required
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              autoComplete="current-password"
            />
          </div>

          <div className="remember-forgot">
            <label>
              <input
                type="checkbox"
                name="remember"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                disabled={loading}
              />{' '}
              Remember me
            </label>
            <Link to="/forgot-password">Forgot Password?</Link>
          </div>

          <button type="submit" className="submit-btn" disabled={loading}>
            {loading ? 'Logging in...' : 'Login'}
          </button>
        </form>

        <p className="signup-link">
          Don't have an account? <Link to="/sign-up">Sign Up</Link>
        </p>
      </div>

    </div>
  );
}
