import React from 'react';
import { render, screen } from '@testing-library/react';

import SharedArtifactView from './SharedArtifactView';
import { Jaspen } from '../Workspace/JaspenClient';

jest.mock('../Workspace/JaspenClient', () => ({ Jaspen: {} }));

const card = (id, name, score) => ({
  id,
  analysis_id: id,
  project_name: name,
  jaspen_score: score,
  executive_summary: `${name} is worth doing.`,
  top_risks: [{ risk: 'Slow payback' }],
  dimensions: {
    fit: { score: 80, label: 'Founder fit', rationale: 'Strong fit' },
    speed: { score: 60, label: 'Time to signal', rationale: 'Slow' },
  },
});

describe('SharedArtifactView (real views, read-only)', () => {
  test('scorecard renders without drag, resize, edit, or export controls', () => {
    const { container } = render(
      <SharedArtifactView artifactType="scorecard" snapshot={{ scorecard: card('c1', 'Paid search', 72) }} />,
    );
    expect(container.querySelector('.score-dashboard-container.is-read-only')).not.toBeNull();
    expect(container.querySelector('[draggable="true"]')).toBeNull();
    expect(container.querySelector('.card-resize-handle, .card-resize-handle-x, .card-drag-handle')).toBeNull();
    expect(screen.queryByRole('button', { name: /Export|Print|Undo|Redo/ })).toBeNull();
  });

  test('trade-off renders every option and the summary, with no row actions or decision panel', () => {
    render(
      <SharedArtifactView
        artifactType="tradeoff"
        snapshot={{
          scorecards: [card('c1', 'Paid search', 72), card('c2', 'Podcasts', 64)],
          portfolio_summary: { structure: '1 Leading Candidate', recommended_sequence: 'Commit to Paid search.' },
        }}
      />,
    );
    expect(screen.getAllByText('Paid search').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Podcasts').length).toBeGreaterThan(0);
    expect(screen.getByText('Commit to Paid search.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Build an execution plan|Open this idea|Park/ })).toBeNull();
    expect(Object.keys(Jaspen)).toHaveLength(0); // nothing reached for the API
  });
});
