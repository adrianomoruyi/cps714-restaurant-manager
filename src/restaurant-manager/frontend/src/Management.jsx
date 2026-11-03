import { useState } from 'react';
import { useRestaurantResource } from './useRestaurantResource.js';

function Status({ value }) {
  return <span className={`badge ${['available', 'occupied', 'reserved'].includes(value) ? value : 'other'}`}><span className="dot" />{value}</span>;
}

function Field({ label, name, ...props }) {
  return <label className="field"><span>{label}</span><input name={name} {...props} /></label>;
}

export function Page({ title, subtitle, resource, children, canManage, viewNote = 'You have view access. A manager can make changes.' }) {
  return <main className="dashboard management-page">
    <div className="dashboard-heading"><div><div className="eyebrow">YOUR RESTAURANT WORKSPACE</div><h1>{title}</h1><p>{subtitle}</p></div><button className="button secondary" disabled={resource.loading || resource.busy} onClick={resource.refresh}>Refresh</button></div>
    {!canManage && <p className="view-note">{viewNote}</p>}
    {resource.notice && <p className="notice" role="status">{resource.notice}</p>}
    {resource.error && <p className="error" role="alert">{resource.error}</p>}
    {resource.loadError ? <div className="error" role="alert">{resource.loadError} <button type="button" className="text-button" onClick={resource.refresh}>Try again</button></div>
      : resource.loading ? <p className="panel-message" role="status">Loading {title.toLowerCase()}…</p>
      : children}
  </main>;
}

function DeleteButton({ label, busy, onDelete }) {
  const [confirming, setConfirming] = useState(false);
  if (!confirming) return <button className="button danger" type="button" disabled={busy} onClick={() => setConfirming(true)}>Delete</button>;
  return <span className="delete-confirm"><span>Delete {label}?</span><button className="button danger" type="button" disabled={busy} onClick={async () => { if (await onDelete()) setConfirming(false); }}>Confirm delete</button><button className="button secondary" type="button" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button></span>;
}

const money = value => new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' }).format(Number(value));

export function MenuPage({ auth, onLogout }) {
  const resource = useRestaurantResource('/menu', auth, onLogout);
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const manager = auth.user.role === 'manager';
  const items = resource.data?.items || [];

  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const data = Object.fromEntries(form);
    data.available = form.has('available');
    const success = await resource.save(editing ? `/menu/${editing.menu_item_id}` : '/menu', editing ? 'PUT' : 'POST', data);
    if (success) { setEditing(null); setAdding(false); }
  }

  return <Page title="Menu" subtitle="The dishes and drinks your team can offer." resource={resource} canManage={manager}>
    {manager && <div className="section-actions"><button className="button primary" disabled={resource.busy} onClick={() => { setEditing(null); setAdding(true); }}>Add menu item</button></div>}
    {manager && (adding || editing) && <section className="editor-card" aria-labelledby="menu-editor-heading">
      <h2 id="menu-editor-heading">{editing ? 'Edit menu item' : 'New menu item'}</h2>
      <form key={editing?.menu_item_id || 'new'} onSubmit={submit}>
        <fieldset disabled={resource.busy}>
          <div className="field-row"><Field label="Item name" name="name" maxLength={120} defaultValue={editing?.name || ''} required /><Field label="Category" name="category" maxLength={80} defaultValue={editing?.category || ''} /></div>
          <label className="field"><span>Description</span><textarea name="description" maxLength={1000} rows={3} defaultValue={editing?.description || ''} /></label>
          <div className="field-row"><Field label="Price (CAD)" name="price" type="number" min="0" max="999999.99" step="0.01" defaultValue={editing?.price ?? ''} required /><label className="checkbox-field"><input type="checkbox" name="available" defaultChecked={editing ? editing.available : true} />Available to order</label></div>
          <div className="form-actions"><button className="button primary">{resource.busy ? 'Saving…' : 'Save item'}</button><button className="button secondary" type="button" onClick={() => { setEditing(null); setAdding(false); }}>Cancel</button></div>
        </fieldset>
      </form>
    </section>}
    <section className="table-panel" aria-label="Menu items">
      {items.length === 0 ? <div className="panel-message empty"><h2>No menu items yet</h2><p>A manager can add the first item.</p></div>
        : <div className="table-scroll"><table><thead><tr><th scope="col">Item</th><th scope="col">Category</th><th scope="col">Price</th><th scope="col">Availability</th>{manager && <th scope="col">Actions</th>}</tr></thead><tbody>{items.map(item => <tr key={item.menu_item_id}><td><strong>{item.name}</strong><span className="item-description">{item.description}</span></td><td>{item.category || '—'}</td><td>{money(item.price)}</td><td><span className={`badge ${item.available ? 'available' : 'other'}`}>{item.available ? 'Available' : 'Unavailable'}</span></td>{manager && <td><div className="row-actions"><button className="button secondary" disabled={resource.busy} onClick={() => { setEditing(item); setAdding(false); }}>Edit</button><button className="button secondary" disabled={resource.busy} onClick={() => resource.save(`/menu/${item.menu_item_id}`, 'PUT', { ...item, available: !item.available })}>{item.available ? 'Mark unavailable' : 'Mark available'}</button><DeleteButton label={item.name} busy={resource.busy} onDelete={() => resource.save(`/menu/${item.menu_item_id}`, 'DELETE')} /></div></td>}</tr>)}</tbody></table></div>}
    </section>
  </Page>;
}

export function TablesPage({ auth, onLogout }) {
  const resource = useRestaurantResource('/tables', auth, onLogout);
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const manager = auth.user.role === 'manager';
  const tables = resource.data?.tables || [];

  async function submit(event) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (await resource.save(editing ? `/tables/${editing.table_id}` : '/tables', editing ? 'PUT' : 'POST', data)) {
      setEditing(null); setAdding(false);
    }
  }

  return <Page title="Tables & seats" subtitle="Organize the floor and keep table availability up to date." resource={resource} canManage={manager}>
    {manager && <div className="section-actions"><button className="button primary" disabled={resource.busy} onClick={() => { setEditing(null); setAdding(true); }}>Add table</button></div>}
    {manager && (adding || editing) && <section className="editor-card" aria-labelledby="table-editor-heading">
      <h2 id="table-editor-heading">{editing ? `Edit table ${editing.table_number}` : 'New table'}</h2>
      <p className="editor-help">Capacity creates numbered seats automatically. Reducing it removes the highest numbered seats; seats with orders are kept.</p>
      <form key={editing?.table_id || 'new'} onSubmit={submit}><fieldset disabled={resource.busy}>
        <div className="field-row"><Field label="Table number" name="table_number" type="number" min="1" max="9999" step="1" defaultValue={editing?.table_number || ''} required /><Field label="Capacity" name="capacity" type="number" min="1" max="30" step="1" defaultValue={editing?.capacity || 4} required /></div>
        {editing && <label className="field"><span>Status</span><select name="status" defaultValue={editing.status}><option value="available">Available</option><option value="occupied">Occupied</option><option value="reserved">Reserved</option></select></label>}
        <div className="form-actions"><button className="button primary">{resource.busy ? 'Saving…' : 'Save table'}</button><button className="button secondary" type="button" onClick={() => { setEditing(null); setAdding(false); }}>Cancel</button></div>
      </fieldset></form>
    </section>}
    {tables.length === 0 ? <section className="table-panel panel-message empty"><h2>No tables yet</h2><p>A manager can create a table and its seats.</p></section>
      : <section className="floor-grid" aria-label="Restaurant floor">{tables.map(table => <article className="floor-card" key={table.table_id} aria-label={`Table ${table.table_number}`}>
        <div className="floor-card-heading"><h2>Table {table.table_number}</h2><Status value={table.status} /></div>
        <p>{table.capacity} seats · {table.server_first_name ? `${table.server_first_name} ${table.server_last_name || ''}`.trim() : 'Unassigned'}</p>
        <div className="seat-list" aria-label={`Seats at table ${table.table_number}`}>{table.seats.map(seat => <span className="seat-chip" key={seat.seat_id}>Seat {seat.seat_number}</span>)}{table.seats.length === 0 && <span className="muted">No seats configured. Edit and save capacity to create them.</span>}</div>
        {manager && <div className="row-actions"><button className="button secondary" disabled={resource.busy} onClick={() => { setEditing(table); setAdding(false); }}>Edit table</button><DeleteButton label={`table ${table.table_number}`} busy={resource.busy} onDelete={() => resource.save(`/tables/${table.table_id}`, 'DELETE')} /></div>}
      </article>)}</section>}
  </Page>;
}

export function AssignmentsPage({ auth, onLogout }) {
  const resource = useRestaurantResource('/tables', auth, onLogout);
  const manager = auth.user.role === 'manager';
  const tables = resource.data?.tables || [];
  const servers = resource.data?.servers || [];

  async function submit(event, table) {
    event.preventDefault();
    const employee_id = new FormData(event.currentTarget).get('employee_id');
    await resource.save(`/tables/${table.table_id}/assignment`, 'PUT', { employee_id });
  }

  return <Page title="Server assignments" subtitle="Give each table a clear point of contact." resource={resource} canManage={manager}>
    {manager && <p className="view-note">Assigning a server marks the table occupied. Removing an assignment keeps its status; update availability under Tables & seats when service is finished.</p>}
    {manager && servers.length === 0 && <p className="notice">No active servers are available. Register a server account for this restaurant to make an assignment.</p>}
    <section className="table-panel" aria-label="Server assignments">
      {tables.length === 0 ? <div className="panel-message empty"><h2>No tables to assign</h2><p>Create tables under Tables & seats first.</p></div>
        : <div className="table-scroll"><table><thead><tr><th scope="col">Table</th><th scope="col">Status</th><th scope="col">Assigned server</th>{manager && <th scope="col">Manage assignment</th>}</tr></thead><tbody>{tables.map(table => <tr key={table.table_id}><td>Table {table.table_number}</td><td><Status value={table.status} /></td><td>{table.server_first_name ? `${table.server_first_name} ${table.server_last_name || ''}`.trim() : 'Unassigned'}</td>{manager && <td><form key={`${table.table_id}-${table.server_id || 'none'}`} className="assignment-form" onSubmit={event => submit(event, table)}><select name="employee_id" aria-label={`Server for table ${table.table_number}`} defaultValue={table.server_id || ''} required disabled={resource.busy || !servers.length}><option value="" disabled>Choose server</option>{servers.map(server => <option key={server.employee_id} value={server.employee_id}>{server.first_name} {server.last_name}</option>)}</select><button className="button primary" disabled={resource.busy || !servers.length}>{table.server_id ? 'Reassign' : 'Assign'}</button>{table.server_id && <button className="button secondary" type="button" disabled={resource.busy} onClick={() => resource.save(`/tables/${table.table_id}/assignment`, 'DELETE')}>Remove assignment</button>}</form></td>}</tr>)}</tbody></table></div>}
    </section>
  </Page>;
}
