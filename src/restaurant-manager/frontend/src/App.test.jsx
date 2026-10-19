import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';

const user = { employee_id: '7', restaurant_id: '2', first_name: 'Alex', last_name: 'Chen', role: 'server', username: 'alex' };
const tables = [
  { table_id: '3', table_number: '1', capacity: '4', status: 'available', server_name: null },
  { table_id: '4', table_number: '2', capacity: '2', status: 'occupied', server_name: 'Alex' },
];

function respond(data, status = 200) {
  return { ok: status < 400, status, json: async () => data };
}

beforeEach(() => {
  window.history.replaceState({}, '', '/login');
  vi.stubGlobal('fetch', vi.fn(async path => {
    if (path === '/api/restaurants') return respond({ restaurants: [{ restaurant_id: '2', name: 'The Rustic Spoon' }] });
    if (path === '/api/login') return respond({ user });
    if (path === '/api/dashboard') return respond({ tables });
    if (path === '/api/register') return respond({ message: 'Account created. You can now log in.' }, 201);
    throw new Error(`Unexpected request: ${path}`);
  }));
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function logIn() {
  const browser = userEvent.setup();
  await browser.type(screen.getByLabelText('Username'), 'alex');
  await browser.type(screen.getByLabelText('Password'), 'simple');
  await browser.click(screen.getByRole('button', { name: 'Log in' }));
  return browser;
}

describe('sprint pages', () => {
  it('logs in, renders read-only tables, and logs out without persistent login storage', async () => {
    render(<App />);
    const browser = await logIn();
    await screen.findByText('4 seats');
    expect(screen.getByRole('heading', { name: 'Hello, Alex.' })).toBeTruthy();
    expect(screen.getByText('Unassigned')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /clear|assign|order|delete/i })).toBeNull();
    expect(window.location.pathname).toBe('/dashboard');
    const request = fetch.mock.calls.find(([path]) => path === '/api/dashboard')[1];
    expect(request.headers.get('X-Restaurant-Authorization')).toBe(`Basic ${btoa('alex:simple')}`);
    expect(request.headers.has('Authorization')).toBe(false);
    expect(request.credentials).toBe('same-origin');
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    await browser.click(screen.getByRole('button', { name: 'Log out' }));
    expect(screen.getByRole('heading', { name: 'Ready for the day?' })).toBeTruthy();
    expect(window.location.pathname).toBe('/login');
  });

  it('shows a failed login without opening the dashboard', async () => {
    fetch.mockImplementation(async () => respond({ error: 'Invalid username or password.' }, 401));
    render(<App />);
    await logIn();
    expect((await screen.findByRole('alert')).textContent).toContain('Invalid username');
    expect(window.location.pathname).toBe('/login');
  });

  it('registers an account and sends the user back to login', async () => {
    render(<App />);
    const browser = userEvent.setup();
    await browser.click(screen.getByRole('link', { name: 'Create an account' }));
    await screen.findByRole('option', { name: 'The Rustic Spoon' });
    await browser.type(screen.getByLabelText('First name'), 'Alex');
    await browser.type(screen.getByLabelText('Last name'), 'Chen');
    await browser.selectOptions(screen.getByLabelText('Restaurant'), '2');
    await browser.type(screen.getByLabelText('Username'), 'alex');
    await browser.type(screen.getByLabelText('Password'), 'simple');
    await browser.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByRole('heading', { name: 'Ready for the day?' });
    expect(screen.getByRole('status').textContent).toContain('Account created');
    expect(screen.getByLabelText('Username').value).toBe('alex');
    const payload = JSON.parse(fetch.mock.calls.find(([path]) => path === '/api/register')[1].body);
    expect(payload).toEqual({ first_name: 'Alex', last_name: 'Chen', restaurant_id: '2', role: 'server', username: 'alex', password: 'simple' });
    for (const [, options] of fetch.mock.calls) {
      expect(options.credentials).toBe('same-origin');
      expect(options.headers.has('Authorization')).toBe(false);
    }
  });

  it('requires login after a fresh visit to the dashboard', async () => {
    window.history.replaceState({}, '', '/dashboard');
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe('/login'));
    expect(screen.getByRole('button', { name: 'Log in' })).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('handles an empty dashboard', async () => {
    fetch.mockImplementation(async path => path === '/api/login' ? respond({ user }) : respond({ tables: [] }));
    render(<App />);
    await logIn();
    expect(await screen.findByRole('heading', { name: 'No tables yet' })).toBeTruthy();
  });

  it('shows a dashboard database failure and allows retry', async () => {
    let attempts = 0;
    fetch.mockImplementation(async path => {
      if (path === '/api/login') return respond({ user });
      return ++attempts === 1 ? respond({ error: 'Database unavailable.' }, 503) : respond({ tables });
    });
    render(<App />);
    const browser = await logIn();
    expect((await screen.findByRole('alert')).textContent).toContain('Database unavailable');
    await browser.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByText('4 seats')).toBeTruthy();
  });

  it('disables registration when there are no restaurants', async () => {
    window.history.replaceState({}, '', '/register');
    fetch.mockResolvedValue(respond({ restaurants: [] }));
    render(<App />);
    expect((await screen.findByRole('status')).textContent).toContain('No restaurants');
    expect(screen.getByRole('button', { name: 'Create account' }).disabled).toBe(true);
  });
});
