import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AssignmentsPage, MenuPage, TablesPage } from './Management.jsx';

const manager = { user: { role: 'manager' }, credentials: { username: 'alex', password: 'simple' } };
const server = { ...manager, user: { role: 'server' } };
const item = { menu_item_id: '5', name: 'Soup', description: 'Seasonal', category: 'Starter', price: '8.50', available: true };
const table = {
  table_id: '3', table_number: '1', capacity: '2', status: 'available', server_id: null,
  server_first_name: null, server_last_name: null,
  seats: [{ seat_id: '11', seat_number: '1' }, { seat_id: '12', seat_number: '2' }],
};
const servers = [{ employee_id: '8', first_name: 'Sam', last_name: 'Lee' }];
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
let items;
let tables;

beforeEach(() => {
  items = [{ ...item }];
  tables = [{ ...table, seats: [...table.seats] }];
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    const method = options.method || 'GET';
    if (path === '/api/menu' && method === 'GET') return response({ items: items.map(item => ({ ...item })) });
    if (path === '/api/tables' && method === 'GET') return response({ tables: structuredClone(tables), servers });
    throw new Error(`Unexpected request: ${method} ${path}`);
  }));
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function handleMutation(handler) {
  const get = fetch.getMockImplementation();
  fetch.mockImplementation(async (path, options) => {
    if (!options.method || options.method === 'GET') return get(path, options);
    return handler(path, options);
  });
}

it('lets servers view the menu without management controls', async () => {
  render(<MenuPage auth={server} onLogout={vi.fn()} />);
  await screen.findByText('Soup');
  expect(screen.getByText('$8.50')).toBeTruthy();
  expect(screen.queryByRole('button', { name: /add menu item|edit|delete|mark unavailable/i })).toBeNull();
  expect(screen.getByText(/You have view access/)).toBeTruthy();
});

it('creates a menu item and refreshes the list with the saved result', async () => {
  handleMutation((path, options) => {
    expect(path).toBe('/api/menu');
    expect(options.method).toBe('POST');
    const payload = JSON.parse(options.body);
    expect(payload).toEqual({ name: 'Lemonade', category: 'Beverage', description: 'Fresh lemon', price: '4.25', available: false });
    items.push({ ...payload, menu_item_id: '6' });
    return response({ message: 'Menu item added.' }, 201);
  });
  const browser = userEvent.setup();
  render(<MenuPage auth={manager} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Add menu item' }));
  await browser.type(screen.getByLabelText('Item name'), 'Lemonade');
  await browser.type(screen.getByLabelText('Category'), 'Beverage');
  await browser.type(screen.getByLabelText('Description'), 'Fresh lemon');
  await browser.type(screen.getByLabelText('Price (CAD)'), '4.25');
  await browser.click(screen.getByLabelText('Available to order'));
  await browser.click(screen.getByRole('button', { name: 'Save item' }));
  await screen.findByText('Lemonade');
  expect(screen.getByRole('status').textContent).toBe('Menu item added.');
  expect(screen.queryByRole('heading', { name: 'New menu item' })).toBeNull();
});

it('updates table capacity and displays newly added seats', async () => {
  handleMutation((path, options) => {
    expect(path).toBe('/api/tables/3');
    expect(options.method).toBe('PUT');
    expect(JSON.parse(options.body)).toEqual({ table_number: '1', capacity: '3', status: 'reserved' });
    tables = [{ ...table, capacity: '3', status: 'reserved', seats: [...table.seats, { seat_id: '13', seat_number: '3' }] }];
    return response({ message: 'Table and seats updated.' });
  });
  const browser = userEvent.setup();
  render(<TablesPage auth={manager} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Edit table' }));
  await browser.clear(screen.getByLabelText('Capacity'));
  await browser.type(screen.getByLabelText('Capacity'), '3');
  await browser.selectOptions(screen.getByLabelText('Status'), 'reserved');
  await browser.click(screen.getByRole('button', { name: 'Save table' }));
  expect(await screen.findByText('Seat 3')).toBeTruthy();
  expect(screen.getByText('reserved')).toBeTruthy();
});

it('assigns and removes a server while showing the saved assignment and table status', async () => {
  handleMutation((path, options) => {
    expect(path).toBe('/api/tables/3/assignment');
    if (options.method === 'PUT') {
      expect(JSON.parse(options.body)).toEqual({ employee_id: '8' });
      tables = [{ ...table, server_id: '8', server_first_name: 'Sam', server_last_name: 'Lee', status: 'occupied' }];
      return response({ message: 'Server assigned. Table marked occupied.' });
    }
    expect(options.method).toBe('DELETE');
    tables = [{ ...table, status: 'occupied' }];
    return response({ message: 'Server assignment removed. Table status is unchanged.' });
  });
  const browser = userEvent.setup();
  render(<AssignmentsPage auth={manager} onLogout={vi.fn()} />);
  await screen.findByRole('option', { name: 'Sam Lee' });
  await browser.selectOptions(screen.getByLabelText('Server for table 1'), '8');
  await browser.click(screen.getByRole('button', { name: 'Assign' }));
  await screen.findByRole('cell', { name: 'Sam Lee' });
  expect(screen.getByText('occupied')).toBeTruthy();
  await browser.click(screen.getByRole('button', { name: 'Remove assignment' }));
  await screen.findByRole('cell', { name: 'Unassigned' });
  expect(screen.getByText('occupied')).toBeTruthy();
});
