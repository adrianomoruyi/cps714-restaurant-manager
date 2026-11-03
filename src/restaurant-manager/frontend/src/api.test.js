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

it('sends Unicode passwords intact without replacing platform authorization', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ tables: [] }) })));
  await api('/dashboard', {
    credentials: { username: 'alex', password: 'café:餐厅' },
    headers: { Authorization: 'Bearer platform-token' },
  });
  const { headers } = fetch.mock.calls[0][1];
  const encoded = headers.get('X-Restaurant-Authorization').slice('Basic '.length);
  const decoded = new TextDecoder().decode(Uint8Array.from(atob(encoded), character => character.charCodeAt(0)));
  expect(decoded).toBe('alex:café:餐厅');
  expect(headers.get('Authorization')).toBe('Bearer platform-token');
});

it('preserves cancellation so leaving a page does not produce a false error', async () => {
  const controller = new AbortController();
  controller.abort();
  const aborted = new DOMException('The operation was aborted.', 'AbortError');
  vi.stubGlobal('fetch', vi.fn(async (_path, { signal }) => {
    if (signal.aborted) throw aborted;
    throw new Error('The request should have been aborted');
  }));
  await expect(api('/restaurants', { signal: controller.signal })).rejects.toBe(aborted);
});

it.each([null, ['unexpected array'], 'unexpected string'])(
  'rejects an invalid successful API payload: %j', async payload => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => payload })));
    await expect(api('/restaurants')).rejects.toMatchObject({ status: 502 });
  },
);

it('handles structured platform errors without displaying an object as a message', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false, status: 403, json: async () => ({ error: { code: 'FORBIDDEN', message: 'Platform denied access' } }),
  })));
  await expect(api('/restaurants')).rejects.toMatchObject({
    status: 403, message: expect.stringContaining('Databricks sign-in'),
  });
});
