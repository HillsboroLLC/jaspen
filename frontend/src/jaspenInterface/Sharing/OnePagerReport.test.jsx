import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import OnePagerReport from './OnePagerReport';

const snapshot = {
  scorecard: {
    project_name: 'Denver Bike Lane Package',
    jaspen_score: 47,
    decision_kit: 'rfp_bid',
    recommendation: { label: 'No-Bid' },
    executive_summary: 'The case rests mostly on assumptions. Second sentence.',
  },
};

const renderEditor = (onSavePresentation) => render(
  <OnePagerReport
    artifactType="scorecard"
    snapshot={snapshot}
    title="Denver Bike Lane Package"
    canEdit
    editing
    onSavePresentation={onSavePresentation}
  />,
);

test('a color too light for white text is flagged before saving, with the nearest readable shade', async () => {
  const onSave = jest.fn().mockResolvedValue(undefined);
  renderEditor(onSave);

  fireEvent.change(screen.getByLabelText('Accent'), { target: { value: '#e8472c' } });

  expect(screen.getByText('Too light to read on white.')).toBeInTheDocument();
  const save = screen.getByRole('button', { name: 'Save' });
  expect(save).toBeDisabled();

  await userEvent.click(screen.getByRole('button', { name: /^Use #/ }));
  expect(screen.queryByText('Too light to read on white.')).not.toBeInTheDocument();
  expect(save).toBeEnabled();

  await userEvent.click(save);
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  const { accent } = onSave.mock.calls[0][0].colors;
  expect(accent).toMatch(/^#[0-9A-F]{6}$/);
  expect(accent).not.toBe('#E8472C');
});

test('a refused save is explained inside the editor in plain words', async () => {
  const onSave = jest.fn().mockRejectedValue(
    new Error('That color is too light to read on white. Choose a darker shade.'),
  );
  renderEditor(onSave);

  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  expect(await screen.findByText('That color is too light to read on white. Choose a darker shade.')).toBeInTheDocument();
  expect(screen.queryByText(/api\/v1/)).not.toBeInTheDocument();
});
