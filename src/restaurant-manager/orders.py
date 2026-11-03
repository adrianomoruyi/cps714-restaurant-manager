"""Seat-level ordering, with restaurant and table-assignment permissions."""

from flask import abort, jsonify, request

from database import FULL_SCHEMA, run_sql
from management import positive_integer

ACTIVE_STATUSES = ('pending', 'preparing', 'served')
NEXT_STATUS = {'pending': 'preparing', 'preparing': 'served'}


def normalize_status(status):
    # The reference notebooks used 'ordered' before the schema adopted 'pending'.
    return 'pending' if status == 'ordered' else status


def order_changes(order, data):
    """Validate edits without allowing paid/cancelled orders to be reopened."""
    if not data or set(data) - {'quantity', 'status'}:
        abort(400, description='Provide quantity or status. Other order fields cannot be changed.')
    status = normalize_status(order['status'])
    if status not in ACTIVE_STATUSES:
        abort(409, description='This order is closed or has an unsupported status and cannot be changed.')
    quantity = int(order['quantity'])
    if 'quantity' in data:
        if status != 'pending':
            abort(409, description='Quantity can only be changed while an order is pending.')
        quantity = positive_integer(data['quantity'], 'Quantity', 99)
    if 'status' in data:
        target = data['status']
        if target not in ('pending', 'preparing', 'served', 'cancelled'):
            abort(400, description='Choose a valid order status. Payment is handled at checkout.')
        if target not in (status, NEXT_STATUS.get(status), 'cancelled'):
            abort(409, description='Orders must progress from pending to preparing to served.')
        status = target
    return {'quantity': quantity, 'status': status}


def register_orders(app, current_employee):
    def scope(user, **values):
        return dict(restaurant_id=int(user['restaurant_id']), **values)

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description='Submit a JSON object.')
        return data

    def require_order_role(user):
        if user['role'] not in ('manager', 'server'):
            abort(403, description='Only managers and servers can manage orders.')

    def require_table_access(user, table_id):
        if user['role'] == 'manager':
            return
        assignments = run_sql(f'''SELECT employee_id FROM {FULL_SCHEMA}.server_table_assignment
            WHERE table_id = :table_id AND status = 'active'
            ORDER BY assigned_at DESC, assignment_id DESC LIMIT 1''', {'table_id': int(table_id)})
        if not assignments or str(assignments[0]['employee_id']) != str(user['employee_id']):
            abort(403, description='You can only manage orders for tables assigned to you.')

    def can_manage(user, table):
        return user['role'] == 'manager' or (
            user['role'] == 'server' and str(table.get('server_id')) == str(user['employee_id']))

    @app.get('/api/orders')
    def get_orders():
        user = current_employee()
        tables = run_sql(f'''SELECT t.table_id, t.table_number, t.status, a.employee_id AS server_id
            FROM {FULL_SCHEMA}.restaurant_table t
            LEFT JOIN (SELECT table_id, employee_id,
                ROW_NUMBER() OVER (PARTITION BY table_id ORDER BY assigned_at DESC, assignment_id DESC) AS rn
                FROM {FULL_SCHEMA}.server_table_assignment WHERE status = 'active') a
                ON a.table_id = t.table_id AND a.rn = 1
            WHERE t.restaurant_id = :restaurant_id ORDER BY t.table_number''', scope(user))
        seats = run_sql(f'''SELECT s.seat_id, s.table_id, s.seat_number FROM {FULL_SCHEMA}.seat s
            JOIN {FULL_SCHEMA}.restaurant_table t ON t.table_id = s.table_id
            WHERE t.restaurant_id = :restaurant_id ORDER BY s.seat_number''', scope(user))
        items = run_sql(f'''SELECT menu_item_id, name, price, category FROM {FULL_SCHEMA}.menu_item
            WHERE restaurant_id = :restaurant_id AND available = true ORDER BY category, name''', scope(user))
        orders = run_sql(f'''SELECT o.seat_order_id, o.seat_id, o.menu_item_id, o.quantity, o.status, o.order_time,
            s.seat_number, t.table_id, t.table_number, COALESCE(m.name, 'Unavailable menu item') AS menu_item_name,
            m.price AS unit_price, (m.price * o.quantity) AS line_total
            FROM {FULL_SCHEMA}.seat_order_item o
            JOIN {FULL_SCHEMA}.seat s ON s.seat_id = o.seat_id
            JOIN {FULL_SCHEMA}.restaurant_table t ON t.table_id = s.table_id
            LEFT JOIN {FULL_SCHEMA}.menu_item m ON m.menu_item_id = o.menu_item_id AND m.restaurant_id = t.restaurant_id
            WHERE t.restaurant_id = :restaurant_id
            ORDER BY t.table_number, s.seat_number, o.order_time, o.seat_order_id''', scope(user))
        permissions = {}
        for table in tables:
            table['can_manage'] = can_manage(user, table)
            table['seats'] = [seat for seat in seats if str(seat['table_id']) == str(table['table_id'])]
            permissions[str(table['table_id'])] = table['can_manage']
        for order in orders:
            order['status'] = normalize_status(order['status'])
            order['can_manage'] = permissions.get(str(order['table_id']), False)
        return jsonify(tables=tables, items=items, orders=orders)

    @app.post('/api/orders')
    def add_order():
        user = current_employee()
        require_order_role(user)
        data = body()
        seat_id = positive_integer(data.get('seat_id'), 'Seat ID')
        item_id = positive_integer(data.get('menu_item_id'), 'Menu item ID')
        quantity = positive_integer(data.get('quantity', 1), 'Quantity', 99)
        seats = run_sql(f'''SELECT s.seat_id, t.table_id, t.status AS table_status
            FROM {FULL_SCHEMA}.seat s JOIN {FULL_SCHEMA}.restaurant_table t ON t.table_id = s.table_id
            WHERE s.seat_id = :seat_id AND t.restaurant_id = :restaurant_id''', scope(user, seat_id=seat_id))
        if not seats:
            abort(404, description='Seat not found in your restaurant.')
        table = seats[0]
        require_table_access(user, table['table_id'])
        if not run_sql(f'''SELECT menu_item_id FROM {FULL_SCHEMA}.menu_item
            WHERE menu_item_id = :item_id AND restaurant_id = :restaurant_id AND available = true''',
            scope(user, item_id=item_id)):
            abort(400, description='Choose an available menu item from your restaurant.')
        # Set occupancy first: a failed insert can be retried without duplicating an already-created order.
        if table['table_status'] != 'occupied':
            run_sql(f'''UPDATE {FULL_SCHEMA}.restaurant_table SET status = 'occupied'
                WHERE table_id = :table_id AND restaurant_id = :restaurant_id''',
                scope(user, table_id=int(table['table_id'])))
        run_sql(f'''INSERT INTO {FULL_SCHEMA}.seat_order_item (seat_id, menu_item_id, quantity, status)
            VALUES (:seat_id, :item_id, :quantity, 'pending')''',
            {'seat_id': seat_id, 'item_id': item_id, 'quantity': quantity})
        return jsonify(message='Order item added.'), 201

    @app.patch('/api/orders/<int:order_id>')
    def change_order(order_id):
        user = current_employee()
        require_order_role(user)
        order_id = positive_integer(order_id, 'Order ID')
        data = body()
        orders = run_sql(f'''SELECT o.seat_order_id, o.seat_id, o.quantity, o.status, t.table_id
            FROM {FULL_SCHEMA}.seat_order_item o
            JOIN {FULL_SCHEMA}.seat s ON s.seat_id = o.seat_id
            JOIN {FULL_SCHEMA}.restaurant_table t ON t.table_id = s.table_id
            WHERE o.seat_order_id = :order_id AND t.restaurant_id = :restaurant_id''', scope(user, order_id=order_id))
        if not orders:
            abort(404, description='Order not found in your restaurant.')
        order = orders[0]
        require_table_access(user, order['table_id'])
        changes = order_changes(order, data)
        changed = run_sql(f'''UPDATE {FULL_SCHEMA}.seat_order_item
            SET quantity = :quantity, status = :status
            WHERE seat_order_id = :order_id AND seat_id = :seat_id AND status = :previous_status
            AND seat_id IN (SELECT s.seat_id FROM {FULL_SCHEMA}.seat s
                JOIN {FULL_SCHEMA}.restaurant_table t ON t.table_id = s.table_id
                WHERE t.restaurant_id = :restaurant_id)''',
            scope(user, order_id=order_id, seat_id=int(order['seat_id']), previous_status=order['status'], **changes))
        if changed and str(changed[0].get('num_affected_rows', '1')) == '0':
            abort(409, description='This order changed while you were editing it. Refresh and try again.')
        message = 'Order item cancelled. History was kept.' if changes['status'] == 'cancelled' else 'Order item updated.'
        return jsonify(message=message)
