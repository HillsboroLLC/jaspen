import React from 'react';
import { render, waitFor } from '@testing-library/react';
import AuthCallback from './AuthCallback';

const mockNavigate = jest.fn();
let mockSearch = '';

jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useLocation: () => ({ search: mockSearch }),
}));
jest.mock('../auth/AuthContext', () => ({ useAuth: () => ({ setMfaEnforcement: jest.fn() }) }));
jest.mock('../auth/http', () => ({ authFetch: jest.fn() }));
jest.mock('../auth/pendingIntakeContext', () => ({
  readPendingIntakeContext: () => null,
  clearPendingIntakeContext: jest.fn(),
  getOrCreatePendingThreadId: jest.fn(),
  clearPendingIntakeThreadId: jest.fn(),
  runExclusiveHandoff: jest.fn(),
}));

beforeEach(() => {
  mockNavigate.mockClear();
});

test.each([
  ['?next=%2Faccount%3Ftab%3Dplans', '/account?tab=plans'],
  ['?next=%2F%5Cevil.example', '/new'],
])('navigates %s to %s', async (search, expected) => {
  mockSearch = search;
  render(<AuthCallback />);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith(expected, { replace: true }));
});
