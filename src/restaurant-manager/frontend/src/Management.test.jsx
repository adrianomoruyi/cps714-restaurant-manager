import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
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

it('edits an existing menu item without creating a new one', async () => {
  handleMutation((path, options) => {
    expect(path).toBe('/api/menu/5');
    expect(options.method).toBe('PUT');
    const payload = JSON.parse(options.body);
    items = [{ ...payload, menu_item_id: '5' }];
    return response({ message: 'Menu item updated.' });
  });
  const browser = userEvent.setup();
  render(<MenuPage auth={manager} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Edit' }));
  await browser.clear(screen.getByLabelText('Item name'));
  await browser.type(screen.getByLabelText('Item name'), 'Tomato soup');
  await browser.click(screen.getByRole('button', { name: 'Save item' }));
  expect(await screen.findByText('Tomato soup')).toBeTruthy();
  expect(items).toHaveLength(1);
});

it('requires delete confirmation and preserves an item when order history blocks deletion', async () => {
  handleMutation((path, options) => {
    expect(path).toBe('/api/menu/5');
    expect(options.method).toBe('DELETE');
    return response({ error: 'This item has orders. Mark it unavailable instead of deleting it.' }, 409);
  });
  const browser = userEvent.setup();
  render(<MenuPage auth={manager} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Delete' }));
  expect(fetch.mock.calls.some(([, options]) => options.method === 'DELETE')).toBe(false);
  await browser.click(screen.getByRole('button', { name: 'Confirm delete' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Mark it unavailable');
  expect(screen.getByText('Soup')).toBeTruthy();
});

it('marks menu items unavailable without deleting them', async () => {
  handleMutation((path, options) => {
    expect(path).toBe('/api/menu/5');
    expect(options.method).toBe('PUT');
    expect(JSON.parse(options.body).available).toBe(false);
    items = [{ ...item, available: false }];
    return response({ message: 'Menu item updated.' });
  });
  const browser = userEvent.setup();
  render(<MenuPage auth={manager} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Mark unavailable' }));
  expect(await screen.findByText('Unavailable')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Mark available' })).toBeTruthy();
});

it('creates a table and displays its generated seats', async () => {
  handleMutation((path, options) => {
    expect(path).toBe('/api/tables');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ table_number: '2', capacity: '2' });
    tables.push({ ...table, table_id: '4', table_number: '2' });
    return response({ message: 'Table and seats created.' }, 201);
  });
  const browser = userEvent.setup();
  render(<TablesPage auth={manager} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Add table' }));
  await browser.type(screen.getByLabelText('Table number'), '2');
  await browser.clear(screen.getByLabelText('Capacity'));
  await browser.type(screen.getByLabelText('Capacity'), '2');
  await browser.click(screen.getByRole('button', { name: 'Save table' }));
  const added = await screen.findByRole('article', { name: 'Table 2' });
  expect(within(added).getByText('Seat 1')).toBeTruthy();
  expect(within(added).getByText('Seat 2')).toBeTruthy();
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

it('keeps assignment controls hidden from servers', async () => {
  render(<AssignmentsPage auth={server} onLogout={vi.fn()} />);
  await screen.findByText('Table 1');
  expect(screen.queryByRole('combobox')).toBeNull();
  expect(screen.queryByRole('button', { name: /assign|reassign|remove assignment/i })).toBeNull();
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

it('handles lost manager permission without discarding an unsaved menu form', async () => {
  handleMutation(() => response({ error: 'Manager access is required for this action.' }, 403));
  const onLogout = vi.fn();
  const browser = userEvent.setup();
  render(<MenuPage auth={manager} onLogout={onLogout} />);
  await browser.click(await screen.findByRole('button', { name: 'Add menu item' }));
  await browser.type(screen.getByLabelText('Item name'), 'Lemonade');
  await browser.type(screen.getByLabelText('Price (CAD)'), '4.25');
  await browser.click(screen.getByRole('button', { name: 'Save item' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Manager access');
  expect(screen.getByLabelText('Item name').value).toBe('Lemonade');
  expect(onLogout).not.toHaveBeenCalled();
});

it('retries loading restaurant data after a temporary database failure', async () => {
  fetch.mockResolvedValueOnce(response({ error: 'Database unavailable.' }, 503));
  const browser = userEvent.setup();
  render(<MenuPage auth={manager} onLogout={vi.fn()} />);
  await screen.findByRole('alert');
  await browser.click(screen.getByRole('button', { name: 'Try again' }));
  await waitFor(() => expect(screen.getByText('Soup')).toBeTruthy());
});
