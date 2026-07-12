import React from 'react';
import './FlowIllustrated.css';

/* ── Simple reusable person shapes ── */
function Person({ x, y, color = '#a0036c', shirtColor, scale = 1, flip = false }) {
  const sc = `scale(${flip ? -scale : scale}, ${scale})`;
  const tx = flip ? -(x * 2 + 30) : 0;
  return (
    <g transform={`translate(${x}, ${y})`}>
      <g transform={`translate(${tx}, 0) ${sc}`}>
        {/* Head */}
        <circle cx="15" cy="8" r="9" fill="#f4c5a0" />
        {/* Hair */}
        <ellipse cx="15" cy="2" rx="9" ry="5" fill={color} />
        {/* Body / shirt */}
        <rect x="7" y="17" width="16" height="20" rx="4" fill={shirtColor || color} />
        {/* Left arm */}
        <rect x="1" y="18" width="7" height="14" rx="3.5" fill={shirtColor || color} />
        {/* Right arm */}
        <rect x="22" y="18" width="7" height="14" rx="3.5" fill={shirtColor || color} />
        {/* Left leg */}
        <rect x="8" y="35" width="7" height="16" rx="3.5" fill="#161f3b" />
        {/* Right leg */}
        <rect x="15" y="35" width="7" height="16" rx="3.5" fill="#161f3b" />
        {/* Shoes */}
        <ellipse cx="11" cy="51" rx="5" ry="3" fill="#333" />
        <ellipse cx="19" cy="51" rx="5" ry="3" fill="#333" />
      </g>
    </g>
  );
}

function PersonPointing({ x, y, color = '#a0036c', shirtColor, flip = false }) {
  const sc = flip ? 'scale(-1,1)' : 'scale(1,1)';
  const tx = flip ? -(x * 2 + 30) : 0;
  return (
    <g transform={`translate(${x}, ${y})`}>
      <g transform={`translate(${tx}, 0) ${sc}`}>
        <circle cx="15" cy="8" r="9" fill="#f4c5a0" />
        <ellipse cx="15" cy="2" rx="9" ry="5" fill={color} />
        <rect x="7" y="17" width="16" height="20" rx="4" fill={shirtColor || color} />
        {/* Pointing arm up-right */}
        <line x1="23" y1="22" x2="40" y2="8" stroke={shirtColor || color} strokeWidth="7" strokeLinecap="round" />
        {/* Other arm down */}
        <rect x="1" y="20" width="7" height="12" rx="3.5" fill={shirtColor || color} />
        <rect x="8" y="35" width="7" height="16" rx="3.5" fill="#161f3b" />
        <rect x="15" y="35" width="7" height="16" rx="3.5" fill="#161f3b" />
        <ellipse cx="11" cy="51" rx="5" ry="3" fill="#333" />
        <ellipse cx="19" cy="51" rx="5" ry="3" fill="#333" />
      </g>
    </g>
  );
}

function PersonSitting({ x, y, color = '#a0036c', shirtColor }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <circle cx="15" cy="8" r="9" fill="#f4c5a0" />
      <ellipse cx="15" cy="2" rx="9" ry="5" fill={color} />
      <rect x="7" y="17" width="16" height="18" rx="4" fill={shirtColor || color} />
      <rect x="0" y="20" width="8" height="13" rx="4" fill={shirtColor || color} />
      <rect x="22" y="20" width="8" height="13" rx="4" fill={shirtColor || color} />
      {/* Sitting legs */}
      <rect x="8" y="33" width="7" height="10" rx="3" fill="#161f3b" />
      <rect x="15" y="33" width="7" height="10" rx="3" fill="#161f3b" />
      <rect x="5" y="41" width="14" height="6" rx="3" fill="#161f3b" />
      <rect x="15" y="41" width="14" height="6" rx="3" fill="#161f3b" />
      <ellipse cx="10" cy="47" rx="6" ry="3" fill="#333" />
      <ellipse cx="22" cy="47" rx="6" ry="3" fill="#333" />
    </g>
  );
}

/* ── Decorative elements ── */
function Cloud({ x, y, scale = 1 }) {
  return (
    <g transform={`translate(${x}, ${y}) scale(${scale})`} opacity="0.7">
      <ellipse cx="30" cy="20" rx="22" ry="14" fill="white" />
      <ellipse cx="50" cy="16" rx="18" ry="12" fill="white" />
      <ellipse cx="68" cy="22" rx="16" ry="10" fill="white" />
      <rect x="8" y="22" width="76" height="12" fill="white" rx="4" />
    </g>
  );
}

function Leaf({ x, y, color = '#7db87d', rotation = 0 }) {
  return (
    <g transform={`translate(${x}, ${y}) rotate(${rotation})`}>
      <ellipse cx="0" cy="0" rx="12" ry="22" fill={color} opacity="0.75" />
      <line x1="0" y1="-20" x2="0" y2="20" stroke={color} strokeWidth="1.5" opacity="0.5" />
    </g>
  );
}

function ScoreCard({ x, y }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect x="0" y="0" width="70" height="52" rx="8" fill="white" stroke="#e2dbd5" strokeWidth="1.5" />
      <rect x="8" y="8" width="36" height="5" rx="2.5" fill="#a0036c" opacity="0.8" />
      <rect x="8" y="18" width="50" height="4" rx="2" fill="#e5ddd7" />
      <rect x="8" y="26" width="44" height="4" rx="2" fill="#e5ddd7" />
      <rect x="8" y="34" width="38" height="4" rx="2" fill="#e5ddd7" />
      <circle cx="58" cy="40" r="8" fill="#a0036c" opacity="0.15" />
      <text x="58" y="44" textAnchor="middle" fill="#a0036c" fontSize="8" fontWeight="700">87</text>
    </g>
  );
}

function MagnifyingGlass({ x, y }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <circle cx="16" cy="16" r="13" fill="none" stroke="#e9b57b" strokeWidth="4" />
      <line x1="25" y1="25" x2="36" y2="36" stroke="#e9b57b" strokeWidth="4" strokeLinecap="round" />
    </g>
  );
}

function Scale({ x, y }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      {/* Pole */}
      <rect x="19" y="0" width="3" height="40" rx="1.5" fill="#161f3b" opacity="0.5" />
      {/* Beam */}
      <rect x="0" y="12" width="40" height="3" rx="1.5" fill="#161f3b" opacity="0.5" />
      {/* Left pan */}
      <line x1="3" y1="15" x2="3" y2="26" stroke="#a0036c" strokeWidth="1.5" />
      <ellipse cx="3" cy="28" rx="10" ry="4" fill="#a0036c" opacity="0.25" />
      {/* Right pan */}
      <line x1="38" y1="15" x2="38" y2="30" stroke="#a0036c" strokeWidth="1.5" />
      <ellipse cx="38" cy="32" rx="10" ry="4" fill="#a0036c" opacity="0.25" />
    </g>
  );
}

function Gear({ x, y, r = 18, color = '#161f3b', opacity = 0.18 }) {
  const teeth = 8;
  const pts = [];
  for (let i = 0; i < teeth * 2; i++) {
    const a = (i * Math.PI) / teeth;
    const rad = i % 2 === 0 ? r : r * 0.72;
    pts.push(`${x + Math.cos(a) * rad},${y + Math.sin(a) * rad}`);
  }
  return (
    <g opacity={opacity}>
      <polygon points={pts.join(' ')} fill={color} />
      <circle cx={x} cy={y} r={r * 0.35} fill="#f5f1ea" />
    </g>
  );
}

export default function FlowIllustrated({ onOpenModal }) {
  return (
    <section className="flow-illustrated" id="flow-illustrated">
      <div className="flow-illustrated-inner">
        <div className="flow-illustrated-header">
          <p className="flow-illustrated-eyebrow">The FLOW Method™</p>
          <h2 className="flow-illustrated-heading">One flow. Full context.<br />Zero handoffs.</h2>
          <p className="flow-illustrated-sub">
            The four categories Jaspen works through with you — Frame, Limits, Opportunities, Weigh. Every step builds on the last.
          </p>
        </div>

        <div className="flow-scene">
          <svg viewBox="0 0 1200 420" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">

            {/* ── Background decorations ── */}
            <g className="float-a"><Cloud x={30} y={10} scale={1.1} /></g>
            <g className="float-b"><Cloud x={980} y={18} scale={0.85} /></g>
            <g className="float-e"><Cloud x={520} y={5} scale={0.7} /></g>

            <g className="float-c"><Leaf x={55} y={310} color="#7db87d" rotation={-30} /></g>
            <g className="float-f"><Leaf x={75} y={285} color="#5a9e5a" rotation={15} /></g>
            <g className="float-d"><Leaf x={1120} y={300} color="#7db87d" rotation={30} /></g>
            <g className="float-b"><Leaf x={1140} y={275} color="#5a9e5a" rotation={-20} /></g>
            <g className="float-e"><Leaf x={580} y={380} color="#7db87d" rotation={10} /></g>

            <g className="float-f"><Gear x={110} y={370} r={22} color="#a0036c" opacity={0.12} /></g>
            <g className="float-c"><Gear x={1080} y={360} r={18} color="#161f3b" opacity={0.14} /></g>
            <g className="float-a"><Gear x={600} y={400} r={14} color="#e9b57b" opacity={0.22} /></g>

            {/* ── Big FLOW letters — equal margins left/right ── */}
            <text x="114" y="320" fontSize="260" fontWeight="900" fill="#a0036c" opacity="0.13" fontFamily="inherit" letterSpacing="-8">F</text>
            <text x="376" y="320" fontSize="260" fontWeight="900" fill="#161f3b" opacity="0.10" fontFamily="inherit" letterSpacing="-8">L</text>
            <text x="616" y="320" fontSize="260" fontWeight="900" fill="#a0036c" opacity="0.10" fontFamily="inherit" letterSpacing="-8">O</text>
            <text x="866" y="320" fontSize="260" fontWeight="900" fill="#161f3b" opacity="0.10" fontFamily="inherit" letterSpacing="-8">W</text>

            {/* ── Ground line ── */}
            <rect x="0" y="340" width="1200" height="4" rx="2" fill="#c9bfb4" opacity="0.4" />

            {/* ── F — Frame: person pointing up at letter, compass/map element ── */}
            <g className="float-b">
              <rect x="82" y="220" width="56" height="44" rx="6" fill="white" stroke="#e2dbd5" strokeWidth="1.5" />
              <line x1="92" y1="232" x2="128" y2="232" stroke="#a0036c" strokeWidth="1.5" opacity="0.6" />
              <line x1="92" y1="240" x2="118" y2="240" stroke="#a0036c" strokeWidth="1" opacity="0.4" />
              <line x1="92" y1="248" x2="124" y2="248" stroke="#a0036c" strokeWidth="1" opacity="0.4" />
              <circle cx="130" cy="230" r="7" fill="#e9b57b" />
              <text x="130" y="234" textAnchor="middle" fill="white" fontSize="8" fontWeight="700">N</text>
            </g>
            <PersonPointing x={130} y={290} color="#a0036c" shirtColor="#c4046f" />
            <PersonSitting x={58} y={295} color="#161f3b" shirtColor="#1e2c4a" />

            {/* ── L — Limits: person looking through magnifier, warning sign ── */}
            <g className="float-a">
              <polygon points="388,195 420,250 356,250" fill="#e9b57b" opacity="0.85" />
              <text x="388" y="242" textAnchor="middle" fill="white" fontSize="22" fontWeight="900">!</text>
            </g>
            <g className="float-d"><MagnifyingGlass x={330} y={268} /></g>
            <Person x={342} y={286} color="#e9b57b" shirtColor="#c8932a" />
            <PersonPointing x={410} y={290} color="#161f3b" shirtColor="#2a3a5e" flip />

            {/* ── O — Opportunities: scorecard, person celebrating ── */}
            <g className="float-e"><ScoreCard x={558} y={215} /></g>
            <g className="float-c" opacity="0.7">
              <line x1="648" y1="255" x2="648" y2="215" stroke="#a0036c" strokeWidth="3" strokeLinecap="round" />
              <polygon points="648,208 641,222 655,222" fill="#a0036c" />
            </g>
            <Person x={558} y={289} color="#a0036c" shirtColor="#c4046f" />
            <PersonPointing x={620} y={292} color="#e9b57b" shirtColor="#c8932a" flip={false} />

            {/* ── W — Weigh: scale element, two people on either side ── */}
            <g className="float-b">
              <Scale x={844} y={210} />
              <rect x="808" y="258" width="34" height="18" rx="9" fill="#a0036c" opacity="0.8" />
              <text x="825" y="271" textAnchor="middle" fill="white" fontSize="9" fontWeight="700">A</text>
              <rect x="876" y="262" width="34" height="18" rx="9" fill="#161f3b" opacity="0.7" />
              <text x="893" y="275" textAnchor="middle" fill="white" fontSize="9" fontWeight="700">B</text>
            </g>
            <Person x={808} y={290} color="#161f3b" shirtColor="#2a3a5e" />
            <PersonPointing x={882} y={290} color="#a0036c" shirtColor="#c4046f" flip />

            {/* ── Dotted connector line between steps ── */}
            <line x1="190" y1="310" x2="320" y2="310" stroke="#a0036c" strokeWidth="1.5" strokeDasharray="6,5" opacity="0.35" />
            <line x1="480" y1="310" x2="560" y2="310" stroke="#a0036c" strokeWidth="1.5" strokeDasharray="6,5" opacity="0.35" />
            <line x1="700" y1="310" x2="820" y2="310" stroke="#a0036c" strokeWidth="1.5" strokeDasharray="6,5" opacity="0.35" />

            {/* Arrow heads on connectors */}
            <polygon points="320,306 310,312 320,318" fill="#a0036c" opacity="0.4" />
            <polygon points="560,306 550,312 560,318" fill="#a0036c" opacity="0.4" />
            <polygon points="820,306 810,312 820,318" fill="#a0036c" opacity="0.4" />
          </svg>
        </div>

        {/* Step labels below the scene */}
        <div className="flow-step-labels">
          {[
            { letter: 'F', name: 'Frame', d1: 'Where are we going?', d2: 'What does success look like?' },
            { letter: 'L', name: 'Limits', d1: "What's in the way?", d2: 'What are we working around?' },
            { letter: 'O', name: 'Opportunities', d1: "What's already working?", d2: "Where's the momentum?" },
            { letter: 'W', name: 'Weigh', d1: 'What are the options?', d2: 'What are the tradeoffs?' },
          ].map(s => (
            <div className="flow-step-label" key={s.letter}>
              <p className="flow-step-name">{s.name}</p>
              <p className="flow-step-desc">{s.d1}<br />{s.d2}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
