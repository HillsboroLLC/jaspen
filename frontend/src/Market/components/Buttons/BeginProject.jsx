import React, { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faComments,
  faBalanceScale,
  faProjectDiagram,
  faSearch,
  faChartLine
} from '@fortawesome/free-solid-svg-icons';
import './BeginProject.css';

/**
 * BeginProjectMenu - Reusable dropdown menu for Market IQ pages
 * 
 * @param {string} currentPage - The current page name to exclude from menu
 *   Options: 'dashboard', 'explore', 'scenario', 'chat'
 * @param {function} onNavigate - Callback function for navigation
 *   Receives page name as parameter: 'dashboard', 'explore', 'scenario', 'chat', 'project'
 */
export default function BeginProjectMenu({ currentPage, onNavigate }) {
  const [isOpen, setIsOpen] = useState(false);

  const menuItems = [
    {
      id: 'dashboard',
      label: 'View Dashboard',
      icon: faChartLine,
      action: () => onNavigate('dashboard')
    },
    {
      id: 'explore',
      label: 'Explore Analysis',
      icon: faSearch,
      action: () => onNavigate('explore')
    },
    {
      id: 'chat',
      label: 'Discuss with Analyst',
      icon: faComments,
      action: () => onNavigate('chat')
    },
    {
      id: 'scenario',
      label: 'Scenario Modeling',
      icon: faBalanceScale,
      action: () => onNavigate('scenario')
    },
    {
      id: 'project',
      label: 'Begin Project',
      icon: faProjectDiagram,
      action: () => onNavigate('project')
    }
  ];

  // Filter out the current page
  const filteredItems = menuItems.filter(item => item.id !== currentPage);

  const handleItemClick = (action) => {
    action();
    setIsOpen(false);
  };

  return (
    <div className="begin-project-menu">
      <button 
        className="begin-project-btn"
        onClick={() => setIsOpen(!isOpen)}
      >
        <span>Begin Project</span>
        <span className={`begin-project-arrow ${isOpen ? 'open' : ''}`}>▼</span>
      </button>
      {isOpen && (
        <div className="begin-project-dropdown">
          {filteredItems.map((item) => (
            <button
              key={item.id}
              className="begin-project-item"
              onClick={() => handleItemClick(item.action)}
            >
              <FontAwesomeIcon icon={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
