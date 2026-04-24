import React from 'react';
import './FieldError.css';

export default function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p id={id} className="jas-field-error" role="alert">
      {message}
    </p>
  );
}
