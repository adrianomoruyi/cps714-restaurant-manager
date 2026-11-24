"""Saved bill splits and manager-approved discounts; no payment processing."""

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import abort, jsonify, request

from database import FULL_SCHEMA, run_sql
from management import positive_integer

DEFAULT_PLAN = dict(mode='seats', people=2, groups=[], discount_kind='none',
                    discount_value='0.00', discount_reason='', discount_employee_id=None)


def amount(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal('9999999999.99') or number != number.quantize(Decimal('.01')):
            raise ValueError
        return number
    except (InvalidOperation, ValueError):
        abort(400, description='Enter a non-negative amount with at most two decimal places.')


def money(cents):
    return format(Decimal(cents) / 100, '.2f')


def allocate(total, weights):
    """Allocate integer cents exactly, assigning remaining cents by largest remainder."""
    if not weights:
        return []
    denominator = sum(weights)
    if not denominator:
        weights = [1] * len(weights)
        denominator = len(weights)
    shares = [total * weight // denominator for weight in weights]
    remainders = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % denominator), i))
    for index in remainders[:total - sum(shares)]:
        shares[index] += 1
    return shares


def split_bill(items, plan):
    """Compute a bill in cents, excluding cancelled/paid items supplied by the query."""
    seats = {}
    subtotal = 0
    for item in items:
        if item.get('unit_price') is None:
            abort(409, description='An order item has no price. Restore its menu item before splitting the bill.')
        cents = int(amount(item['unit_price']) * 100) * int(item['quantity'])
        seat_id = str(item['seat_id'])
        seats.setdefault(seat_id, dict(seat_number=str(item['seat_number']), subtotal=0))['subtotal'] += cents
        subtotal += cents
    kind = plan.get('discount_kind', 'none')
    value = amount(plan.get('discount_value', '0.00'))
    if kind == 'percentage':
        if value > 100:
            abort(400, description='A percentage discount cannot exceed 100%.')
        discount = int((Decimal(subtotal) * value / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    elif kind == 'fixed':
        discount = min(subtotal, int(value * 100))
    elif kind == 'none':
        discount = 0
    else:
        abort(400, description='Choose no discount, a percentage, or a fixed amount.')

    mode = plan.get('mode', 'seats')
    groups = []
    if mode == 'seats':
        groups = [[seat_id] for seat_id in seats]
    elif mode == 'equal':
        people = positive_integer(plan.get('people'), 'Number of people', 30)
    elif mode == 'groups':
        raw_groups = plan.get('groups')
        if not isinstance(raw_groups, list) or len(raw_groups) > 30:
            abort(400, description='Choose groups of seats for the split.')
        seen = []
        for group in raw_groups:
            if not isinstance(group, list) or not group:
                abort(400, description='Each bill must contain at least one seat.')
            group = [str(positive_integer(seat, 'Seat ID')) for seat in group]
            groups.append(group)
            seen.extend(group)
        if len(seen) != len(set(seen)) or set(seen) != set(seats):
            abort(400, description='Assign every seat with current orders to exactly one bill.')
    else:
        abort(400, description='Choose a split by seat, an equal split, or grouped seats.')

    if mode == 'equal':
        subtotals = allocate(subtotal, [1] * people) if items else []
        # Allocate the final amount independently so equal shares differ by at most one cent.
        totals = allocate(subtotal - discount, [1] * people) if items else []
        discounts = [before - after for before, after in zip(subtotals, totals)]
        labels = [f'Person {i + 1}' for i in range(len(totals))]
        groups = [[] for _ in totals]
    else:
        subtotals = [sum(seats[seat]['subtotal'] for seat in group) for group in groups]
        discounts = allocate(discount, subtotals)
        totals = [before - reduction for before, reduction in zip(subtotals, discounts)]
        labels = [('Seat ' + seats[group[0]]['seat_number']) if mode == 'seats'
                  else f'Bill {i + 1}' for i, group in enumerate(groups)]
    bills = [dict(label=labels[i], seat_ids=group,
                  seat_numbers=[seats[seat]['seat_number'] for seat in group],
                  subtotal=money(subtotals[i]), discount=money(discounts[i]), total=money(totals[i]))
             for i, group in enumerate(groups)]
    return dict(subtotal=money(subtotal), discount_total=money(discount), total=money(subtotal - discount), bills=bills)


def register_billing(app, current_employee):
    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description='Submit a JSON object.')
        return data

    def context(table_id, edit=False, manager=False):
        user = current_employee()
        values = dict(table_id=table_id, restaurant_id=int(user['restaurant_id']))
        tables = run_sql(f'''SELECT table_id, table_number FROM {FULL_SCHEMA}.restaurant_table
            WHERE table_id = :table_id AND restaurant_id = :restaurant_id''', values)
        if not tables:
            abort(404, description='Table not found in your restaurant.')
        can_manage = user['role'] == 'manager'
        if user['role'] == 'server':
            assignments = run_sql(f'''SELECT employee_id FROM {FULL_SCHEMA}.server_table_assignment
                WHERE table_id = :table_id AND status = 'active'
                ORDER BY assigned_at DESC, assignment_id DESC LIMIT 1''', {'table_id': table_id})
            can_manage = bool(assignments and str(assignments[0]['employee_id']) == str(user['employee_id']))
        if manager and user['role'] != 'manager':
            abort(403, description='A manager must approve discounts.')
        if edit and not can_manage:
            abort(403, description='Only a manager or this table’s assigned server can change its bill.')
        return user, tables[0], values, can_manage

    def load(values):
        rows = run_sql(f'SELECT * FROM {FULL_SCHEMA}.bill_plan WHERE table_id = :table_id', {'table_id': values['table_id']})
        plan = DEFAULT_PLAN.copy()
        if rows:
            row = rows[0]
            plan.update({key: row[key] for key in ('people', 'discount_kind', 'discount_value',
                                                  'discount_reason', 'discount_employee_id') if row.get(key) is not None})
            plan['mode'] = row.get('split_mode') or 'seats'
            plan['groups'] = json.loads(row.get('groups_json') or '[]')
        items = run_sql(f'''SELECT o.seat_order_id, o.seat_id, s.seat_number, m.name AS menu_item_name,
            o.quantity, m.price AS unit_price
            FROM {FULL_SCHEMA}.seat_order_item o JOIN {FULL_SCHEMA}.seat s ON s.seat_id = o.seat_id
            JOIN {FULL_SCHEMA}.restaurant_table t ON t.table_id = s.table_id
            LEFT JOIN {FULL_SCHEMA}.menu_item m ON m.menu_item_id = o.menu_item_id AND m.restaurant_id = t.restaurant_id
            WHERE t.table_id = :table_id AND t.restaurant_id = :restaurant_id
            AND o.status IN ('pending', 'ordered', 'preparing', 'served')
            ORDER BY s.seat_number, o.seat_order_id''', values)
        return plan, items

    def save_plan(table_id, fields):
        # Column names come only from these internal callers. MERGE updates just the changed settings.
        columns = list(fields)
        expressions = {name: (f'CAST(:{name} AS DECIMAL(12,2))' if name == 'discount_value' else ':' + name) for name in columns}
        assignments = ', '.join(f'{name} = {expressions[name]}' for name in columns)
        insert_columns = ', '.join(['table_id', *columns, 'updated_at'])
        insert_values = ', '.join([':table_id', *(expressions[name] for name in columns), 'CURRENT_TIMESTAMP()'])
        run_sql(f'''MERGE INTO {FULL_SCHEMA}.bill_plan AS target
            USING (SELECT :table_id AS source_table_id) AS source ON target.table_id = source.source_table_id
            WHEN MATCHED THEN UPDATE SET {assignments}, updated_at = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})''',
            dict(table_id=table_id, **fields))

    @app.get('/api/bills/<int:table_id>')
    def get_bill(table_id):
        user, table, values, can_manage = context(table_id)
        plan, items = load(values)
        # New orders may introduce seats not present in a previously saved grouping.
        # Display a valid per-seat fallback and ask the user to save their new grouping.
        warning = ''
        if plan['mode'] == 'groups':
            grouped = [str(seat) for group in plan['groups'] for seat in group]
            if set(grouped) != {str(item['seat_id']) for item in items}:
                plan['mode'], plan['groups'] = 'seats', []
                warning = 'The ordered seats have changed. Review and save the split again.'
        return jsonify(table=table, settings=plan, items=items, can_manage=can_manage,
                       can_discount=user['role'] == 'manager', warning=warning, **split_bill(items, plan))

    @app.put('/api/bills/<int:table_id>/split')
    def save_split(table_id):
        _, _, values, _ = context(table_id, edit=True)
        data = body()
        if set(data) - {'mode', 'people', 'groups'}:
            abort(400, description='Only split settings can be changed here. A manager must approve discounts separately.')
        plan, items = load(values)
        plan.update(data)
        split_bill(items, plan)
        save_plan(table_id, dict(split_mode=plan['mode'], people=positive_integer(plan['people'], 'Number of people', 30),
                                 groups_json=json.dumps(plan['groups'] if plan['mode'] == 'groups' else [])))
        return jsonify(message='Bill split saved. The amounts below show what each person owes.')

    @app.put('/api/bills/<int:table_id>/discount')
    def save_discount(table_id):
        user, _, values, _ = context(table_id, edit=True, manager=True)
        data = body()
        kind = data.get('kind')
        value = amount(data.get('value', '0')) if kind != 'none' else Decimal('0')
        reason = data.get('reason', '')
        if not isinstance(reason, str) or len(reason.strip()) > 200 or (value > 0 and not reason.strip()):
            abort(400, description='Enter a discount reason of at most 200 characters.')
        plan, items = load(values)
        # Group settings may need review after new seats order; discount validation is independent.
        plan.update(mode='seats', discount_kind=kind, discount_value=format(value, '.2f'))
        split_bill(items, plan)
        save_plan(table_id, dict(discount_kind=kind, discount_value=format(value, '.2f'),
                                 discount_reason=reason.strip() if kind != 'none' else '',
                                 discount_employee_id=int(user['employee_id'])))
        return jsonify(message='Manager discount saved.' if kind != 'none' else 'Discount removed.')
