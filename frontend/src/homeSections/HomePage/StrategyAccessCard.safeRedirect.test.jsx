import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import StrategyAccessCard from './StrategyAccessCard';

const mockLogin = jest.fn();
const mockSignup = jest.fn();
const mockAuthFetch = jest.fn();
const mockReadPendingIntakeContext = jest.fn();

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({
    login: mockLogin,
    signup: mockSignup,
    mfaEnforcement: null,
    setMfaEnforcement: jest.fn(),
  }),
}));
jest.mock('../../shared/auth/http', () => ({ authFetch: (...args) => mockAuthFetch(...args) }));
jest.mock('../../shared/auth/pendingIntakeContext', () => ({
  readPendingIntakeContext: () => mockReadPendingIntakeContext(),
  writePendingIntakeContext: jest.fn(),
  clearPendingIntakeContext: jest.fn(),
  getOrCreatePendingThreadId: () => 'pending-thread',
  clearPendingIntakeThreadId: jest.fn(),
  runExclusiveHandoff: (fn) => Promise.resolve().then(fn),
}));

const realLocation = window.location;

function setLocation(search = '') {
  window.location.search = search;
  window.location.href = `http://localhost/${search}`;
}

function fillEmailForm({ signup = false } = {}) {
  if (signup) {
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Test User' } });
  }
  fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'user@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'ValidPass1' } });
  if (signup) {
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'ValidPass1' } });
  }
  const submit = screen.getAllByRole('button', { name: signup ? 'Create free account' : 'Sign in' })
    .find((button) => button.type === 'submit');
  fireEvent.click(submit);
}

beforeAll(() => {
  delete window.location;
  window.location = {
    ...realLocation,
    href: 'http://localhost/',
    search: '',
    hostname: 'localhost',
    origin: 'http://localhost',
  };
});

afterAll(() => {
  window.location = realLocation;
});

beforeEach(() => {
  jest.clearAllMocks();
  window.matchMedia = jest.fn(() => ({ matches: true }));
  mockLogin.mockResolvedValue({ success: true });
  mockSignup.mockResolvedValue({ success: true });
  mockReadPendingIntakeContext.mockReturnValue(null);
  setLocation();
});

test.each([
  ['/new?sid=abc', '/new?sid=abc'],
  ['//evil.example', '/new'],
  ['/\\evil.example', '/new'],
  ['/%09/evil.example', '/new'],
])('sign-in sends next=%s to %s', async (next, expected) => {
  setLocation(`?next=${encodeURIComponent(next)}`);
  render(<StrategyAccessCard />);
  fillEmailForm();
  await waitFor(() => expect(window.location.href).toBe(expected));
});

test('sign-up uses the safe destination', async () => {
  setLocation('?next=%2Fnew%3Fsid%3Dabc');
  render(<StrategyAccessCard />);
  fillEmailForm({ signup: true });
  await waitFor(() => expect(window.location.href).toBe('/new?sid=abc'));
});

test('pending-context handoff still wins', async () => {
  setLocation('?next=%2Faccount');
  mockReadPendingIntakeContext.mockReturnValue('context');
  mockAuthFetch.mockResolvedValue({ ok: true, json: async () => ({ thread_id: 'continued-thread' }) });
  render(<StrategyAccessCard />);
  fillEmailForm();
  await waitFor(() => expect(window.location.href).toBe('/new?sid=continued-thread'));
});

test('Google start receives only a safe next value', () => {
  setLocation('?next=%2F%5Cevil.example');
  render(<StrategyAccessCard />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }));
  const url = new URL(window.location.href, 'http://localhost');
  expect(url.pathname).toBe('/api/v1/auth/google/start');
  expect(url.searchParams.get('next')).toBe('/new');
});

test('invalid decision-profile email next behaves like a missing next', async () => {
  setLocation('?next=%2F%5Cevil.example&source=decision-profile-email');
  render(<StrategyAccessCard />);
  fillEmailForm();
  await waitFor(() => expect(window.location.href).toBe('/decision-profile'));
});
