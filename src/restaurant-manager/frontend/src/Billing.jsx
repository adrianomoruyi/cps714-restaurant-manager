import { useEffect, useState } from 'react';
import { Field, Page } from './Management.jsx';
import { useRestaurantResource } from './useRestaurantResource.js';

const money = value => new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' }).format(Number(value));

export function BillsPage({ auth, onLogout, initialTableId = '' }) {
  const resource = useRestaurantResource('/tables', auth, onLogout);
  const [tableId, setTableId] = useState(String(initialTableId));
  const tables = resource.data?.tables || [];
  useEffect(() => {
    if (resource.data && tableId && !resource.data.tables.some(table => String(table.table_id) === tableId)) setTableId('');
  }, [resource.data, tableId]);
  return <Page title="Bills & splits" subtitle="See what each person owes and save how the bill is shared." resource={resource} canManage>
    <label className="field bill-table-picker"><span>Table for bill</span><select value={tableId} onChange={event => setTableId(event.target.value)}><option value="">Choose a table</option>{tables.map(table => <option key={table.table_id} value={table.table_id}>Table {table.table_number}</option>)}</select></label>
    {!tableId && <section className="table-panel panel-message">Choose a table to split its current orders by seat, group seats together, or divide the total equally.</section>}
    {tableId && <BillDetail key={tableId} tableId={tableId} auth={auth} onLogout={onLogout} />}
  </Page>;
}

function BillDetail({ tableId, auth, onLogout }) {
  const resource = useRestaurantResource(`/bills/${tableId}`, auth, onLogout);
  const [mode, setMode] = useState('seats');
  const [people, setPeople] = useState('2');
  const [groups, setGroups] = useState({});
  const bill = resource.data;
  const manager = bill?.can_discount ?? (auth.user.role === 'manager');
  const seats = [...new Map((bill?.items || []).map(item => [String(item.seat_id), item.seat_number])).entries()];

  useEffect(() => {
    if (!bill) return;
    setMode(bill.settings.mode);
    setPeople(String(bill.settings.people));
    const ids = [...new Set(bill.items.map(item => String(item.seat_id)))];
    setGroups(Object.fromEntries(ids.map((id, i) => {
      const group = bill.settings.groups.findIndex(group => group.map(String).includes(id));
      return [id, String(group >= 0 ? group + 1 : i + 1)];
    })));
  }, [bill]);

  async function saveSplit(event) {
    event.preventDefault();
    const grouped = [...new Set(seats.map(([id]) => groups[id]))].sort((a, b) => Number(a) - Number(b))
      .map(group => seats.filter(([id]) => groups[id] === group).map(([id]) => id));
    await resource.save(`/bills/${tableId}/split`, 'PUT', { mode, people, groups: mode === 'groups' ? grouped : [] });
  }

  async function saveDiscount(event) {
    event.preventDefault();
    await resource.save(`/bills/${tableId}/discount`, 'PUT', Object.fromEntries(new FormData(event.currentTarget)));
  }

  // Kept as a section so the page has one main landmark.
  if (resource.loading) return <p role="status" className="panel-message">Loading bill…</p>;
  if (resource.loadError) return <p role="alert" className="error">{resource.loadError} <button className="text-button" onClick={resource.refresh}>Try again</button></p>;
  if (!bill) return null;
  return <section aria-label={`Bill for table ${bill.table.table_number}`}>
    {resource.notice && <p className="notice" role="status">{resource.notice}</p>}
    {resource.error && <p className="error" role="alert">{resource.error}</p>}
    {bill.warning && <p className="notice">{bill.warning}</p>}
    {!bill.can_manage && <p className="view-note">View only. A manager or the assigned server can change this split.</p>}
    {!bill.items.length ? <p className="notice">This table has no current order items to bill.</p> : <>
      <div className="bill-summary" aria-label="Bill totals"><div><span>Subtotal</span><strong>{money(bill.subtotal)}</strong></div><div><span>Manager discount</span><strong>−{money(bill.discount_total)}</strong></div><div><span>Total to split</span><strong>{money(bill.total)}</strong></div></div>
      <div className="bill-editors">
        {bill.can_manage && <section className="editor-card"><h2>Split bill</h2><form onSubmit={saveSplit}><fieldset disabled={resource.busy}>
          <label className="field"><span>Split method</span><select value={mode} onChange={event => setMode(event.target.value)}><option value="seats">Separate bill for each seat</option><option value="groups">Group seats onto bills</option><option value="equal">Split equally</option></select></label>
          {mode === 'equal' && <Field label="Number of people" name="people" type="number" min="1" max="30" step="1" value={people} onChange={event => setPeople(event.target.value)} required />}
          {mode === 'groups' && <div className="seat-groups">{seats.map(([id, number]) => <label className="field" key={id}><span>Bill for seat {number}</span><select value={groups[id] || ''} onChange={event => setGroups({ ...groups, [id]: event.target.value })} required><option value="" disabled>Choose bill</option>{seats.map((_, i) => <option value={String(i + 1)} key={i}>Bill {i + 1}</option>)}</select></label>)}</div>}
          <button className="button primary">Calculate & save split</button>
        </fieldset></form></section>}
        {manager && <section className="editor-card"><h2>Manager discount</h2><form key={`${bill.settings.discount_kind}-${bill.settings.discount_value}-${bill.settings.discount_reason}`} onSubmit={saveDiscount}><fieldset disabled={resource.busy}>
          <label className="field"><span>Discount type</span><select name="kind" defaultValue={bill.settings.discount_kind}><option value="none">No discount</option><option value="percentage">Percentage (%)</option><option value="fixed">Fixed amount (CAD)</option></select></label>
          <Field label="Discount value" name="value" type="number" min="0" step="0.01" defaultValue={bill.settings.discount_value} required />
          <Field label="Discount reason" name="reason" maxLength={200} defaultValue={bill.settings.discount_reason} />
          <button className="button primary">Approve discount</button>
        </fieldset></form></section>}
      </div>
      {bill.settings.discount_reason && <p className="view-note">Approved discount: {bill.settings.discount_reason}</p>}
      <section aria-label="Amounts owed" className="bill-grid">{bill.bills.map((share, i) => <article className="floor-card bill-share" key={i} aria-label={share.label}><h2>{share.label}</h2>{share.seat_numbers.length > 0 && <p>Seat{share.seat_numbers.length > 1 ? 's' : ''} {share.seat_numbers.join(', ')}</p>}<dl><div><dt>Subtotal</dt><dd>{money(share.subtotal)}</dd></div><div><dt>Discount</dt><dd>−{money(share.discount)}</dd></div><div className="bill-due"><dt>Amount owed</dt><dd>{money(share.total)}</dd></div></dl></article>)}</section>
      <section className="table-panel" aria-label="Bill items"><div className="panel-heading"><h2>Items on this bill</h2></div><div className="table-scroll"><table><thead><tr><th>Seat</th><th>Item</th><th>Quantity</th><th>Unit price</th><th>Line total</th></tr></thead><tbody>{bill.items.map(item => <tr key={item.seat_order_id}><td>Seat {item.seat_number}</td><td>{item.menu_item_name}</td><td>{item.quantity}</td><td>{money(item.unit_price)}</td><td>{money(Number(item.unit_price) * Number(item.quantity))}</td></tr>)}</tbody></table></div></section>
      <p className="view-note">Amounts are in CAD and use current menu prices. Cancelled and paid items are excluded. Saved splits recalculate as orders change. No payments are collected.</p>
    </>}
  </section>;
}
