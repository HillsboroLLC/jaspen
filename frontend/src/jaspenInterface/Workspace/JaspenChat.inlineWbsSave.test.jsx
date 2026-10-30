import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

jest.mock('react-markdown', () => ({ children }) => <>{children}</>);
jest.mock('remark-gfm', () => () => null);

import {
  classifyInlineWbsSaveFailure,
  InlineWbsSaveStatus,
} from './JaspenChat';
import { REVISION_CONFLICT_MESSAGE } from './JaspenClient';

it('classifies ordinary inline-save failures as retryable', () => {
  expect(classifyInlineWbsSaveFailure(
    { status: 500 },
    "Couldn't save that change — try again.",
  )).toEqual({
    message: "Couldn't save that change — try again.",
    retryable: true,
    state: 'error',
  });
});

it('classifies conflicts with D4 and no retry path', () => {
  expect(classifyInlineWbsSaveFailure(
    { status: 409 },
    "Couldn't save that change — try again.",
  )).toEqual({
    message: REVISION_CONFLICT_MESSAGE,
    retryable: false,
    state: 'conflict',
  });
});

it('shows Retry and Undo only for an ordinary inline-save failure', () => {
  const onRetry = jest.fn();
  const onUndo = jest.fn();
  render(<InlineWbsSaveStatus state="error" onRetry={onRetry} onUndo={onUndo} />);

  expect(screen.getByText('Save failed')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  fireEvent.click(screen.getByRole('button', { name: 'Undo change' }));
  expect(onRetry).toHaveBeenCalledTimes(1);
  expect(onUndo).toHaveBeenCalledTimes(1);
});

it('shows D4 with no Retry or Undo for an inline-save conflict', () => {
  render(<InlineWbsSaveStatus state="conflict" onRetry={jest.fn()} onUndo={jest.fn()} />);

  expect(screen.getByText(REVISION_CONFLICT_MESSAGE)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Undo change' })).not.toBeInTheDocument();
  expect(screen.queryByText('Save failed')).not.toBeInTheDocument();
});
