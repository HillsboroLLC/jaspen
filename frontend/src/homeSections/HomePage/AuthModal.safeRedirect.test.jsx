import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import AuthModal from './AuthModal';

const mockLogin = jest.fn();
const mockSignup = jest.fn();
const mockSetUser = jest.fn();

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ login: mockLogin, signup: mockSignup, setUser: mockSetUser }),
}));

const realLocation = window.location;

function setLocation(search = '') {
  window.location.search = search;
  window.location.href = `http://localhost/${search}`;
}

async function submitEmail() {
  fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'user@example.com' } });
  fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'ValidPass1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Continue with email' }));
  await waitFor(() => expect(mockLogin).toHaveBeenCalled());
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
  mockLogin.mockResolvedValue({ success: true });
  mockSignup.mockResolvedValue({ success: true });
  setLocation();
});

test.each([
  ['/new?sid=abc', '/new?sid=abc'],
  ['//evil.example', '/new'],
  ['/\\evil.example', '/new'],
  ['/%09/evil.example', '/new'],
])('email sign-in sends next=%s to %s', async (next, expected) => {
  setLocation(`?next=${encodeURIComponent(next)}`);
  render(<AuthModal isOpen mode="email" />);
  await submitEmail();
  await waitFor(() => expect(window.location.href).toBe(expected));
});

test('sign-up fallback uses the safe destination', async () => {
  setLocation('?next=%2Fnew%3Fsid%3Dabc');
  mockLogin.mockResolvedValue({ success: false });
  render(<AuthModal isOpen mode="email" />);
  await submitEmail();
  await waitFor(() => expect(mockSignup).toHaveBeenCalled());
  expect(window.location.href).toBe('/new?sid=abc');
});

test('verification-code completion uses the safe destination', async () => {
  setLocation('?next=%2F%2509%2Fevil.example');
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ user: { id: 'user-1' } }),
  });
  render(<AuthModal
    isOpen
    mode="email"
    initialMfaData={{ mfaRequired: true, mfaSetupRequired: false, pendingToken: 'pending-1' }}
  />);
  fireEvent.change(screen.getByLabelText(/Authentication code/), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
  await waitFor(() => expect(window.location.href).toBe('/new'));
});

test('Google start receives only a safe next value', () => {
  setLocation('?next=%2F%5Cevil.example');
  render(<AuthModal isOpen mode="google" />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }));
  const url = new URL(window.location.href, 'http://localhost');
  expect(url.pathname).toBe('/api/v1/auth/google/start');
  expect(url.searchParams.get('next')).toBe('/new');
});

test('invalid decision-profile email next behaves like a missing next', async () => {
  setLocation('?next=%2F%5Cevil.example&source=decision-profile-email');
  render(<AuthModal isOpen mode="email" />);
  await submitEmail();
  await waitFor(() => expect(window.location.href).toBe('/decision-profile'));
});
