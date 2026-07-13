import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DecisionProfile from './DecisionProfile';
import { authFetch } from '../../shared/auth/http';

jest.mock('../../shared/auth/http', () => ({
  authFetch: jest.fn(),
}));

jest.mock('../shared/AppMenu', () => function MockAppMenu() {
  return <nav aria-label="App menu" />;
});

const profilePayload = {
  has_profile: true,
  profile: {
    id: 1,
    style_key: 'fast_mover',
    style_name: 'Fast Mover',
    interpretation: 'You tend to read the situation quickly and keep momentum.',
    completed_at: '2026-07-13T00:00:00',
    last_updated_at: '2026-07-13T00:00:00',
    version: 1,
    responses: [
      {
        question_id: 'q1_instinct_vs_research',
        question: 'When an important decision comes up, where do you naturally start?',
        tendency: 'Starting point',
        answer_label: 'With my gut read of the situation',
        meaning: 'You tend to notice an early direction before gathering much outside information.',
      },
    ],
    sections: {
      shows_up: 'You often know what feels workable early.',
      natural_strength: 'Your natural strength is movement.',
      watch: 'A useful pattern to watch is moving before the key assumptions have been named.',
      decision_tendencies: [{ label: 'Starting point', value: 'Less often' }],
      jaspen_support: 'Jaspen helps you preserve speed while adding a quick check.',
      questions: ['What assumption needs a quick check before you act?'],
      history: 'Future versions will show how this profile changes.',
      additional_context: 'Add work context here as the profile grows.',
    },
  },
};

function jsonResponse(data, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(data),
  });
}

beforeEach(() => {
  authFetch.mockReset();
});

test('renders empty state and opens the assessment modal', async () => {
  const user = userEvent.setup();
  authFetch.mockReturnValueOnce(jsonResponse({ has_profile: false, profile: null }));

  render(<DecisionProfile />);

  expect(await screen.findByText('Your Decision Profile is ready when you are.')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /take the assessment/i }));

  expect(screen.getByRole('dialog', { name: /find your decision profile/i })).toBeInTheDocument();
  expect(screen.getByText('Question 1 of 7')).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: /with my gut read/i })).toBeInTheDocument();
});

test('renders a saved profile with response interpretation sections', async () => {
  authFetch.mockReturnValueOnce(jsonResponse(profilePayload));

  render(<DecisionProfile />);

  expect(await screen.findByRole('heading', { name: 'Fast Mover' })).toBeInTheDocument();
  expect(screen.getByText('Response profile')).toBeInTheDocument();
  expect(screen.getAllByText('With my gut read of the situation')).toHaveLength(2);
  expect(screen.getByText('How Jaspen supports your style')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /retake assessment/i })).toBeInTheDocument();

  await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/decision-profile'));
});
