import { useEffect, useState } from 'react';
import { Page } from './Management.jsx';
import { useRestaurantResource } from './useRestaurantResource.js';

const ACTIVE_STATUSES = ['pending', 'preparing', 'served'];
const NEXT_STATUS = { pending: ['preparing', 'Start preparing'], preparing: ['served', 'Mark served'] };
const currency = new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' });
const money = value => value == null ? '—' : currency.format(Number(value));

function OrderRow({ order, resource }) {
  const [confirming, setConfirming] = useState(false);
  const editable = order.can_manage && ACTIVE_STATUSES.includes(order.status);
  const next = NEXT_STATUS[order.status];
  const label = `${order.menu_item_name}, table ${order.table_number}, seat ${order.seat_number}, order ${order.seat_order_id}`;
  const path = `/orders/${order.seat_order_id}`;

  async function changeQuantity(event) {
    event.preventDefault();
    const quantity = new FormData(event.currentTarget).get('quantity');
    await resource.save(path, 'PATCH', { quantity });
  }

  return <tr aria-label={label}>
    <td><strong>{order.menu_item_name}</strong><span className="item-description">Table {order.table_number} · Seat {order.seat_number}</span></td>
    <td>{editable && order.status === 'pending'
      ? <form className="quantity-form" key={`${order.quantity}-${order.status}`} onSubmit={changeQuantity}>
        <input aria-label={`Quantity for ${label}`} name="quantity" type="number" min="1" max="99" step="1" defaultValue={order.quantity} disabled={resource.busy} required />
        <button className="button secondary" disabled={resource.busy}>Save quantity</button>
      </form>
      : order.quantity}</td>
    <td>{money(order.unit_price)}</td>
    <td>{money(order.line_total)}</td>
    <td><span className={`badge order-status ${ACTIVE_STATUSES.includes(order.status) ? order.status : 'other'}`}><span className="dot" />{order.status || 'Unknown'}</span></td>
    <td>{editable ? <div className="row-actions">
      {next && <button className="button secondary" disabled={resource.busy} onClick={() => resource.save(path, 'PATCH', { status: next[0] })}>{next[1]}</button>}
      {confirming ? <span className="delete-confirm"><span>Cancel this item?</span><button className="button danger" disabled={resource.busy} onClick={async () => { if (await resource.save(path, 'PATCH', { status: 'cancelled' })) setConfirming(false); }}>Confirm cancellation</button><button className="button secondary" disabled={resource.busy} onClick={() => setConfirming(false)}>Keep item</button></span>
        : <button className="button danger" disabled={resource.busy} onClick={() => setConfirming(true)}>Cancel item</button>}
    </div> : <span className="muted">{ACTIVE_STATUSES.includes(order.status) ? 'View only' : 'Closed'}</span>}</td>
  </tr>;
}

export function OrdersPage({ auth, onLogout }) {
  const resource = useRestaurantResource('/orders', auth, onLogout);
  const [tableId, setTableId] = useState('');
  const [seatId, setSeatId] = useState('');
  const [itemId, setItemId] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [showHistory, setShowHistory] = useState(false);
  const tables = resource.data?.tables || [];
  const items = resource.data?.items || [];
  const table = tables.find(table => String(table.table_id) === tableId);
  const orders = (resource.data?.orders || []).filter(order =>
    (!tableId || String(order.table_id) === tableId) && (showHistory || ACTIVE_STATUSES.includes(order.status)));
  const orderRole = ['manager', 'server'].includes(auth.user.role);

  useEffect(() => {
    if (resource.data && tableId && !resource.data.tables.some(table => String(table.table_id) === tableId)) {
      setTableId('');
      setSeatId('');
    }
  }, [resource.data, tableId]);

  async function submit(event) {
    event.preventDefault();
    if (!table?.can_manage) return;
    if (await resource.save('/orders', 'POST', { seat_id: seatId, menu_item_id: itemId, quantity })) {
      setItemId('');
      setQuantity('1');
    }
  }

  return <Page title="Orders" subtitle="Take orders by seat and keep service moving." resource={resource}
    canManage={orderRole} viewNote="You have view access. A manager or the assigned server can manage orders.">
    <section className="order-filter" aria-label="Order filters">
      <label className="field"><span>Table</span><select value={tableId} onChange={event => { setTableId(event.target.value); setSeatId(''); }} disabled={resource.busy}>
        <option value="">All tables</option>
        {tables.map(table => <option key={table.table_id} value={table.table_id}>Table {table.table_number}{table.can_manage ? '' : ' (view only)'}</option>)}
      </select></label>
      <label className="checkbox-field"><input type="checkbox" checked={showHistory} onChange={event => setShowHistory(event.target.checked)} />Show cancelled and paid items</label>
    </section>
    {tables.length === 0 && <p className="notice">No tables are available yet. A manager can create them under Tables & seats.</p>}
    {!table && tables.length > 0 && orderRole && <p className="view-note">Choose a table to add an item. Managers can manage all tables; servers can manage their assigned tables.</p>}
    {table && !table.can_manage && <p className="view-note">Only a manager or this table’s assigned server can add or change its orders.</p>}
    {table?.can_manage && <section className="editor-card" aria-labelledby="new-order-heading">
      <h2 id="new-order-heading">Add an item to table {table.table_number}</h2>
      {table.seats.length === 0 && <p className="notice">This table has no seats. Ask a manager to save its capacity under Tables & seats.</p>}
      {items.length === 0 && <p className="notice">No available menu items. A manager can add or enable items under Menu.</p>}
      <form onSubmit={submit}><fieldset disabled={resource.busy}>
        <div className="order-fields">
          <label className="field"><span>Seat</span><select name="seat_id" value={seatId} onChange={event => setSeatId(event.target.value)} disabled={!table.seats.length} required>
            <option value="" disabled>Choose seat</option>{table.seats.map(seat => <option key={seat.seat_id} value={seat.seat_id}>Seat {seat.seat_number}</option>)}
          </select></label>
          <label className="field"><span>Menu item</span><select name="menu_item_id" value={itemId} onChange={event => setItemId(event.target.value)} disabled={!items.length} required>
            <option value="" disabled>Choose item</option>{items.map(item => <option key={item.menu_item_id} value={item.menu_item_id}>{item.name} · {money(item.price)}</option>)}
          </select></label>
          <label className="field"><span>Quantity</span><input name="quantity" type="number" min="1" max="99" step="1" value={quantity} onChange={event => setQuantity(event.target.value)} required /></label>
        </div>
        <button className="button primary" disabled={!table.seats.length || !items.length}>{resource.busy ? 'Adding…' : 'Add item'}</button>
      </fieldset></form>
    </section>}
    <section className="table-panel" aria-labelledby="order-list-heading">
      <div className="panel-heading"><div><h2 id="order-list-heading">{showHistory ? 'Order items & history' : 'Current order items'}</h2><p>{table ? `Table ${table.table_number}` : 'All tables'} · {orders.length} item{orders.length === 1 ? '' : 's'}</p></div></div>
      {orders.length === 0 ? <div className="panel-message empty"><h3>No order items to show</h3><p>{showHistory ? 'Items will appear here when an order is added.' : 'Add an item, choose another table, or show cancelled and paid items.'}</p></div>
        : <div className="table-scroll"><table><thead><tr><th scope="col">Item & seat</th><th scope="col">Quantity</th><th scope="col">Unit price</th><th scope="col">Line total</th><th scope="col">Status</th><th scope="col">Actions</th></tr></thead><tbody>{orders.map(order => <OrderRow key={order.seat_order_id} order={order} resource={resource} />)}</tbody></table></div>}
      <div className="panel-footer"><span>Prices reflect the current menu.</span><span>Cancelled and paid items remain in history.</span></div>
    </section>
  </Page>;
}
