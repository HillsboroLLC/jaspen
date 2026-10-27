import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import ConnectorContextChip from './ConnectorContextChip';

test('a non-green context chip is disabled and never toggles', () => {
  const onToggle = jest.fn();
  render(
    <ConnectorContextChip
      source={{ id: 'jira_sync', label: 'Jira' }}
      connector={{ id: 'jira_sync', label: 'Jira', connected: true, freshness: 'unconfirmed', jira: { data_enabled: true } }}
      onToggle={onToggle}
    />
  );

  const chip = screen.getByRole('button', { name: 'Jira' });
  expect(chip).toBeDisabled();
  expect(chip).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(chip);
  expect(onToggle).not.toHaveBeenCalled();
});

test('a confirmed context chip toggles', () => {
  const onToggle = jest.fn();
  render(
    <ConnectorContextChip
      source={{ id: 'jira_sync', label: 'Jira' }}
      connector={{ id: 'jira_sync', label: 'Jira', connected: true, freshness: 'confirmed', jira: { data_enabled: true } }}
      onToggle={onToggle}
    />
  );

  fireEvent.click(screen.getByRole('button', { name: 'Jira' }));
  expect(onToggle).toHaveBeenCalledWith('jira_sync', 'Jira');
});
