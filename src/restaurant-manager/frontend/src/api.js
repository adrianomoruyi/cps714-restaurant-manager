export async function api(path, { credentials, ...options } = {}) {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (credentials) {
    const bytes = new TextEncoder().encode(`${credentials.username}:${credentials.password}`);
    headers.set('Authorization', `Basic ${btoa(String.fromCharCode(...bytes))}`);
  }
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'omit' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'Something went wrong. Please try again.');
    error.status = response.status;
    throw error;
  }
  return data;
}
