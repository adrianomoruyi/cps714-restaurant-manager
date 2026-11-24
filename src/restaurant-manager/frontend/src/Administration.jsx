import { useState } from 'react';
import { DeleteButton, Field, Page } from './Management.jsx';
import { useRestaurantResource } from './useRestaurantResource.js';

const roles = ['server', 'manager'];

export function EmployeesPage({ auth, onLogout }) {
  const resource = useRestaurantResource('/employees', auth, onLogout);
  const [editor, setEditor] = useState(null);
  const employees = resource.data?.employees || [];

  async function submit(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (await resource.save(editor.employee_id ? `/employees/${editor.employee_id}` : '/employees', editor.employee_id ? 'PUT' : 'POST', values)) setEditor(null);
  }

  return <Page title="Employees" subtitle="Manage your restaurant’s team and account access." resource={resource} canManage>
    <div className="section-actions"><button className="button primary" disabled={resource.busy} onClick={() => setEditor({})}>Add employee</button></div>
    {editor && <section className="editor-card" aria-labelledby="employee-heading">
      <h2 id="employee-heading">{editor.employee_id ? 'Edit employee' : 'New employee'}</h2>
      <p className="editor-help">Deactivate employees to keep their history. Leave an existing employee’s password blank to keep it. Your own login, role, and active status must be changed by another manager.</p>
      <form key={editor.employee_id || 'new'} onSubmit={submit}><fieldset disabled={resource.busy}>
        <div className="field-row"><Field label="First name" name="first_name" maxLength={100} defaultValue={editor.first_name || ''} required /><Field label="Last name" name="last_name" maxLength={100} defaultValue={editor.last_name || ''} required /></div>
        <div className="field-row"><Field label="Username" name="username" minLength={3} maxLength={64} defaultValue={editor.username || ''} required /><Field label={editor.employee_id ? 'New password (optional)' : 'Password'} name="password" type="password" autoComplete="new-password" maxLength={128} required={!editor.employee_id} /></div>
        <div className="field-row"><label className="field"><span>Role</span><select name="role" defaultValue={editor.role || 'server'}>{roles.map(role => <option key={role} value={role}>{role}</option>)}</select></label><label className="field"><span>Account status</span><select name="status" defaultValue={editor.status || 'active'}><option value="active">Active</option><option value="inactive">Inactive</option></select></label></div>
        <div className="form-actions"><button className="button primary">Save employee</button><button className="button secondary" type="button" onClick={() => setEditor(null)}>Cancel</button></div>
      </fieldset></form>
    </section>}
    <section className="table-panel" aria-label="Employee accounts">
      {!employees.length ? <p className="panel-message">No employees yet. Add the restaurant’s first team member.</p> : <div className="table-scroll"><table><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>{employees.map(employee => <tr key={employee.employee_id}><td>{employee.first_name} {employee.last_name}</td><td>{employee.username || 'No login configured'}</td><td>{employee.role}</td><td><span className={`badge ${employee.status === 'active' ? 'available' : 'other'}`}>{employee.status}</span></td><td><div className="row-actions"><button className="button secondary" disabled={resource.busy} onClick={() => setEditor(employee)}>Edit employee</button>{String(employee.employee_id) !== String(auth.user.employee_id) && <DeleteButton label={`${employee.first_name} ${employee.last_name}`} busy={resource.busy} onDelete={() => resource.save(`/employees/${employee.employee_id}`, 'DELETE')} />}</div></td></tr>)}</tbody></table></div>}
    </section>
  </Page>;
}

export function RestaurantsPage({ auth, onLogout }) {
  const resource = useRestaurantResource('/restaurant', auth, onLogout);
  const [editor, setEditor] = useState(null);
  const restaurant = resource.data?.restaurant;

  async function submit(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (await resource.save(editor.restaurant_id ? `/restaurants/${editor.restaurant_id}` : '/restaurants', editor.restaurant_id ? 'PUT' : 'POST', values)) setEditor(null);
  }

  return <Page title="Restaurant settings" subtitle="Maintain your restaurant’s contact details." resource={resource} canManage>
    <p className="view-note">You manage the restaurant associated with your account. You can also create a restaurant for a new team; its members select it when registering.</p>
    <div className="section-actions"><button className="button primary" disabled={resource.busy} onClick={() => setEditor({})}>Add restaurant</button></div>
    {editor && <section className="editor-card" aria-labelledby="restaurant-heading"><h2 id="restaurant-heading">{editor.restaurant_id ? 'Edit restaurant' : 'New restaurant'}</h2>
      <form key={editor.restaurant_id || 'new'} onSubmit={submit}><fieldset disabled={resource.busy}>
        <Field label="Restaurant name" name="name" maxLength={120} defaultValue={editor.name || ''} required />
        <Field label="Address" name="address" maxLength={300} defaultValue={editor.address || ''} />
        <Field label="Phone" name="phone" type="tel" maxLength={40} defaultValue={editor.phone || ''} />
        <div className="form-actions"><button className="button primary">Save restaurant</button><button className="button secondary" type="button" onClick={() => setEditor(null)}>Cancel</button></div>
      </fieldset></form>
    </section>}
    {restaurant && <section className="table-panel" aria-label="Your restaurant"><div className="table-scroll"><table><thead><tr><th>Restaurant</th><th>Address</th><th>Phone</th><th>Actions</th></tr></thead><tbody><tr><td>{restaurant.name}</td><td>{restaurant.address || '—'}</td><td>{restaurant.phone || '—'}</td><td><button className="button secondary" disabled={resource.busy} onClick={() => setEditor(restaurant)}>Edit restaurant</button></td></tr></tbody></table></div></section>}
  </Page>;
}
