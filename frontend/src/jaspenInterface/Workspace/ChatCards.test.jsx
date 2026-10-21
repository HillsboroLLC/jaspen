import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ConfirmCard, DataTableCard, ReceiptsCard, RubricCard, StatusCard, isLatestCard } from './ChatCards';

const rubric = {
  status: 'proposed',
  kit_label: 'RFP response',
  criteria: [
    { label: 'Win probability', weight_pct: 60, gate: false },
    { label: 'Delivery capacity', weight_pct: 40, gate: false },
    { label: 'Surety / bond confirmation', weight_pct: null, gate: true },
  ],
  actions: [
    { label: 'Approve rubric', value: 'Approve this rubric' },
    { label: 'Change rubric', value: 'Change the rubric' },
  ],
};

it('shows the exact rubric, its status, and sends the chosen action as the user', () => {
  const onSendText = jest.fn();
  render(<RubricCard data={rubric} onSendText={onSendText} showActions />);
  expect(screen.getByText('RFP response rubric')).toBeInTheDocument();
  expect(screen.getByText('Proposed')).toBeInTheDocument();
  expect(screen.getByText('Win probability')).toBeInTheDocument();
  expect(screen.getByText('60%')).toBeInTheDocument();
  expect(screen.getByText('Surety / bond confirmation')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Approve rubric' }));
  expect(onSendText).toHaveBeenCalledWith('Approve this rubric');
});

it('hides buttons on cards that are not the newest', () => {
  render(<RubricCard data={rubric} onSendText={jest.fn()} showActions={false} />);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('a failure card offers Retry that resends the original message', () => {
  const onSendText = jest.fn();
  render(<StatusCard data={{ tone: 'error', message: "Scoring didn't finish.", retry_message: 'Score both now' }} onSendText={onSendText} showRetry />);
  expect(screen.getByRole('alert')).toHaveTextContent("Scoring didn't finish.");
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(onSendText).toHaveBeenCalledWith('Score both now');
});

it('the kit change card shows the change and its choices', () => {
  const onSendText = jest.fn();
  render(<ConfirmCard
    data={{ kind: 'decision_kit_change', from_label: 'RFP response', to_label: 'Vendor selection', actions: [{ label: 'Change kit and re-score', value: 'Yes, change the Decision Kit and re-score.' }] }}
    onSendText={onSendText}
    showActions
  />);
  expect(screen.getByText('Vendor selection')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Change kit and re-score' }));
  expect(onSendText).toHaveBeenCalledWith('Yes, change the Decision Kit and re-score.');
});

it('only the newest card of a type is latest', () => {
  const first = { artifact: { type: 'rubric', data: {} } };
  const second = { artifact: { type: 'rubric', data: {} } };
  const messages = [first, { text: 'hi' }, second];
  expect(isLatestCard(first, messages)).toBe(false);
  expect(isLatestCard(second, messages)).toBe(true);
});

it('a "which option?" card offers the options instead of Retry', () => {
  const onSendText = jest.fn();
  render(<StatusCard
    data={{ tone: 'info', message: 'Which option did you mean?', actions: [{ label: 'North Agency', value: 'North Agency' }, { label: 'South Agency', value: 'South Agency' }] }}
    onSendText={onSendText}
    showRetry
  />);
  expect(screen.getByRole('status')).toHaveTextContent('Which option did you mean?');
  expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'South Agency' }));
  expect(onSendText).toHaveBeenCalledWith('South Agency');
});

it('lists what changed as receipts', () => {
  render(<ReceiptsCard data={{ items: ['Renamed this initiative to \'Q4 bids\'.', 'Saved 2 structured fact(s) for Agency.'] }} />);
  expect(screen.getByText("Renamed this initiative to 'Q4 bids'.")).toBeInTheDocument();
  expect(screen.getByText('Saved 2 structured fact(s) for Agency.')).toBeInTheDocument();
});

it('the override card names the option and what it overrides', () => {
  const onSendText = jest.fn();
  render(<ConfirmCard
    data={{ kind: 'decision_override', option_name: 'Aurora bid', override_of: 'decline', actions: [{ label: 'Record override', value: 'Yes, record it.' }, { label: 'Cancel', value: "No, don't record it." }] }}
    onSendText={onSendText}
    showActions
  />);
  expect(screen.getByText('Aurora bid')).toBeInTheDocument();
  expect(screen.getByText("Overrides Jaspen's No-Bid.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Record override' }));
  expect(onSendText).toHaveBeenCalledWith('Yes, record it.');
});

it('shows query results exactly, with formatted numbers and a row count', () => {
  render(<DataTableCard data={{
    source: 'snowflake', table: 'sales.regions', columns: ['REGION', 'REVENUE'],
    rows: [{ REGION: 'West', REVENUE: 1250000 }, { REGION: 'East', REVENUE: null }],
    returned_rows: 48,
  }} />);
  expect(screen.getByText('Snowflake data')).toBeInTheDocument();
  expect(screen.getByText('sales.regions')).toBeInTheDocument();
  expect(screen.getByText('1,250,000')).toBeInTheDocument();
  expect(screen.getByText('—')).toBeInTheDocument();
  expect(screen.getByText('Showing 2 of 48 rows')).toBeInTheDocument();
});
