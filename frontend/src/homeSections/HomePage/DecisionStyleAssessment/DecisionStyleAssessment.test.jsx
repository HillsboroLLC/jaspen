import React from 'react';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DecisionStyleAssessment from './DecisionStyleAssessment';
import { QUESTIONS, LEAD_SOURCE } from './assessmentData';

// Answer the currently-visible question by clicking one of its options, then
// wait deterministically for the flow to move on (auto-advance is briefly
// delayed by design, so we wait for the next question — or the result — to
// appear rather than racing the transition).
async function answerCurrent(user, currentNum, optionIndex = 0) {
  const group = await screen.findByRole('radiogroup');
  const options = within(group).getAllByRole('radio');
  await user.click(options[optionIndex]);
  if (currentNum < QUESTIONS.length) {
    await screen.findByText(new RegExp(`question ${currentNum + 1} of 7`, 'i'));
  } else {
    await screen.findByText(/reflection complete/i);
  }
}

async function walkThroughAllQuestions(user) {
  await user.click(screen.getByRole('button', { name: /start the reflection/i }));
  for (let i = 0; i < QUESTIONS.length; i += 1) {
    await answerCurrent(user, i + 1);
  }
}

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe('DecisionStyleAssessment', () => {
  it('renders the intro with the non-judgmental framing and no score claim', () => {
    render(<DecisionStyleAssessment />);
    expect(
      screen.getByRole('heading', { name: /how do you make decisions/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/no score, no grade/i)).toBeInTheDocument();
  });

  it('advances through the questions and shows progress', async () => {
    const user = userEvent.setup();
    render(<DecisionStyleAssessment />);
    await user.click(screen.getByRole('button', { name: /start the reflection/i }));

    expect(screen.getByText(/question 1 of 7/i)).toBeInTheDocument();
    await answerCurrent(user, 1);
    expect(await screen.findByText(/question 2 of 7/i)).toBeInTheDocument();
  });

  it('lets the user go back and change an earlier answer', async () => {
    const user = userEvent.setup();
    render(<DecisionStyleAssessment />);
    await user.click(screen.getByRole('button', { name: /start the reflection/i }));
    await answerCurrent(user, 1); // now on Q2
    await screen.findByText(/question 2 of 7/i);

    await user.click(screen.getByRole('button', { name: /^back$/i }));
    expect(await screen.findByText(/question 1 of 7/i)).toBeInTheDocument();
    // The previously chosen option is still selected (radio checked).
    const group = await screen.findByRole('radiogroup');
    const firstRadio = within(group).getAllByRole('radio')[0];
    expect(firstRadio).toBeChecked();
  });

  it('shows a partial result with a provisional style before asking for email', async () => {
    const user = userEvent.setup();
    render(<DecisionStyleAssessment />);
    await walkThroughAllQuestions(user);

    expect(await screen.findByText(/reflection complete/i)).toBeInTheDocument();
    expect(screen.getByText(/your decision style appears to be/i)).toBeInTheDocument();
    expect(
      screen.getByText(/your full decision profile will include/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /email my full decision profile/i })
    ).toBeInTheDocument();
  });

  it('rejects an invalid email without submitting', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest.spyOn(global, 'fetch');
    render(<DecisionStyleAssessment />);
    await walkThroughAllQuestions(user);

    const input = await screen.findByLabelText(/where should we send/i);
    await user.type(input, 'not-an-email');
    await user.click(screen.getByRole('button', { name: /email my full decision profile/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/valid email/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('submits a valid email with assessment answers and confirms only after acceptance', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({ ok: true }) });

    render(<DecisionStyleAssessment />);
    await walkThroughAllQuestions(user);

    const input = await screen.findByLabelText(/where should we send/i);
    await user.type(input, 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email my full decision profile/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const [url, options] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/public\/leads$/);
    const body = JSON.parse(options.body);
    expect(body).toMatchObject({
      email: 'lydia@jaspen.ai',
      source: LEAD_SOURCE,
      decision_style: expect.any(String),
    });
    expect(body.assessment_answers).toBeDefined();
    expect(Object.keys(body.assessment_answers)).toHaveLength(QUESTIONS.length);

    expect(await screen.findByText(/your decision profile is on its way/i)).toBeInTheDocument();
    expect(screen.getByText(/check your inbox in the next few minutes/i)).toBeInTheDocument();
  });

  it('uses the results-specific loading text while submitting', async () => {
    const user = userEvent.setup();
    let resolveFetch;
    jest.spyOn(global, 'fetch').mockImplementation(
      () => new Promise((resolve) => {
        resolveFetch = resolve;
      })
    );

    render(<DecisionStyleAssessment />);
    await walkThroughAllQuestions(user);

    const input = await screen.findByLabelText(/where should we send/i);
    await user.type(input, 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email my full decision profile/i }));

    expect(await screen.findByRole('button', { name: /sending your results/i })).toBeDisabled();

    resolveFetch({ ok: true, status: 201, json: async () => ({ ok: true }) });
    expect(await screen.findByText(/your decision profile is on its way/i)).toBeInTheDocument();
  });

  it('preserves the result and email when the lead request fails', async () => {
    const user = userEvent.setup();
    jest.spyOn(global, 'fetch').mockRejectedValue(new Error('network down'));

    render(<DecisionStyleAssessment />);
    await walkThroughAllQuestions(user);

    const input = await screen.findByLabelText(/where should we send/i);
    await user.type(input, 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email my full decision profile/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not email your decision profile/i);
    expect(screen.getByLabelText(/where should we send/i)).toHaveValue('lydia@jaspen.ai');
    expect(screen.getByText(/your decision style appears to be/i)).toBeInTheDocument();
    expect(screen.queryByText(/your decision profile is on its way/i)).not.toBeInTheDocument();
  });

  it('does not show success when the backend rejects the request', async () => {
    const user = userEvent.setup();
    jest.spyOn(global, 'fetch').mockResolvedValue({ ok: false, status: 502 });

    render(<DecisionStyleAssessment />);
    await walkThroughAllQuestions(user);

    const input = await screen.findByLabelText(/where should we send/i);
    await user.type(input, 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email my full decision profile/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not email your decision profile/i);
    expect(screen.queryByText(/your decision profile is on its way/i)).not.toBeInTheDocument();
  });

  it('can restart back to the intro', async () => {
    const user = userEvent.setup();
    render(<DecisionStyleAssessment />);
    await user.click(screen.getByRole('button', { name: /start the reflection/i }));
    await answerCurrent(user, 1);

    await user.click(screen.getByRole('button', { name: /start over/i }));
    expect(
      await screen.findByRole('button', { name: /start the reflection/i })
    ).toBeInTheDocument();
  });

  it('recovers in-progress answers from localStorage after a refresh', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<DecisionStyleAssessment />);
    await user.click(screen.getByRole('button', { name: /start the reflection/i }));
    await answerCurrent(user, 1); // Q1 answered, now on Q2
    await screen.findByText(/question 2 of 7/i);

    unmount(); // simulate refresh
    render(<DecisionStyleAssessment />);
    // Comes back on the question flow, not the intro.
    expect(await screen.findByText(/question 2 of 7/i)).toBeInTheDocument();
  });
});
