import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OrdersPage } from './Orders.jsx';

const auth = { user: { employee_id: '7', role: 'server' }, credentials: { username: 'alex', password: 'simple' } };
const first = {
  seat_order_id: '11', table_id: '3', table_number: '1', seat_id: '4', seat_number: '1',
  menu_item_id: '5', menu_item_name: 'Soup', quantity: '2', unit_price: '8.50', line_total: '17.00', status: 'pending', can_manage: true,
};
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
let data;

beforeEach(() => {
  data = {
    tables: [
      { table_id: '3', table_number: '1', can_manage: true, seats: [{ seat_id: '4', seat_number: '1' }, { seat_id: '5', seat_number: '2' }] },
      { table_id: '6', table_number: '2', can_manage: false, seats: [{ seat_id: '8', seat_number: '1' }] },
    ],
    items: [{ menu_item_id: '5', name: 'Soup', price: '8.50' }],
    orders: [
      { ...first },
      { ...first, seat_order_id: '12', table_id: '6', table_number: '2', can_manage: false, menu_item_name: 'Tea' },
      { ...first, seat_order_id: '13', menu_item_name: 'Coffee', status: 'cancelled' },
      { ...first, seat_order_id: '14', menu_item_name: 'Bread', status: 'paid' },
    ],
  };
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    if (path === '/api/orders' && !options.method) return response(structuredClone(data));
    throw new Error(`Unexpected request: ${options.method} ${path}`);
  }));
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mutations(handler) {
  const get = fetch.getMockImplementation();
  fetch.mockImplementation((path, options) => options.method ? handler(path, options) : get(path, options));
}

async function chooseTable(browser) {
  await screen.findByRole('combobox', { name: 'Table' });
  await browser.selectOptions(screen.getByRole('combobox', { name: 'Table' }), '3');
}

async function fillOrder(browser) {
  await chooseTable(browser);
  await browser.selectOptions(screen.getByRole('combobox', { name: 'Seat' }), '4');
  await browser.selectOptions(screen.getByRole('combobox', { name: 'Menu item' }), '5');
}

it('shows active order items and filters them by table', async () => {
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  await screen.findByText('Soup');
  expect(screen.getByText('Tea')).toBeTruthy();
  expect(screen.queryByText('Coffee')).toBeNull();
  await chooseTable(browser);
  expect(screen.getByText('Soup')).toBeTruthy();
  expect(screen.queryByText('Tea')).toBeNull();
});

it('adds an item to a specific seat and refreshes the saved order', async () => {
  mutations((path, options) => {
    expect(path).toBe('/api/orders');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ seat_id: '4', menu_item_id: '5', quantity: '3' });
    data.orders.push({ ...first, seat_order_id: '15', quantity: '3', line_total: '25.50' });
    return response({ message: 'Order item added.' }, 201);
  });
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  await fillOrder(browser);
  await browser.clear(screen.getByRole('spinbutton', { name: 'Quantity', exact: true }));
  await browser.type(screen.getByRole('spinbutton', { name: 'Quantity', exact: true }), '3');
  await browser.click(screen.getByRole('button', { name: 'Add item' }));
  const added = await screen.findByRole('row', { name: /order 15$/ });
  expect(within(added).getByText('$25.50')).toBeTruthy();
  expect(screen.getByRole('status').textContent).toBe('Order item added.');
  expect(screen.getByRole('combobox', { name: 'Menu item' }).value).toBe('');
});

it('edits the quantity of a pending item', async () => {
  mutations((path, options) => {
    expect(path).toBe('/api/orders/11');
    expect(options.method).toBe('PATCH');
    expect(JSON.parse(options.body)).toEqual({ quantity: '4' });
    data.orders[0] = { ...first, quantity: '4', line_total: '34.00' };
    return response({ message: 'Order item updated.' });
  });
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  const row = await screen.findByRole('row', { name: /order 11$/ });
  await browser.clear(within(row).getByRole('spinbutton'));
  await browser.type(within(row).getByRole('spinbutton'), '4');
  await browser.click(within(row).getByRole('button', { name: 'Save quantity' }));
  expect(await screen.findByText('$34.00')).toBeTruthy();
  expect(screen.getByRole('spinbutton', { name: /order 11$/ }).value).toBe('4');
});

it('progresses through preparation and serving and locks quantity after preparation starts', async () => {
  mutations((path, options) => {
    expect(path).toBe('/api/orders/11');
    expect(options.method).toBe('PATCH');
    const { status } = JSON.parse(options.body);
    expect(['preparing', 'served']).toContain(status);
    data.orders[0] = { ...data.orders[0], status };
    return response({ message: 'Order item updated.' });
  });
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Start preparing' }));
  const prepare = await screen.findByRole('button', { name: 'Mark served' });
  let row = screen.getByRole('row', { name: /order 11$/ });
  expect(within(row).queryByRole('spinbutton')).toBeNull();
  expect(within(row).getByText('preparing')).toBeTruthy();
  await browser.click(prepare);
  await screen.findByText('served');
  row = screen.getByRole('row', { name: /order 11$/ });
  expect(within(row).queryByRole('button', { name: 'Mark served' })).toBeNull();
  expect(within(row).getByRole('button', { name: 'Cancel item' })).toBeTruthy();
});

it('confirms cancellation and keeps the cancelled item in read-only history', async () => {
  mutations((path, options) => {
    expect(path).toBe('/api/orders/11');
    expect(options.method).toBe('PATCH');
    expect(JSON.parse(options.body)).toEqual({ status: 'cancelled' });
    data.orders[0] = { ...first, status: 'cancelled' };
    return response({ message: 'Order item cancelled. History was kept.' });
  });
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  const row = await screen.findByRole('row', { name: /order 11$/ });
  await browser.click(within(row).getByRole('button', { name: 'Cancel item' }));
  expect(fetch.mock.calls.some(([, options]) => options.method === 'PATCH')).toBe(false);
  await browser.click(within(row).getByRole('button', { name: 'Confirm cancellation' }));
  await screen.findByRole('status');
  await screen.findByText('Tea');
  expect(screen.queryByText('Soup')).toBeNull();
  await browser.click(screen.getByRole('checkbox', { name: 'Show cancelled and paid items' }));
  const cancelled = screen.getByRole('row', { name: /order 11$/ });
  expect(within(cancelled).getByText('cancelled')).toBeTruthy();
  expect(within(cancelled).queryByRole('button')).toBeNull();
});

it('keeps other servers tables read-only and does not show an order entry form for them', async () => {
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  const row = await screen.findByRole('row', { name: /order 12$/ });
  expect(within(row).queryByRole('button')).toBeNull();
  expect(within(row).queryByRole('spinbutton')).toBeNull();
  await browser.selectOptions(screen.getByRole('combobox', { name: 'Table' }), '6');
  expect(screen.queryByRole('button', { name: 'Add item' })).toBeNull();
  expect(screen.getByText(/Only a manager or this table’s assigned server/)).toBeTruthy();
});

it('keeps paid items read-only when history is shown', async () => {
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  await screen.findByRole('checkbox', { name: 'Show cancelled and paid items' });
  await browser.click(screen.getByRole('checkbox', { name: 'Show cancelled and paid items' }));
  const row = screen.getByRole('row', { name: /order 14$/ });
  expect(within(row).getByText('paid')).toBeTruthy();
  expect(within(row).queryByRole('button')).toBeNull();
});

it('shows assignment changes without discarding the order form or logging out', async () => {
  mutations(() => response({ error: 'You can only manage orders for tables assigned to you.' }, 403));
  const browser = userEvent.setup();
  const logout = vi.fn();
  render(<OrdersPage auth={auth} onLogout={logout} />);
  await fillOrder(browser);
  await browser.click(screen.getByRole('button', { name: 'Add item' }));
  expect((await screen.findByRole('alert')).textContent).toContain('assigned to you');
  expect(screen.getByRole('combobox', { name: 'Menu item' }).value).toBe('5');
  expect(logout).not.toHaveBeenCalled();
});

it('shows a stale menu availability error while preserving the selection for correction', async () => {
  mutations(() => response({ error: 'Choose an available menu item from your restaurant.' }, 400));
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  await fillOrder(browser);
  await browser.click(screen.getByRole('button', { name: 'Add item' }));
  expect((await screen.findByRole('alert')).textContent).toContain('available menu item');
  expect(screen.getByRole('combobox', { name: 'Seat' }).value).toBe('4');
});

it('disables ordering when a table has no seats or available menu items', async () => {
  data.tables[0].seats = [];
  data.items = [];
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  await chooseTable(browser);
  expect(screen.getByText(/This table has no seats/)).toBeTruthy();
  expect(screen.getByText(/No available menu items/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Add item' }).disabled).toBe(true);
});

it('shows an empty restaurant and lets a failed data request be retried', async () => {
  data = { tables: [], items: [], orders: [] };
  fetch.mockResolvedValueOnce(response({ error: 'Database unavailable.' }, 503));
  const browser = userEvent.setup();
  render(<OrdersPage auth={auth} onLogout={vi.fn()} />);
  await screen.findByRole('alert');
  await browser.click(screen.getByRole('button', { name: 'Try again' }));
  expect(await screen.findByText(/No tables are available yet/)).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'No order items to show' })).toBeTruthy();
});
