import React, { useState, useCallback, useRef } from 'react';
import JaspenAgentDemo from './JaspenAgentDemo';
import JaspenScenarioDemo from './JaspenScenarioDemo';
import './JaspenAgentDemo.css';

const DEMOS = [JaspenAgentDemo, JaspenScenarioDemo];

export default function JaspenDemoCycler() {
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);
  const switchTimer = useRef(null);

  const handleComplete = useCallback(() => {
    setVisible(false);
    switchTimer.current = setTimeout(() => {
      setIndex((prev) => (prev + 1) % DEMOS.length);
      setVisible(true);
    }, 600);
  }, []);

  const ActiveDemo = DEMOS[index];

  return (
    <div
      className="jad-cycler"
      style={{ opacity: visible ? 1 : 0, transition: 'opacity 600ms ease' }}
    >
      <ActiveDemo key={index} onComplete={handleComplete} />
    </div>
  );
}
