import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BillsPage } from './Billing.jsx';
import { EmployeesPage, RestaurantsPage } from './Administration.jsx';
import { TablesPage } from './Management.jsx';

const auth = { user: { employee_id: '7', role: 'manager' }, credentials: { username: 'alex', password: 'simple' } };
const table = { table_id: '3', table_number: '1', capacity: '2', status: 'available', seats: [{ seat_id: '4', seat_number: '1' }, { seat_id: '5', seat_number: '2' }] };
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => structuredClone(data) });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('saves an equal split and manager discount and displays what each person owes', async () => {
  let settings = { mode: 'seats', people: 2, groups: [], discount_kind: 'none', discount_value: '0.00', discount_reason: '' };
  const items = [
    { seat_order_id: '11', seat_id: '4', seat_number: '1', menu_item_name: 'Soup', quantity: '1', unit_price: '10.01' },
    { seat_order_id: '12', seat_id: '5', seat_number: '2', menu_item_name: 'Tea', quantity: '1', unit_price: '5.00' },
  ];
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    if (path === '/api/tables') return response({ tables: [table] });
    if (path === '/api/bills/3' && !options.method) {
      const discounted = settings.discount_kind === 'percentage';
      const totals = settings.mode === 'equal' ? (discounted ? ['4.51', '4.50', '4.50'] : ['5.01', '5.00', '5.00']) : ['10.01', '5.00'];
      return response({ table, settings, items, can_manage: true, subtotal: '15.01', discount_total: discounted ? '1.50' : '0.00', total: discounted ? '13.51' : '15.01',
        bills: totals.map((total, i) => ({ label: settings.mode === 'equal' ? `Person ${i + 1}` : `Seat ${i + 1}`, seat_numbers: [], subtotal: total, discount: '0.00', total })) });
    }
    if (path === '/api/bills/3/split') {
      expect(options.method).toBe('PUT');
      expect(JSON.parse(options.body)).toEqual({ mode: 'equal', people: '3', groups: [] });
      settings = { ...settings, ...JSON.parse(options.body) };
      return response({ message: 'Bill split saved.' });
    }
    if (path === '/api/bills/3/discount') {
      expect(options.method).toBe('PUT');
      expect(JSON.parse(options.body)).toEqual({ kind: 'percentage', value: '10', reason: 'Service recovery' });
      settings = { ...settings, discount_kind: 'percentage', discount_value: '10.00', discount_reason: 'Service recovery' };
      return response({ message: 'Manager discount saved.' });
    }
    throw new Error(`Unexpected request: ${path}`);
  }));
  const browser = userEvent.setup();
  render(<BillsPage auth={auth} onLogout={vi.fn()} initialTableId="3" />);
  await browser.selectOptions(await screen.findByLabelText('Split method'), 'equal');
  await browser.clear(screen.getByLabelText('Number of people'));
  await browser.type(screen.getByLabelText('Number of people'), '3');
  await browser.click(screen.getByRole('button', { name: 'Calculate & save split' }));
  expect(within(await screen.findByRole('article', { name: 'Person 1' })).getAllByText('$5.01').length).toBeGreaterThan(0);
  await browser.selectOptions(screen.getByLabelText('Discount type'), 'percentage');
  await browser.clear(screen.getByLabelText('Discount value'));
  await browser.type(screen.getByLabelText('Discount value'), '10');
  await browser.type(screen.getByLabelText('Discount reason'), 'Service recovery');
  await browser.click(screen.getByRole('button', { name: 'Approve discount' }));
  await screen.findByText('$13.51');
  expect(within(screen.getByRole('article', { name: 'Person 1' })).getAllByText('$4.51').length).toBeGreaterThan(0);
});

it('deactivates an employee while keeping their existing password out of the form', async () => {
  let employee = { employee_id: '8', first_name: 'Sam', last_name: 'Lee', username: 'sam', role: 'server', status: 'active' };
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    if (path === '/api/employees' && !options.method) return response({ employees: [employee] });
    expect(path).toBe('/api/employees/8');
    expect(options.method).toBe('PUT');
    expect(JSON.parse(options.body)).toEqual({ first_name: 'Sam', last_name: 'Lee', username: 'sam', password: '', role: 'server', status: 'inactive' });
    employee = { ...employee, status: 'inactive' };
    return response({ message: 'Employee updated.' });
  }));
  const browser = userEvent.setup();
  render(<EmployeesPage auth={auth} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Edit employee' }));
  expect(screen.getByLabelText('New password (optional)').value).toBe('');
  expect(within(screen.getByLabelText('Role')).getAllByRole('option').map(option => option.value)).toEqual(['server', 'manager']);
  await browser.selectOptions(screen.getByLabelText('Account status'), 'inactive');
  await browser.click(screen.getByRole('button', { name: 'Save employee' }));
  expect(await screen.findByText('inactive')).toBeTruthy();
});

it('creates a restaurant while keeping the manager in their own restaurant', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    if (path === '/api/restaurant' && !options.method) return response({ restaurant: { restaurant_id: '2', name: 'The Rustic Spoon', address: 'Old address' } });
    expect(path).toBe('/api/restaurants');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ name: 'New restaurant', address: '123 Main St', phone: '555-0100' });
    return response({ message: 'New restaurant created. Its team can select it when registering.' }, 201);
  }));
  const browser = userEvent.setup();
  render(<RestaurantsPage auth={auth} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Add restaurant' }));
  await browser.type(screen.getByLabelText('Restaurant name'), 'New restaurant');
  await browser.type(screen.getByLabelText('Address'), '123 Main St');
  await browser.type(screen.getByLabelText('Phone'), '555-0100');
  await browser.click(screen.getByRole('button', { name: 'Save restaurant' }));
  expect((await screen.findByRole('status')).textContent).toContain('New restaurant created');
  expect(await screen.findByRole('cell', { name: 'The Rustic Spoon' })).toBeTruthy();
});

it('adds an individual numbered seat and shows the updated table capacity', async () => {
  let savedTable = structuredClone(table);
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    if (path === '/api/tables' && !options.method) return response({ tables: [savedTable], servers: [] });
    expect(path).toBe('/api/tables/3/seats');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ seat_number: '7' });
    savedTable = { ...savedTable, capacity: '3', seats: [...savedTable.seats, { seat_id: '6', seat_number: '7' }] };
    return response({ message: 'Seat added.' }, 201);
  }));
  const browser = userEvent.setup();
  render(<TablesPage auth={auth} onLogout={vi.fn()} />);
  await browser.click(await screen.findByRole('button', { name: 'Add seat' }));
  await browser.type(screen.getByLabelText('Seat number'), '7');
  await browser.click(screen.getByRole('button', { name: 'Save seat' }));
  expect(await screen.findByText('Seat 7')).toBeTruthy();
  expect(screen.getByText(/3 seats/)).toBeTruthy();
});
