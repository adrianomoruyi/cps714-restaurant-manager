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
