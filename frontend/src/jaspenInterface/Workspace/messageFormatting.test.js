import React from 'react';
import { render, screen } from '@testing-library/react';
import fs from 'fs';
import path from 'path';
import { userMessageWhitespaceStyle } from './messageFormatting';

const renderUserBubble = (text) => {
  render(
    <div data-testid="user-message" style={{ maxWidth: '90%', ...userMessageWhitespaceStyle }}>
      {text}
    </div>
  );
  return screen.getByTestId('user-message');
};

describe('user message whitespace formatting', () => {
  test('preserves multiple paragraphs and blank lines in rendered user text', () => {
    const text = 'First paragraph with context.\n\nSecond paragraph after a blank line.';
    const bubble = renderUserBubble(text);

    expect(bubble.textContent).toBe(text);
    expect(bubble).toHaveStyle(userMessageWhitespaceStyle);
  });

  test('preserves hyphenated bullets and numbered lists exactly as entered', () => {
    const text = [
      'Risks:',
      '- Supplier delay',
      '- Missed launch window',
      '',
      'Next steps:',
      '1. Confirm owner',
      '2. Set weekly review',
    ].join('\n');

    expect(renderUserBubble(text).textContent).toBe(text);
  });

  test('keeps long user text mobile-safe with emergency wrapping', () => {
    const bubble = renderUserBubble(`Long line: ${'A'.repeat(240)}`);
    expect(bubble).toHaveStyle(userMessageWhitespaceStyle);
  });

  test('main workspace user bubbles include the same whitespace rules', () => {
    const css = fs.readFileSync(path.resolve(__dirname, 'JaspenChat.css'), 'utf8');

    expect(css).toMatch(/\.jas-message\.user \.jas-message-bubble\s*\{[^}]*white-space:\s*pre-wrap;/s);
    expect(css).toMatch(/\.jas-message\.user \.jas-message-bubble\s*\{[^}]*overflow-wrap:\s*anywhere;/s);
    expect(css).toMatch(/\.jas-message\.user \.jas-message-bubble\s*\{[^}]*word-break:\s*break-word;/s);
    expect(css).toMatch(/\.jas-chat-tab \.agent-chat-message\.user \.message-content\s*\{[^}]*white-space:\s*pre-wrap;/s);
  });
});
