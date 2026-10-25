import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import OnePagerReport from './OnePagerReport';
import { closestReadableShade } from './reportModel';

const snapshot = {
  scorecard: {
    project_name: 'Denver Bike Lane Package',
    jaspen_score: 47,
    decision_kit: 'rfp_bid',
    recommendation: { label: 'No-Bid' },
    executive_summary: 'The case rests mostly on assumptions. Second sentence.',
  },
};

const renderEditor = (onSavePresentation, reportSnapshot = snapshot) => render(
  <OnePagerReport
    artifactType="scorecard"
    snapshot={reportSnapshot}
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

  const shade = closestReadableShade('#E8472C');
  expect(screen.getByText(`Too light to read on white. Saving will use ${shade}.`)).toBeInTheDocument();
  const save = screen.getByRole('button', { name: 'Save' });
  expect(save).toBeEnabled();

  await userEvent.click(save);
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  const { accent } = onSave.mock.calls[0][0].colors;
  expect(accent).toBe(shade);
});

test('a wording-only edit saves when the report already has unreadable colors', async () => {
  const onSave = jest.fn().mockResolvedValue(undefined);
  const savedSnapshot = {
    ...snapshot,
    presentation: {
      colors: { accent: '#E8472C', ink: '#AAAAAA', tint: '#F7F7F7' },
    },
  };
  renderEditor(onSave, savedSnapshot);

  const save = screen.getByRole('button', { name: 'Save' });
  expect(save).toBeEnabled();
  fireEvent.change(screen.getByLabelText('Headline'), { target: { value: 'A clearer headline' } });
  await userEvent.click(save);

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  expect(onSave.mock.calls[0][0]).toEqual(expect.objectContaining({
    colors: {
      accent: closestReadableShade('#E8472C'),
      ink: closestReadableShade('#AAAAAA'),
      tint: '#F7F7F7',
    },
    text: expect.objectContaining({ headline: 'A clearer headline' }),
  }));
});

test('readable colors are sent unchanged', async () => {
  const onSave = jest.fn().mockResolvedValue(undefined);
  const colors = { accent: '#A0036C', ink: '#1B2342', tint: '#EEF5F7' };
  renderEditor(onSave, { ...snapshot, presentation: { colors } });

  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  expect(onSave.mock.calls[0][0].colors).toEqual(colors);
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
