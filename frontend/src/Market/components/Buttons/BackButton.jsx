import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowLeft } from '@fortawesome/free-solid-svg-icons';
import './BackButton.css';

export default function BackButton({ onClick, label = 'Back' }) {
  return (
    <button className="back-button" onClick={onClick}>
      <FontAwesomeIcon icon={faArrowLeft} />
      {label && <span>{label}</span>}
    </button>
  );
}
