import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FavoriteAIBrainstorm from './FavoriteAIBrainstorm';
import {
  appendComposerDraft,
  BRAINSTORM_PROMPT,
  buildCopiedPrompt,
  buildFavoriteAIProjectSummary,
} from './favoriteAI';

const summary = {
  title: 'Choose a launch market',
  options: ['Chicago', 'Austin'],
  informationNeeded: ['Demand evidence: Which market has stronger qualified demand?'],
  decisionQuestions: ['Chicago: Confirm regulatory approval'],
};

function setClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
}

describe('FavoriteAIBrainstorm', () => {
  let openSpy;

  beforeEach(() => {
    localStorage.clear();
    openSpy = jest.spyOn(window, 'open').mockImplementation(() => ({ opener: window }));
  });
  afterEach(() => openSpy.mockRestore());

  test('renders distinct muted and brand logo layers with accessible provider launchers', () => {
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    for (const provider of ['ChatGPT', 'Claude', 'Gemini', 'Copilot']) {
      const button = screen.getByRole('button', { name: `Brainstorm with ${provider}` });
      expect(button).not.toHaveAttribute('title');
      expect(button).toHaveAttribute('data-tooltip', 'Brainstorm with your favorite AI tool');
      expect(button.querySelector('.favorite-ai-logo-mono')).toHaveAttribute('fill', 'currentColor');
      expect(button.querySelector('.favorite-ai-logo-brand')).toBeInTheDocument();
      expect(button).not.toHaveAttribute('style');
    }
    expect(screen.getByRole('button', { name: 'Brainstorm with Gemini' })).toContainHTML('linearGradient');
    expect(screen.getByRole('button', { name: 'Brainstorm with Copilot' })).toContainHTML('linearGradient');
    expect(screen.getByRole('button', { name: 'Brainstorm with your favorite AI tool' }))
      .toHaveClass('favorite-ai-collapsed-icon');
  });

  test('shows the integration note and an editable comprehensive prompt', async () => {
    const user = userEvent.setup();
    const scheduledFrames = [];
    const frameSpy = jest.spyOn(window, 'requestAnimationFrame')
      .mockImplementation((callback) => {
        scheduledFrames.push(callback);
        return scheduledFrames.length;
      });
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with ChatGPT' }));
    expect(screen.getByText('Exploring a more connected experience')).toBeInTheDocument();
    expect(screen.getByText(/We're exploring deeper provider integrations/)).toBeInTheDocument();
    const prompt = screen.getByLabelText('Prompt to copy');
    expect(prompt).toHaveValue(BRAINSTORM_PROMPT);
    expect(prompt).not.toHaveAttribute('readonly');
    expect(BRAINSTORM_PROMPT).toMatch(/objectives, criteria, priorities, constraints, assumptions/);
    expect(BRAINSTORM_PROMPT).toMatch(/verified from a named source, estimates/);
    await user.clear(prompt);
    act(() => scheduledFrames.splice(0).forEach((callback) => callback()));
    expect(prompt).toHaveFocus();
    await user.type(prompt, 'My tailored prompt');
    expect(prompt).toHaveValue('My tailored prompt');
    frameSpy.mockRestore();
  });

  test('keeps project context off by default and copies exactly the edited visible prompt', async () => {
    const user = userEvent.setup();
    const writeText = jest.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with ChatGPT' }));
    const checkbox = screen.getByRole('checkbox', { name: "Include this project's summary" });
    const prompt = screen.getByLabelText('Prompt to copy');
    expect(checkbox).not.toBeChecked();
    expect(prompt).not.toHaveValue(expect.stringContaining(summary.title));
    await user.click(checkbox);
    expect(prompt).toHaveValue(buildCopiedPrompt(summary, true));
    await user.type(prompt, '\nMy additional context.');
    const expected = `${buildCopiedPrompt(summary, true)}\nMy additional context.`;
    await user.click(screen.getByRole('button', { name: 'Copy prompt and open ChatGPT' }));
    expect(writeText).toHaveBeenCalledWith(expected);
    expect(openSpy).toHaveBeenCalledWith('https://chatgpt.com/', '_blank');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('uses the project header title and honestly labels each included list', () => {
    const projectSummary = buildFavoriteAIProjectSummary({
      projectHeaderTitle: "SMOKE TEST 5: We're a construction firm",
      scorecards: [
        {
          project_name: 'Denver Water pump station',
          gates: [{ label: 'Confirm bonding capacity', status: 'unknown' }],
        },
        { project_name: 'Adams County road resurfacing' },
        { project_name: 'CDOT bridge rehab' },
      ],
      collectedSignals: [{
        label: 'Jira data',
        hint: 'Connect Jira to confirm delivery dependencies',
        complete: false,
      }],
    });
    const projectText = buildCopiedPrompt(projectSummary, true);

    expect(projectText).toContain("Title: SMOKE TEST 5: We're a construction firm");
    expect(projectText).not.toContain('Title: Denver Water pump station');
    expect(projectText).toContain('Information Jaspen still needs:\n- Jira data: Connect Jira to confirm delivery dependencies');
    expect(projectText).toContain('Decision questions:\n- Denver Water pump station: Confirm bonding capacity');
    expect(projectText).not.toContain('Open questions:');
  });

  test('leaves empty project summary sections out', () => {
    const projectText = buildCopiedPrompt({
      title: '',
      options: ['Denver Water pump station'],
      informationNeeded: [],
      decisionQuestions: [],
    }, true);

    expect(projectText).not.toContain('Title:');
    expect(projectText).toContain('Options:\n- Denver Water pump station');
    expect(projectText).not.toContain('Information Jaspen still needs:');
    expect(projectText).not.toContain('Decision questions:');
  });

  test('the summary promise names exactly the sections that can be added', async () => {
    const user = userEvent.setup();
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with ChatGPT' }));
    expect(screen.getByText(
      'Off by default. Only the project title, options, information Jaspen still needs, and decision questions shown in Jaspen are added when you turn this on.'
    )).toBeInTheDocument();
  });

  test.each([
    ['Claude', 'https://claude.ai/new'],
    ['Gemini', 'https://gemini.google.com/app'],
    ['Copilot', 'https://copilot.microsoft.com/'],
  ])('opens %s at its fixed URL without prompt text in the URL', async (name, url) => {
    const user = userEvent.setup();
    setClipboard(jest.fn().mockResolvedValue(undefined));
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: `Brainstorm with ${name}` }));
    await user.click(screen.getByRole('button', { name: `Copy prompt and open ${name}` }));
    expect(openSpy).toHaveBeenCalledWith(url, '_blank');
    expect(openSpy.mock.calls[0][0]).not.toContain('?');
  });

  test('keeps the dialog open with a recovery action when a popup is blocked', async () => {
    const user = userEvent.setup();
    setClipboard(jest.fn().mockResolvedValue(undefined));
    openSpy.mockReturnValue(null);
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with Gemini' }));
    await user.click(screen.getByRole('button', { name: 'Copy prompt and open Gemini' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('browser blocked the new tab');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    openSpy.mockReturnValue({ opener: window });
    await user.click(screen.getByRole('button', { name: 'Open Gemini' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('selects the prompt for manual copying when clipboard access fails', async () => {
    const user = userEvent.setup();
    setClipboard(jest.fn().mockRejectedValue(new Error('denied')));
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with ChatGPT' }));
    await user.click(screen.getByRole('button', { name: 'Copy prompt and open ChatGPT' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('selected so you can copy it manually');
    const prompt = screen.getByLabelText('Prompt to copy');
    await waitFor(() => expect(prompt).toHaveFocus());
    expect(prompt.selectionStart).toBe(0);
    expect(prompt.selectionEnd).toBe(BRAINSTORM_PROMPT.length);
    expect(openSpy).toHaveBeenCalledWith('https://chatgpt.com/', '_blank');
  });

  test('returns directly to the existing composer without an intermediate paste field or submission', async () => {
    const onAddToComposer = jest.fn();
    const user = userEvent.setup();
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={onAddToComposer} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with Claude' }));
    await user.click(screen.getByRole('button', { name: 'Bring your thinking back' }));
    expect(screen.queryByLabelText('Your brainstorm')).not.toBeInTheDocument();
    expect(screen.getByText(/never submits it automatically/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Continue in Jaspen' }));
    expect(onAddToComposer).toHaveBeenCalledTimes(1);
    expect(onAddToComposer).toHaveBeenCalledWith('Ideas from my Claude brainstorm:\n\n');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('preserves composer text and a blank paste area after the provider label', () => {
    expect(appendComposerDraft('My existing draft', 'Ideas from my Claude brainstorm:\n\n'))
      .toBe('My existing draft\n\nIdeas from my Claude brainstorm:\n\n');
    expect(appendComposerDraft('', 'Ideas from my Claude brainstorm:\n\n'))
      .toBe('Ideas from my Claude brainstorm:\n\n');
  });

  test('offers one return nudge that continues directly in the composer', async () => {
    const onAddToComposer = jest.fn();
    const user = userEvent.setup();
    setClipboard(jest.fn().mockResolvedValue(undefined));
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={onAddToComposer} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with Gemini' }));
    await user.click(screen.getByRole('button', { name: 'Copy prompt and open Gemini' }));
    fireEvent.blur(window);
    fireEvent.focus(window);
    const nudge = await screen.findByRole('status');
    expect(nudge).toHaveTextContent('Continue in Jaspen with your Gemini summary');
    await user.click(screen.getByRole('button', { name: 'Continue in Jaspen with your Gemini summary' }));
    expect(onAddToComposer).toHaveBeenCalledWith('Ideas from my Gemini brainstorm:\n\n');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  test('focuses the dialog and restores focus to its launcher on Escape', async () => {
    const user = userEvent.setup();
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    const launcher = screen.getByRole('button', { name: 'Brainstorm with Copilot' });
    await user.click(launcher);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Close AI brainstorm dialog' })).toHaveFocus());
    await user.keyboard('{Escape}');
    await waitFor(() => expect(launcher).toHaveFocus());
  });

  test('remembers the last provider without inline brand-color styles', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Brainstorm with Claude' }));
    expect(localStorage.getItem('jaspen.brainstormProvider')).toBe('claude');
    unmount();
    render(<FavoriteAIBrainstorm projectSummary={summary} onAddToComposer={jest.fn()} />);
    const collapsed = screen.getByRole('button', { name: 'Brainstorm with your favorite AI tool' });
    expect(collapsed).toHaveClass('favorite-ai-provider-icon--claude');
    expect(collapsed).not.toHaveAttribute('style');
  });
});
