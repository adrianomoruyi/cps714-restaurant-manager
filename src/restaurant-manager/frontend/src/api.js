export async function api(path, { credentials, ...options } = {}) {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (credentials) {
    const bytes = new TextEncoder().encode(`${credentials.username}:${credentials.password}`);
    // Leave Authorization available to Databricks' authentication proxy.
    headers.set('X-Restaurant-Authorization', `Basic ${btoa(String.fromCharCode(...bytes))}`);
  }
  // Databricks requires its own existing sign-in cookie, even though our app
  // deliberately keeps employee login in React memory without Flask sessions.
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' });
  const data = await response.json().catch(() => null);
  if (!response.ok || response.redirected || !data || typeof data !== 'object' || Array.isArray(data)) {
    const appError = typeof data?.error === 'string' ? data.error : null;
    const accessDenied = response.status === 401 || response.status === 403;
    const fallback = accessDenied || response.redirected
      ? 'Your Databricks sign-in could not be verified. Refresh the page and sign in to Databricks again.'
      : `The server returned an unexpected response (HTTP ${response.status}). Please try again shortly.`;
    const error = new Error(appError || fallback);
    error.status = response.ok ? 502 : response.status;
    throw error;
  }
  return data;
}
