import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import RiskRegister from './RiskRegister';

const risk = {
  id: 'risk-1',
  risk: 'Cutover interrupts operations',
  probability: 'Medium',
  residual_risk: 'Low',
  mitigation: 'Stage the cutover.',
};

it('requires an explicit action before residual exposure is accepted', async () => {
  const onAcceptExposure = jest.fn().mockResolvedValue({ id: 'accepted-1' });
  render(<RiskRegister risks={[risk]} onAcceptExposure={onAcceptExposure} />);

  expect(onAcceptExposure).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Accept residual exposure' }));
  expect(screen.getByText(/remains after the stated mitigation/i)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Optional note'), {
    target: { value: 'Operations approved this residual risk.' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Record accepted exposure' }));

  await waitFor(() => expect(onAcceptExposure).toHaveBeenCalledWith(
    risk,
    'Operations approved this residual risk.',
  ));
});

it('renders the recorded actor, timestamp, and note', () => {
  render(
    <RiskRegister
      risks={[risk]}
      optionName="Phased automation"
      onAcceptExposure={jest.fn()}
      acceptedExposures={[{
        id: 'accepted-1',
        accepted_at: '2026-09-08T14:00:00Z',
        accepted_by: { name: 'Lydia Bailey' },
        note: 'Proceed with a rollback checkpoint.',
        exposure: { kind: 'risk', option_name: 'Phased automation', target_key: 'risk-1' },
      }]}
    />,
  );

  expect(screen.getByText('Accepted by Lydia Bailey')).toBeInTheDocument();
  expect(screen.getByText('Proceed with a rollback checkpoint.')).toBeInTheDocument();
});
