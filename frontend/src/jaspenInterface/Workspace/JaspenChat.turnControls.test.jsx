import React from 'react';

jest.mock('react-markdown', () => ({ children }) => <>{children}</>);
jest.mock('remark-gfm', () => () => null);

import { replyTurnControls } from './JaspenChat';

const latestReply = { role: 'ai', text: 'Here is a revised answer.' };
const mutationReply = { role: 'ai', text: 'I updated the plan.', hasMutations: true, canUndo: true };

const writer = {
  activeThreadId: 't-1',
  isLatestAssistant: true,
  isStreamingReply: false,
  busy: false,
  regenerating: false,
  undoingMutation: false,
  canWriteProject: true,
};

it('offers Regenerate on the latest plain reply to a member who can write', () => {
  expect(replyTurnControls(latestReply, writer)).toEqual({
    canRegenerate: true,
    canUndoMutation: false,
  });
});

it('offers Undo changes on the latest reply that changed the project', () => {
  expect(replyTurnControls(mutationReply, writer)).toEqual({
    canRegenerate: false,
    canUndoMutation: true,
  });
});

it('hides Regenerate from a member who can only read the project', () => {
  expect(replyTurnControls(latestReply, { ...writer, canWriteProject: false }).canRegenerate).toBe(false);
});

it('hides Undo changes from a member who can only read the project', () => {
  expect(replyTurnControls(mutationReply, { ...writer, canWriteProject: false }).canUndoMutation).toBe(false);
});

it('keeps the existing rules: never on an earlier reply or while a reply streams', () => {
  expect(replyTurnControls(latestReply, { ...writer, isLatestAssistant: false }).canRegenerate).toBe(false);
  expect(replyTurnControls(mutationReply, { ...writer, isStreamingReply: true }).canUndoMutation).toBe(false);
  expect(replyTurnControls({ ...latestReply, text: 'Applied changes: renamed' }, writer).canRegenerate).toBe(false);
});
