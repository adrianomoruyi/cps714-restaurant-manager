"""Restaurant administration and restaurant-scoped employee management."""

import re
from flask import abort, jsonify, request

from database import FULL_SCHEMA, run_sql

STAFF_ROLES = ('manager', 'server')


def register_administration(app, current_employee):
    def actor():
        user = current_employee()
        if user['role'] != 'manager':
            abort(403, description='Manager access is required.')
        return user

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description='Submit a JSON object.')
        return data

    def text(data, name, maximum, required=False):
        value = data.get(name, '')
        if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
            abort(400, description=f'Enter a valid {name.replace("_", " ")} (at most {maximum} characters).')
        return value.strip()

    def restaurant_values():
        data = body()
        return dict(name=text(data, 'name', 120, True), address=text(data, 'address', 300), phone=text(data, 'phone', 40))

    def restaurant_for(restaurant_id):
        if not run_sql(f'SELECT restaurant_id FROM {FULL_SCHEMA}.restaurant WHERE restaurant_id = :restaurant_id', {'restaurant_id': restaurant_id}):
            abort(404, description='Restaurant not found.')

    def employee_for(user, employee_id):
        values = dict(restaurant_id=int(user['restaurant_id']), employee_id=employee_id)
        rows = run_sql(f'''SELECT employee_id, first_name, last_name, username, role, status
            FROM {FULL_SCHEMA}.employee WHERE employee_id = :employee_id AND restaurant_id = :restaurant_id''', values)
        if not rows:
            abort(404, description='Employee not found in your restaurant.')
        return rows[0], values

    def employee_values(user, editing=False):
        data = body()
        values = dict(first_name=text(data, 'first_name', 100, True), last_name=text(data, 'last_name', 100, True),
                      username=text(data, 'username', 64, True).lower(), role=data.get('role'), status=data.get('status', 'active'))
        if not re.fullmatch(r'[a-z0-9_.-]{3,64}', values['username']):
            abort(400, description='Use 3–64 letters, numbers, dots, underscores, or hyphens for the username.')
        if values['role'] not in STAFF_ROLES:
            abort(400, description='Choose a permitted employee role.')
        if values['status'] not in ('active', 'inactive'):
            abort(400, description='Choose active or inactive.')
        password = data.get('password', '')
        if not isinstance(password, str) or len(password) > 128 or (not editing and not password):
            abort(400, description='Enter a password of 1–128 characters for a new employee.')
        if password:
            values['password'] = password
        return values

    def unique_username(username, employee_id=0):
        if run_sql(f'''SELECT 1 FROM {FULL_SCHEMA}.employee
            WHERE lower(username) = :username AND employee_id <> :employee_id LIMIT 1''',
            dict(username=username, employee_id=employee_id)):
            abort(409, description='That username is already taken.')

    @app.get('/api/restaurant')
    def own_restaurant():
        user = actor()
        rows = run_sql(f'''SELECT restaurant_id, name, address, phone FROM {FULL_SCHEMA}.restaurant
            WHERE restaurant_id = :restaurant_id''', {'restaurant_id': int(user['restaurant_id'])})
        if not rows:
            abort(404, description='Restaurant not found.')
        return jsonify(restaurant=rows[0])

    @app.post('/api/restaurants')
    def create_restaurant():
        actor()
        values = restaurant_values()
        run_sql(f'''INSERT INTO {FULL_SCHEMA}.restaurant (name, address, phone)
            VALUES (:name, :address, :phone)''', values)
        return jsonify(message=f'Restaurant "{values["name"]}" created. Its team can select it when registering. Your account stays with your current restaurant.'), 201

    @app.put('/api/restaurants/<int:restaurant_id>')
    def edit_restaurant(restaurant_id):
        user = actor()
        if restaurant_id != int(user['restaurant_id']):
            abort(404, description='Restaurant not found for your account.')
        values = restaurant_values()
        restaurant_for(restaurant_id)
        run_sql(f'''UPDATE {FULL_SCHEMA}.restaurant SET name = :name, address = :address, phone = :phone
            WHERE restaurant_id = :restaurant_id''', dict(restaurant_id=restaurant_id, **values))
        return jsonify(message='Restaurant updated.')

    @app.get('/api/employees')
    def employees():
        user = actor()
        rows = run_sql(f'''SELECT employee_id, first_name, last_name, username, role, status
            FROM {FULL_SCHEMA}.employee WHERE restaurant_id = :restaurant_id
            ORDER BY first_name, last_name''', {'restaurant_id': int(user['restaurant_id'])})
        return jsonify(employees=rows)

    @app.post('/api/employees')
    def create_employee():
        user = actor()
        values = employee_values(user)
        unique_username(values['username'])
        run_sql(f'''INSERT INTO {FULL_SCHEMA}.employee
            (restaurant_id, first_name, last_name, username, password, role, status)
            VALUES (:restaurant_id, :first_name, :last_name, :username, :password, :role, :status)''',
            dict(restaurant_id=int(user['restaurant_id']), **values))
        return jsonify(message='Employee created.'), 201

    @app.put('/api/employees/<int:employee_id>')
    def edit_employee(employee_id):
        user = actor()
        employee, scope = employee_for(user, employee_id)
        values = employee_values(user, editing=True)
        if str(employee_id) == str(user['employee_id']):
            if (values['role'] != user['role'] or values['status'] != 'active'
                    or values['username'] != employee['username'] or 'password' in values):
                abort(409, description='Use another manager account to change your own role, login, or active status.')
        unique_username(values['username'], employee_id)
        # Retire assignments before disabling a server, so a failed update cannot leave access behind.
        if values['status'] != 'active' or values['role'] != 'server':
            run_sql(f'''UPDATE {FULL_SCHEMA}.server_table_assignment SET status = 'inactive'
                WHERE employee_id = :employee_id AND status = 'active' ''', {'employee_id': employee_id})
        columns = ', '.join(f'{key} = :{key}' for key in values)
        run_sql(f'UPDATE {FULL_SCHEMA}.employee SET {columns} WHERE employee_id = :employee_id AND restaurant_id = :restaurant_id',
                dict(**scope, **values))
        return jsonify(message='Employee updated. Inactive employees cannot log in; their server assignments are removed.')

    @app.delete('/api/employees/<int:employee_id>')
    def delete_employee(employee_id):
        user = actor()
        _, values = employee_for(user, employee_id)
        if str(employee_id) == str(user['employee_id']):
            abort(409, description='You cannot delete your own account.')
        for table, field in [('server_table_assignment', 'employee_id'), ('bill_plan', 'discount_employee_id')]:
            if run_sql(f'SELECT 1 FROM {FULL_SCHEMA}.{table} WHERE {field} = :employee_id LIMIT 1', {'employee_id': employee_id}):
                abort(409, description='This employee has history. Set their status to inactive instead of deleting them.')
        run_sql(f'DELETE FROM {FULL_SCHEMA}.employee WHERE employee_id = :employee_id AND restaurant_id = :restaurant_id', values)
        return jsonify(message='Employee deleted.')
