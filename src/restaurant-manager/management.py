"""Restaurant-scoped menu, floor layout, and server assignment endpoints."""

import re
from decimal import Decimal, InvalidOperation

from flask import abort, jsonify, request

from database import FULL_SCHEMA, run_sql

MAX_CAPACITY = 30


def positive_integer(value, label, maximum=2**63 - 1):
    if not re.fullmatch(r'[1-9][0-9]{0,18}', str(value)) or int(value) > maximum:
        abort(400, description=f'{label} must be a whole number between 1 and {maximum}.')
    return int(value)


def menu_values(data):
    def text(name, maximum, required=False):
        value = data.get(name, '')
        if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
            abort(400, description=f'Enter a valid {name} (at most {maximum} characters).')
        return value.strip()

    name = text('name', 120, required=True)
    description = text('description', 1000)
    category = text('category', 80)
    try:
        price = Decimal(str(data.get('price', '')))
        if not price.is_finite() or price < 0 or price > Decimal('999999.99') or price != price.quantize(Decimal('.01')):
            raise ValueError
    except (InvalidOperation, ValueError):
        abort(400, description='Price must be between 0 and 999999.99, with at most two decimal places.')
    available = data.get('available', True)
    if not isinstance(available, bool):
        abort(400, description='Availability must be true or false.')
    return dict(name=name, description=description, category=category,
                price=format(price, '.2f'), available='true' if available else 'false')


def register_management(app, current_employee):
    def employee(manager=False):
        user = current_employee()
        if manager and user['role'] != 'manager':
            abort(403, description='Manager access is required for this action.')
        return user

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description='Submit a JSON object.')
        return data

    def scope(user, **values):
        return dict(restaurant_id=int(user['restaurant_id']), **values)

    def table_for(user, table_id):
        table_id = positive_integer(table_id, 'Table ID')
        rows = run_sql(f'''SELECT table_id, table_number, capacity, status
            FROM {FULL_SCHEMA}.restaurant_table
            WHERE table_id = :table_id AND restaurant_id = :restaurant_id''', scope(user, table_id=table_id))
        if not rows:
            abort(404, description='Table not found in your restaurant.')
        return rows[0]

    def menu_item_for(user, item_id):
        item_id = positive_integer(item_id, 'Menu item ID')
        if not run_sql(f'''SELECT menu_item_id FROM {FULL_SCHEMA}.menu_item
            WHERE menu_item_id = :item_id AND restaurant_id = :restaurant_id''', scope(user, item_id=item_id)):
            abort(404, description='Menu item not found in your restaurant.')
        return item_id

    def ensure_seats(table_id, capacity):
        # Values come from the bounded capacity, never from interpolated form text.
        numbers = ', '.join(f'({number})' for number in range(1, capacity + 1))
        run_sql(f'''INSERT INTO {FULL_SCHEMA}.seat (table_id, seat_number)
            SELECT :table_id, numbers.seat_number FROM VALUES {numbers} AS numbers(seat_number)
            WHERE NOT EXISTS (SELECT 1 FROM {FULL_SCHEMA}.seat existing
                WHERE existing.table_id = :table_id AND existing.seat_number = numbers.seat_number)''',
            {'table_id': int(table_id)})

    @app.get('/api/menu')
    def get_menu():
        user = employee()
        items = run_sql(f'''SELECT menu_item_id, name, description, price, category, available
            FROM {FULL_SCHEMA}.menu_item WHERE restaurant_id = :restaurant_id
            ORDER BY category, name''', scope(user))
        for item in items:
            item['available'] = str(item.get('available')).lower() == 'true'
            item['description'] = item.get('description') or ''
            item['category'] = item.get('category') or ''
        return jsonify(items=items)

    @app.post('/api/menu')
    def add_menu_item():
        user = employee(manager=True)
        values = menu_values(body())
        run_sql(f'''INSERT INTO {FULL_SCHEMA}.menu_item
            (restaurant_id, name, description, price, category, available)
            VALUES (:restaurant_id, :name, :description, CAST(:price AS DECIMAL(8,2)),
                :category, CAST(:available AS BOOLEAN))''', scope(user, **values))
        return jsonify(message='Menu item added.'), 201

    @app.put('/api/menu/<int:item_id>')
    def update_menu_item(item_id):
        user = employee(manager=True)
        values = menu_values(body())
        menu_item_for(user, item_id)
        run_sql(f'''UPDATE {FULL_SCHEMA}.menu_item
            SET name = :name, description = :description, price = CAST(:price AS DECIMAL(8,2)),
                category = :category, available = CAST(:available AS BOOLEAN)
            WHERE menu_item_id = :item_id AND restaurant_id = :restaurant_id''',
            scope(user, item_id=item_id, **values))
        return jsonify(message='Menu item updated.')

    @app.delete('/api/menu/<int:item_id>')
    def delete_menu_item(item_id):
        user = employee(manager=True)
        menu_item_for(user, item_id)
        if run_sql(f'SELECT 1 FROM {FULL_SCHEMA}.seat_order_item WHERE menu_item_id = :item_id LIMIT 1', {'item_id': item_id}):
            abort(409, description='This item has orders. Mark it unavailable instead of deleting it.')
        run_sql(f'''DELETE FROM {FULL_SCHEMA}.menu_item
            WHERE menu_item_id = :item_id AND restaurant_id = :restaurant_id''', scope(user, item_id=item_id))
        return jsonify(message='Menu item deleted.')

    @app.get('/api/tables')
    def get_tables():
        user = employee()
        tables = run_sql(f'''SELECT t.table_id, t.table_number, t.capacity, t.status,
            a.employee_id AS server_id, e.first_name AS server_first_name, e.last_name AS server_last_name
            FROM {FULL_SCHEMA}.restaurant_table t
            LEFT JOIN (SELECT table_id, employee_id,
                ROW_NUMBER() OVER (PARTITION BY table_id ORDER BY assigned_at DESC, assignment_id DESC) AS rn
                FROM {FULL_SCHEMA}.server_table_assignment WHERE status = 'active') a
                ON a.table_id = t.table_id AND a.rn = 1
            LEFT JOIN {FULL_SCHEMA}.employee e ON e.employee_id = a.employee_id AND e.restaurant_id = t.restaurant_id
            WHERE t.restaurant_id = :restaurant_id ORDER BY t.table_number''', scope(user))
        seats = run_sql(f'''SELECT s.seat_id, s.table_id, s.seat_number FROM {FULL_SCHEMA}.seat s
            JOIN {FULL_SCHEMA}.restaurant_table t ON s.table_id = t.table_id
            WHERE t.restaurant_id = :restaurant_id ORDER BY s.seat_number''', scope(user))
        servers = run_sql(f'''SELECT employee_id, first_name, last_name FROM {FULL_SCHEMA}.employee
            WHERE restaurant_id = :restaurant_id AND role = 'server' AND status = 'active'
            ORDER BY first_name, last_name''', scope(user))
        for table in tables:
            table['seats'] = [seat for seat in seats if str(seat['table_id']) == str(table['table_id'])]
        return jsonify(tables=tables, servers=servers)

    @app.post('/api/tables')
    def add_table():
        user = employee(manager=True)
        data = body()
        number = positive_integer(data.get('table_number'), 'Table number', 9999)
        capacity = positive_integer(data.get('capacity'), 'Capacity', MAX_CAPACITY)
        if run_sql(f'''SELECT 1 FROM {FULL_SCHEMA}.restaurant_table
            WHERE restaurant_id = :restaurant_id AND table_number = :table_number LIMIT 1''',
            scope(user, table_number=number)):
            abort(409, description='That table number is already in use at your restaurant.')
        run_sql(f'''INSERT INTO {FULL_SCHEMA}.restaurant_table (restaurant_id, table_number, capacity, status)
            VALUES (:restaurant_id, :table_number, :capacity, 'available')''',
            scope(user, table_number=number, capacity=capacity))
        rows = run_sql(f'''SELECT table_id FROM {FULL_SCHEMA}.restaurant_table
            WHERE restaurant_id = :restaurant_id AND table_number = :table_number ORDER BY table_id DESC LIMIT 1''',
            scope(user, table_number=number))
        if not rows:
            raise RuntimeError('Could not retrieve the new table.')
        table_id = int(rows[0]['table_id'])
        try:
            ensure_seats(table_id, capacity)
        except RuntimeError:
            # Remove the just-created table if no seats were created, so creation can be retried.
            run_sql(f'''DELETE FROM {FULL_SCHEMA}.restaurant_table
                WHERE table_id = :table_id AND restaurant_id = :restaurant_id
                AND NOT EXISTS (SELECT 1 FROM {FULL_SCHEMA}.seat WHERE table_id = :table_id)''',
                scope(user, table_id=table_id))
            raise
        return jsonify(message='Table and seats created.'), 201

    @app.put('/api/tables/<int:table_id>')
    def update_table(table_id):
        user = employee(manager=True)
        data = body()
        number = positive_integer(data.get('table_number'), 'Table number', 9999)
        capacity = positive_integer(data.get('capacity'), 'Capacity', MAX_CAPACITY)
        status = data.get('status')
        if status not in ('available', 'occupied', 'reserved'):
            abort(400, description='Choose available, occupied, or reserved.')
        table = table_for(user, table_id)
        if run_sql(f'''SELECT 1 FROM {FULL_SCHEMA}.restaurant_table
            WHERE restaurant_id = :restaurant_id AND table_number = :table_number AND table_id <> :table_id LIMIT 1''',
            scope(user, table_id=table_id, table_number=number)):
            abort(409, description='That table number is already in use at your restaurant.')
        if capacity < int(table['capacity']) and table['status'] != 'available':
            abort(409, description='Make the table available before reducing its capacity.')
        seats = run_sql(f'SELECT seat_id, seat_number FROM {FULL_SCHEMA}.seat WHERE table_id = :table_id ORDER BY seat_number', {'table_id': table_id})
        removing = seats[capacity:]
        if removing:
            if table['status'] != 'available':
                abort(409, description='Make the table available before removing seats.')
            ids = {f'seat_{i}': int(seat['seat_id']) for i, seat in enumerate(removing)}
            placeholders = ', '.join(':' + key for key in ids)
            if run_sql(f'SELECT 1 FROM {FULL_SCHEMA}.seat_order_item WHERE seat_id IN ({placeholders}) LIMIT 1', ids):
                abort(409, description='Seats with order history cannot be removed. Keep a larger capacity.')
        if status == 'available':
            if run_sql(f'''SELECT 1 FROM {FULL_SCHEMA}.seat_order_item o
                JOIN {FULL_SCHEMA}.seat s ON o.seat_id = s.seat_id
                WHERE s.table_id = :table_id AND o.status NOT IN ('paid', 'cancelled') LIMIT 1''', {'table_id': table_id}):
                abort(409, description='This table still has active orders.')
            if run_sql(f'''SELECT 1 FROM {FULL_SCHEMA}.server_table_assignment
                WHERE table_id = :table_id AND status = 'active' LIMIT 1''', {'table_id': table_id}):
                abort(409, description='Remove the server assignment before making this table available.')
        if removing:
            run_sql(f'DELETE FROM {FULL_SCHEMA}.seat WHERE seat_id IN ({placeholders}) AND table_id = :table_id', dict(table_id=table_id, **ids))
        existing = {int(seat['seat_number']) for seat in seats[:capacity]}
        additions = [number for number in range(1, 100) if number not in existing][:max(0, capacity - len(seats))]
        if additions:
            numbers = ', '.join(f'({number})' for number in additions)
            run_sql(f'''INSERT INTO {FULL_SCHEMA}.seat (table_id, seat_number)
                SELECT :table_id, n.seat_number FROM VALUES {numbers} AS n(seat_number)
                WHERE NOT EXISTS (SELECT 1 FROM {FULL_SCHEMA}.seat s
                    WHERE s.table_id = :table_id AND s.seat_number = n.seat_number)''', {'table_id': table_id})
        run_sql(f'''UPDATE {FULL_SCHEMA}.restaurant_table
            SET table_number = :table_number, capacity = :capacity, status = :status
            WHERE table_id = :table_id AND restaurant_id = :restaurant_id''',
            scope(user, table_id=table_id, table_number=number, capacity=capacity, status=status))
        return jsonify(message='Table and seats updated.')

    @app.delete('/api/tables/<int:table_id>')
    def delete_table(table_id):
        user = employee(manager=True)
        table = table_for(user, table_id)
        if table['status'] != 'available':
            abort(409, description='Only available tables can be deleted.')
        if run_sql(f'''SELECT 1 FROM {FULL_SCHEMA}.seat_order_item o
            JOIN {FULL_SCHEMA}.seat s ON o.seat_id = s.seat_id WHERE s.table_id = :table_id LIMIT 1''', {'table_id': table_id}):
            abort(409, description='A table with order history cannot be deleted.')
        if run_sql(f'''SELECT 1 FROM {FULL_SCHEMA}.server_table_assignment
            WHERE table_id = :table_id AND status = 'active' LIMIT 1''', {'table_id': table_id}):
            abort(409, description='Remove the server assignment before deleting this table.')
        run_sql(f'DELETE FROM {FULL_SCHEMA}.seat WHERE table_id = :table_id', {'table_id': table_id})
        run_sql(f'DELETE FROM {FULL_SCHEMA}.server_table_assignment WHERE table_id = :table_id', {'table_id': table_id})
        run_sql(f'DELETE FROM {FULL_SCHEMA}.bill_plan WHERE table_id = :table_id', {'table_id': table_id})
        run_sql(f'''DELETE FROM {FULL_SCHEMA}.restaurant_table
            WHERE table_id = :table_id AND restaurant_id = :restaurant_id''', scope(user, table_id=table_id))
        return jsonify(message='Table deleted.')

    @app.put('/api/tables/<int:table_id>/assignment')
    def assign_server(table_id):
        user = employee(manager=True)
        server_id = positive_integer(body().get('employee_id'), 'Server ID')
        table_for(user, table_id)
        if not run_sql(f'''SELECT employee_id FROM {FULL_SCHEMA}.employee
            WHERE employee_id = :employee_id AND restaurant_id = :restaurant_id
            AND role = 'server' AND status = 'active' LIMIT 1''', scope(user, employee_id=server_id)):
            abort(400, description='Choose an active server from your restaurant.')
        # Insert first so a failed insert leaves the old assignment intact.
        run_sql(f'''INSERT INTO {FULL_SCHEMA}.server_table_assignment (table_id, employee_id, status)
            VALUES (:table_id, :employee_id, 'active')''', {'table_id': table_id, 'employee_id': server_id})
        run_sql(f'''UPDATE {FULL_SCHEMA}.server_table_assignment SET status = 'inactive'
            WHERE table_id = :table_id AND status = 'active' AND assignment_id < (
                SELECT MAX(assignment_id) FROM {FULL_SCHEMA}.server_table_assignment
                WHERE table_id = :table_id AND status = 'active')''', {'table_id': table_id})
        run_sql(f'''UPDATE {FULL_SCHEMA}.restaurant_table SET status = 'occupied'
            WHERE table_id = :table_id AND restaurant_id = :restaurant_id''', scope(user, table_id=table_id))
        return jsonify(message='Server assigned. Table marked occupied.')

    @app.delete('/api/tables/<int:table_id>/assignment')
    def unassign_server(table_id):
        user = employee(manager=True)
        table_for(user, table_id)
        run_sql(f'''UPDATE {FULL_SCHEMA}.server_table_assignment SET status = 'inactive'
            WHERE table_id = :table_id AND status = 'active' ''', {'table_id': table_id})
        return jsonify(message='Server assignment removed. Table status is unchanged.')

    def seats_for(table_id):
        return run_sql(f'SELECT seat_id, seat_number FROM {FULL_SCHEMA}.seat WHERE table_id = :table_id ORDER BY seat_number', {'table_id': table_id})

    def sync_capacity(user, table_id):
        run_sql(f'''MERGE INTO {FULL_SCHEMA}.restaurant_table AS target
            USING (SELECT CAST(COUNT(*) AS INT) AS seat_count FROM {FULL_SCHEMA}.seat
                WHERE table_id = :table_id) AS source
            ON target.table_id = :table_id AND target.restaurant_id = :restaurant_id
            WHEN MATCHED THEN UPDATE SET capacity = source.seat_count''', scope(user, table_id=table_id))

    @app.post('/api/tables/<int:table_id>/seats')
    def add_seat(table_id):
        user = employee(manager=True)
        table_for(user, table_id)
        number = positive_integer(body().get('seat_number'), 'Seat number', 99)
        seats = seats_for(table_id)
        if len(seats) >= MAX_CAPACITY:
            abort(409, description='A table can have at most 30 seats.')
        if any(int(seat['seat_number']) == number for seat in seats):
            abort(409, description='That seat number is already in use at this table.')
        run_sql(f'INSERT INTO {FULL_SCHEMA}.seat (table_id, seat_number) VALUES (:table_id, :seat_number)',
                dict(table_id=table_id, seat_number=number))
        sync_capacity(user, table_id)
        return jsonify(message='Seat added and table capacity updated.'), 201

    def unused_seat(user, table_id, seat_id):
        table = table_for(user, table_id)
        if table['status'] != 'available':
            abort(409, description='Make the table available before renumbering or removing seats.')
        seats = seats_for(table_id)
        if not any(str(seat['seat_id']) == str(seat_id) for seat in seats):
            abort(404, description='Seat not found at this table.')
        if run_sql(f'SELECT 1 FROM {FULL_SCHEMA}.seat_order_item WHERE seat_id = :seat_id LIMIT 1', {'seat_id': seat_id}):
            abort(409, description='Seats with order history cannot be removed or renumbered.')
        return seats

    @app.put('/api/tables/<int:table_id>/seats/<int:seat_id>')
    def edit_seat(table_id, seat_id):
        user = employee(manager=True)
        number = positive_integer(body().get('seat_number'), 'Seat number', 99)
        seats = unused_seat(user, table_id, seat_id)
        if any(int(seat['seat_number']) == number and str(seat['seat_id']) != str(seat_id) for seat in seats):
            abort(409, description='That seat number is already in use at this table.')
        run_sql(f'UPDATE {FULL_SCHEMA}.seat SET seat_number = :seat_number WHERE seat_id = :seat_id AND table_id = :table_id',
                dict(table_id=table_id, seat_id=seat_id, seat_number=number))
        return jsonify(message='Seat number updated.')

    @app.delete('/api/tables/<int:table_id>/seats/<int:seat_id>')
    def delete_seat(table_id, seat_id):
        user = employee(manager=True)
        seats = unused_seat(user, table_id, seat_id)
        if len(seats) <= 1:
            abort(409, description='Keep at least one seat at each table.')
        run_sql(f'DELETE FROM {FULL_SCHEMA}.seat WHERE seat_id = :seat_id AND table_id = :table_id', dict(table_id=table_id, seat_id=seat_id))
        sync_capacity(user, table_id)
        return jsonify(message='Seat removed and table capacity updated.')
