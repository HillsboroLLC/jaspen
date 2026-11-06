import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import RequireAuth from './RequireAuth';
import { safeInternalPath } from './safeRedirect';

jest.mock('./http', () => ({
  authFetch: () => Promise.resolve({ ok: false }),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

test('the real path and query round trip remains a safe unchanged next value', async () => {
  render(
    <MemoryRouter initialEntries={['/account?tab=plans']}>
      <Routes>
        <Route path="/account" element={<RequireAuth><div>private</div></RequireAuth>} />
        <Route path="/" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );

  await waitFor(() => expect(screen.getByTestId('location').textContent).toContain('next='));
  const location = screen.getByTestId('location').textContent;
  const encodedNext = new URLSearchParams(location.split('?')[1]).get('next');
  expect(encodedNext).toBe('/account?tab=plans');
  expect(safeInternalPath(encodedNext)).toBe('/account?tab=plans');
});
