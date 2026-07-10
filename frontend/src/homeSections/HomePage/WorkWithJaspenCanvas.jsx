import React from 'react';
import JaspenWorkspace from './JaspenWorkspace';
import { SCENARIOS } from './scenarioData';
import './WorkWithJaspenCanvas.css';

// Full-width "Work with Jaspen" section: the intro beside the live workspace.
export default function WorkWithJaspenCanvas({ demo }) {
  const d = demo || SCENARIOS[0].demo;
  return (
    <section className="wj-section">
      <div className="wj-layout">
        <div className="wj-intro" id="intro-header">
          <span className="wj-eyebrow">Work with Jaspen</span>
          <h3>This is Jaspen.</h3>
          <p>An AI partner that evaluates ideas, prioritizes opportunities, and structures cross-functional work into coordinated, executable plans.</p>
          <p className="wj-tagline">Bring your problem. Leave with clarity.</p>
        </div>

        <JaspenWorkspace demo={d} />
      </div>
    </section>
  );
}
