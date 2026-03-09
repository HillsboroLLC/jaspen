import React from 'react';
import { useAuth } from '../../shared/auth/AuthContext';
import './AuthenticatedHeader.css';

const AuthenticatedHeader = ({ title }) => {
  const { user, logout } = useAuth();

  return (
    <header className="authenticated-header">
      <div className="authenticated-header-content">
        <div className="header-left">
          <a href="/profile" className="logo-link">
            <span className="logo-text">Jaspen</span>
          </a>
          {title && <h1 className="page-title">{title}</h1>}
        </div>
        
        <div className="header-right">
          <div className="user-info">
            <i className="fas fa-user" />
            <span className="user-name">{user?.name || user?.email}</span>
          </div>
          
          <span 
            className="logout-text"
            onClick={logout}
            title="Logout"
          >
            Logout
          </span>
        </div>
      </div>
    </header>
  );
};

export default AuthenticatedHeader;
