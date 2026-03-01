// src/Ops/PMDashboard/PMCustomDropdown.jsx
import React, { useState, useRef, useEffect } from 'react';
import styles from './PMCustomDropdown.module.css';

const PMCustomDropdown = ({ options, onSelect, placeholder = "Select…", label }) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const handleSelect = (value) => {
    onSelect(value);
    setIsOpen(false);
  };

  const toggleDropdown = () => {
    setIsOpen(prev => !prev);
  };

  return (
    <div className={styles.customDropdownContainer} ref={dropdownRef}>
      {label && <span className={styles.dropdownLabel}>{label}</span>}
      <div className={styles.dropdownWrapper}>
        <button
          type="button"
          className={styles.dropdownButton}
          onClick={toggleDropdown}
          aria-expanded={isOpen}
          aria-haspopup="true"
        >
          <span>{placeholder}</span>
          <i className={`fas fa-chevron-down ${styles.dropdownArrow} ${isOpen ? styles.open : ''}`}></i>
        </button>

        {isOpen && (
          <div className={styles.dropdownMenu}>
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                className={styles.dropdownItem}
                onClick={() => handleSelect(option.value)}
              >
                <span>{option.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default PMCustomDropdown;
