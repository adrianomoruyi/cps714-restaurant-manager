import { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';

function Mark() {
  return <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M5 3v5a3 3 0 0 0 6 0V3M8 3v18M19 21V3c-4 2-5 7-3 10h3" /></svg></span>;
}

function Field({ label, name, ...props }) {
  return <label className="field" htmlFor={name}><span>{label}</span><input id={name} name={name} {...props} /></label>;
}

function Login({ onLogin, navigate, notice, initialUsername }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const credentials = { username: form.get('username').trim(), password: form.get('password') };
    setError('');
    setBusy(true);
    try {
      const { user } = await api('/login', { method: 'POST', body: JSON.stringify(credentials) });
      onLogin({ user, credentials });
    } catch (error) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <div className="eyebrow">WELCOME BACK</div>
    <h1>Ready for the day?</h1>
    <p className="form-intro">Log in to see how your restaurant is looking.</p>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <form onSubmit={submit}>
      <Field label="Username" name="username" autoComplete="username" maxLength={64} defaultValue={initialUsername} required />
      <Field label="Password" name="password" type="password" autoComplete="current-password" maxLength={128} required />
      <button className="button primary full" disabled={busy}>{busy ? 'Logging in…' : 'Log in'}<span aria-hidden="true">→</span></button>
    </form>
    <p className="form-footer">New to the team? <a href="/register" onClick={event => { event.preventDefault(); navigate('/register'); }}>Create an account</a></p>
  </>;
}

function Register({ onCreated, navigate }) {
  const [restaurants, setRestaurants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError('');
    api('/restaurants', { signal: controller.signal })
      .then(data => setRestaurants(data.restaurants))
      .catch(error => { if (error.name !== 'AbortError') setLoadError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);

  async function submit(event) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    setError('');
    setBusy(true);
    try {
      const result = await api('/register', { method: 'POST', body: JSON.stringify(data) });
      onCreated(data.username.trim().toLowerCase(), result.message);
    } catch (error) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <div className="eyebrow">JOIN YOUR TEAM</div>
    <h1>A seat at the table.</h1>
    <p className="form-intro">Create your account to get started.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {loadError && <div className="error" role="alert">{loadError} <button type="button" className="text-button" onClick={() => setAttempt(value => value + 1)}>Try again</button></div>}
    {!loading && !loadError && restaurants.length === 0 && <p className="notice" role="status">No restaurants are available yet. Ask your project team to add one to the database.</p>}
    <form onSubmit={submit}>
      <div className="field-row">
        <Field label="First name" name="first_name" autoComplete="given-name" maxLength={100} required />
        <Field label="Last name" name="last_name" autoComplete="family-name" maxLength={100} required />
      </div>
      <div className="field-row">
        <label className="field" htmlFor="restaurant_id"><span>Restaurant</span>
          <select id="restaurant_id" name="restaurant_id" defaultValue="" disabled={loading || !!loadError} required>
            <option value="" disabled>{loading ? 'Loading restaurants…' : 'Select restaurant'}</option>
            {restaurants.map(restaurant => <option key={restaurant.restaurant_id} value={restaurant.restaurant_id}>{restaurant.name}</option>)}
          </select>
        </label>
        <label className="field" htmlFor="role"><span>Role</span><select id="role" name="role" defaultValue="server"><option value="server">Server</option><option value="manager">Manager</option></select></label>
      </div>
      <Field label="Username" name="username" autoComplete="username" minLength={3} maxLength={64} pattern="[a-zA-Z0-9_.\-]{3,64}" title="3–64 letters, numbers, dots, underscores, or hyphens" required />
      <Field label="Password" name="password" type="password" autoComplete="new-password" maxLength={128} required />
      <button className="button primary full" disabled={busy || loading || !!loadError || !restaurants.length}>{busy ? 'Creating account…' : 'Create account'}<span aria-hidden="true">→</span></button>
    </form>
    <p className="form-footer">Already on the team? <a href="/login" onClick={event => { event.preventDefault(); navigate('/login'); }}>Log in</a></p>
  </>;
}

function Dashboard({ auth, onLogout }) {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    api('/dashboard', { credentials: auth.credentials, signal: controller.signal })
      .then(data => setTables(data.tables))
      .catch(error => {
        if (error.name === 'AbortError') return;
        if (error.status === 401 || error.status === 403) onLogout(error.message);
        else setError(error.message);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [auth, refresh, onLogout]);

  const stats = [
    { label: 'Total tables', value: tables.length, color: 'neutral' },
    { label: 'Available', value: tables.filter(table => table.status === 'available').length, color: 'green' },
    { label: 'Occupied', value: tables.filter(table => table.status === 'occupied').length, color: 'orange' },
    { label: 'Reserved', value: tables.filter(table => table.status === 'reserved').length, color: 'purple' },
  ];

  return <div className="dashboard-shell">
    <header className="topbar"><a className="brand" href="/dashboard" onClick={event => event.preventDefault()}><Mark />Restaurant Manager</a>
      <div className="account"><div className="account-info"><strong>{auth.user.first_name} {auth.user.last_name}</strong><span>{auth.user.role}</span></div><span className="avatar" aria-hidden="true">{auth.user.first_name?.charAt(0)}</span><button className="button secondary" onClick={() => onLogout()}>Log out</button></div>
    </header>
    <main className="dashboard">
      <div className="dashboard-heading"><div><div className="eyebrow">YOUR RESTAURANT AT A GLANCE</div><h1>Hello, {auth.user.first_name}.</h1><p>Here’s what’s happening on the floor.</p></div><span className="page-label"><span className="dot" />Dashboard</span></div>
      <section className="stats" aria-label="Table overview">{stats.map(stat => <div className={`stat ${stat.color}`} key={stat.label}><span>{stat.label}</span><strong>{loading || error ? '—' : stat.value}</strong><span className="stat-line" /></div>)}</section>
      <section className="table-panel" aria-labelledby="tables-heading" aria-busy={loading}>
        <div className="panel-heading"><div><h2 id="tables-heading">Restaurant tables</h2><p>Table status and server assignments.</p></div><button className="button secondary" disabled={loading} onClick={() => setRefresh(value => value + 1)}><span aria-hidden="true">↻</span>{loading ? 'Loading…' : 'Refresh'}</button></div>
        {error ? <div className="panel-message error" role="alert">{error}</div>
          : loading ? <p className="panel-message" role="status">Loading your restaurant’s tables…</p>
          : tables.length === 0 ? <div className="panel-message empty"><h3>No tables yet</h3><p>Your restaurant’s tables will appear here once they’re added to the database.</p></div>
          : <div className="table-scroll"><table><thead><tr><th scope="col">Table</th><th scope="col">Capacity</th><th scope="col">Status</th><th scope="col">Assigned server</th></tr></thead><tbody>{tables.map(table => <tr key={table.table_id}><td><span className="table-number">{table.table_number}</span>Table {table.table_number}</td><td>{table.capacity} seats</td><td><span className={`badge ${['available', 'occupied', 'reserved'].includes(table.status) ? table.status : 'other'}`}><span className="dot" />{table.status}</span></td><td>{table.server_name || <span className="muted">Unassigned</span>}</td></tr>)}</tbody></table></div>}
        <div className="panel-footer">Restaurant overview<span>Read only</span></div>
      </section>
      <footer className="dashboard-footer">Restaurant Manager<span>A little clarity for a busy floor.</span></footer>
    </main>
  </div>;
}

export default function App() {
  const [page, setPage] = useState(window.location.pathname);
  const [auth, setAuth] = useState(null);
  const [notice, setNotice] = useState('');
  const [username, setUsername] = useState('');

  function navigate(path, replace = false) {
    window.history[replace ? 'replaceState' : 'pushState']({}, '', path);
    setPage(path);
  }

  useEffect(() => {
    const onPopState = () => setPage(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    if (!auth && (page === '/dashboard' || page === '/')) navigate('/login', true);
    if (auth && page !== '/dashboard') navigate('/dashboard', true);
  }, [auth, page]);

  // A stable callback keeps unrelated renders from restarting dashboard requests.
  const logout = useCallback((message = '') => {
    setAuth(null);
    setNotice(message);
    window.history.replaceState({}, '', '/login');
    setPage('/login');
  }, []);

  if (auth) return <Dashboard auth={auth} onLogout={logout} />;
  return <div className="auth-shell">
    <aside className="welcome-panel"><div className="brand"><Mark />Restaurant Manager</div><div className="welcome-copy"><div className="eyebrow">GOOD SERVICE STARTS HERE</div><h2>Your team.<br />Your tables.<br /><em>All together.</em></h2><p>A clear view of your restaurant,<br />so you can focus on your guests.</p><div className="floor-art" aria-hidden="true"><div className="floor-table one"><span /><span /><b>01</b><span /><span /></div><div className="floor-table two"><span /><span /><b>02</b><span /><span /></div><div className="floor-table three"><span /><span /><b>03</b><span /><span /></div></div></div><span className="welcome-footer">A little clarity for a busy floor.</span></aside>
    <main className="auth-main"><div className="mobile-brand brand"><Mark />Restaurant Manager</div><div className="auth-form">
      {page === '/register' ? <Register navigate={navigate} onCreated={(username, message) => { setUsername(username); setNotice(message); navigate('/login'); }} />
        : <Login navigate={navigate} notice={notice} initialUsername={username} onLogin={auth => { setAuth(auth); setNotice(''); navigate('/dashboard'); }} />}
    </div><span className="auth-footer">Restaurant Manager · Team workspace</span></main>
  </div>;
}
