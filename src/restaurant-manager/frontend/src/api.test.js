import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api.js';

afterEach(() => vi.unstubAllGlobals());

it('keeps the Databricks cookie available for API calls behind an authentication proxy', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_path, options) => {
    if (options.credentials !== 'same-origin') {
      return { ok: false, status: 401, json: async () => ({ message: 'Platform sign-in required' }) };
    }
    return { ok: true, status: 200, json: async () => ({ restaurants: [{ restaurant_id: '1', name: 'The Rustic Spoon' }] }) };
  }));
  const result = await api('/restaurants');
  expect(result.restaurants[0].name).toBe('The Rustic Spoon');
});

it('explains a platform denial when the proxy returns HTML instead of API JSON', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false, status: 401, json: async () => { throw new SyntaxError('HTML sign-in page'); },
  })));
  await expect(api('/restaurants')).rejects.toMatchObject({ status: 401, message: expect.stringContaining('Databricks sign-in') });
});

it('rejects a sign-in redirect instead of treating it as a successful API response', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, redirected: true, json: async () => { throw new SyntaxError('HTML sign-in page'); },
  })));
  await expect(api('/login', { method: 'POST', body: '{}' })).rejects.toMatchObject({ status: 502, message: expect.stringContaining('Databricks sign-in') });
});

it('preserves application errors such as invalid employee credentials', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false, status: 401, json: async () => ({ error: 'Invalid username or password.' }),
  })));
  await expect(api('/login', { method: 'POST', body: '{}' })).rejects.toThrow('Invalid username or password.');
});

it('reports non-JSON server errors with their HTTP status', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false, status: 502, json: async () => { throw new SyntaxError('Bad gateway'); },
  })));
  await expect(api('/restaurants')).rejects.toMatchObject({ status: 502, message: expect.stringContaining('HTTP 502') });
});
