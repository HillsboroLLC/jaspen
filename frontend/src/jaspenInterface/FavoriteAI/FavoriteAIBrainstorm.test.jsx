import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FavoriteAIBrainstorm from './FavoriteAIBrainstorm';
import { BRAINSTORM_PROMPT, buildCopiedPrompt } from './favoriteAI';

const summary = {
  title: 'Choose a launch market',
  options: ['Chicago', 'Austin'],
  openQuestions: ['Demand evidence: Which market has stronger qualified demand?'],
};

function setClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  });
}

describe('FavoriteAIBrainstorm', () => {
  let openSpy;

  beforeEach(() => {
    localStorage.clear();
    openSpy = jest.spyOn(window, 'open').mockImplementation(() => null);
  });

  afterEach(() => {
    openSpy.mockRestore();
  });

  test('renders provider icons with individual labels and the shared tooltip', () => {
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);

    for (const provider of ['ChatGPT', 'Claude', 'Gemini']) {
      const button = screen.getByRole('button', { name: `Brainstorm with ${provider}` });
      expect(button).toHaveAttribute('title', 'Brainstorm with your favorite AI tool');
      expect(button).toContainHTML('<svg');
      expect(button).not.toContainHTML('linearGradient');
    }
    expect(screen.getByRole('button', { name: 'Brainstorm with your favorite AI tool' }))
      .toHaveClass('favorite-ai-collapsed-icon');
  });

  test('keeps project context off by default and copies exactly the visible preview when enabled', async () => {
    const user = userEvent.setup();
    const writeText = jest.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with ChatGPT' }));

    const checkbox = screen.getByRole('checkbox', { name: "Include this project's summary" });
    const preview = screen.getByLabelText('Prompt to copy');
    expect(checkbox).not.toBeChecked();
    expect(preview).toHaveValue(BRAINSTORM_PROMPT);
    expect(preview).not.toHaveValue(expect.stringContaining(summary.title));

    await user.click(checkbox);
    const expected = buildCopiedPrompt(summary, true);
    expect(preview).toHaveValue(expected);
    await user.click(screen.getByRole('button', { name: 'Copy prompt and open ChatGPT' }));

    expect(writeText).toHaveBeenCalledWith(expected);
    expect(openSpy).toHaveBeenCalledWith('https://chatgpt.com/', '_blank', 'noopener,noreferrer');
    expect(openSpy.mock.calls[0][0]).not.toContain('?');
  });

  test.each([
    ['Claude', 'https://claude.ai/new'],
    ['Gemini', 'https://gemini.google.com/app'],
  ])('opens %s at its fixed URL without putting prompt text in the URL', async (name, url) => {
    const user = userEvent.setup();
    const writeText = jest.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: `Brainstorm with ${name}` }));
    await user.click(screen.getByRole('button', { name: `Copy prompt and open ${name}` }));

    expect(writeText).toHaveBeenCalledWith(BRAINSTORM_PROMPT);
    expect(openSpy).toHaveBeenCalledWith(url, '_blank', 'noopener,noreferrer');
  });

  test('selects the prompt for manual copying when clipboard access fails', async () => {
    const user = userEvent.setup();
    setClipboard(jest.fn().mockRejectedValue(new Error('denied')));
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with ChatGPT' }));
    await user.click(screen.getByRole('button', { name: 'Copy prompt and open ChatGPT' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('selected so you can copy it manually');
    const preview = screen.getByLabelText('Prompt to copy');
    await waitFor(() => expect(preview).toHaveFocus());
    expect(preview.selectionStart).toBe(0);
    expect(preview.selectionEnd).toBe(BRAINSTORM_PROMPT.length);
    expect(openSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Open ChatGPT' }));
    expect(openSpy).toHaveBeenCalledWith('https://chatgpt.com/', '_blank', 'noopener,noreferrer');
  });

  test('labels returned thinking and stages it without sending', async () => {
    const onAddToComposer = jest.fn();
    const user = userEvent.setup();
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={onAddToComposer} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with Claude' }));
    await user.click(screen.getByRole('button', { name: 'Bring your thinking back' }));
    await user.type(screen.getByLabelText('Your brainstorm'), 'Austin is the stronger option.');
    await user.click(screen.getByRole('button', { name: 'Add to Jaspen' }));

    expect(onAddToComposer).toHaveBeenCalledTimes(1);
    expect(onAddToComposer).toHaveBeenCalledWith(
      'Ideas from my Claude brainstorm:\n\nAustin is the stronger option.'
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('offers one dismissible, non-modal return nudge after a provider trip', async () => {
    const user = userEvent.setup();
    setClipboard(jest.fn().mockResolvedValue(undefined));
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with Gemini' }));
    await user.click(screen.getByRole('button', { name: 'Copy prompt and open Gemini' }));

    fireEvent.blur(window);
    fireEvent.focus(window);
    const nudge = await screen.findByRole('status');
    expect(nudge).toHaveTextContent('Bring your Gemini thinking back to Jaspen');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Dismiss brainstorm return reminder' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    fireEvent.blur(window);
    fireEvent.focus(window);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  test('remembers the last provider with guarded local storage', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with Claude' }));
    expect(localStorage.getItem('jaspen.brainstormProvider')).toBe('claude');
    unmount();

    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    expect(screen.getByRole('button', { name: 'Brainstorm with your favorite AI tool' }))
      .toHaveStyle({ color: '#D97757' });
  });
});
