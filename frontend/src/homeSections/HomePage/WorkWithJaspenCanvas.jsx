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
          {/* The previous copy listed three generic capabilities in a row, all
              of which a reader already believes general AI does. This says the
              one thing it does not. */}
          <h3>This is Jaspen.</h3>
          <p>Jaspen reads what you bring, grades the evidence behind every criterion, and shows how much of your direction the evidence actually supports.</p>
          <p className="wj-tagline">Bring what you are weighing. Leave knowing what it rests on.</p>
        </div>

        <JaspenWorkspace demo={d} />
      </div>
    </section>
  );
}
