import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faLayerGroup, faScaleBalanced, faPeopleGroup } from '@fortawesome/free-solid-svg-icons';
import { FOCUS_OPTIONS } from './guidedDecisionState';

const ICONS = {
  'layer-group': faLayerGroup,
  'scale-balanced': faScaleBalanced,
  'people-group': faPeopleGroup,
};

export default function ChooseFocusStep({ draft, update }) {
  const selectFocus = (id) => update({ focus: id, focusCustom: '' });
  const onCustomChange = (e) => update({ focusCustom: e.target.value, focus: null });

  return (
    <div className="gd-step">
      <h2 className="gd-step-title">What are you trying to accomplish?</h2>

      <div className="gd-card-grid" role="radiogroup" aria-label="Choose a focus">
        {FOCUS_OPTIONS.map((opt) => {
          const active = draft.focus === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={active}
              className={`gd-card${active ? ' gd-card--active' : ''}`}
              onClick={() => selectFocus(opt.id)}
            >
              <span className="gd-card-icon">
                <FontAwesomeIcon icon={ICONS[opt.icon]} />
              </span>
              <span className="gd-card-title">{opt.title}</span>
              <ul className="gd-card-examples">
                {opt.examples.map((ex) => (
                  <li key={ex}>{ex}</li>
                ))}
              </ul>
            </button>
          );
        })}
      </div>

      <div className="gd-or-divider">
        <span>Or describe your situation</span>
      </div>

      <textarea
        className="gd-textarea"
        rows={2}
        placeholder="Describe your situation..."
        value={draft.focusCustom}
        onChange={onCustomChange}
        disabled={Boolean(draft.focus)}
      />
    </div>
  );
}
