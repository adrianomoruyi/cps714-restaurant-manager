import os
from functools import wraps
from databricks.sdk import WorkspaceClient
from flask import (
    Flask, request, session, redirect, url_for,
    render_template, flash,
)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'cps714-restaurant-manager-dev')

WAREHOUSE_ID = 'af22ac66ae5c1302'
CATALOG = 'cps714'
SCHEMA = 'restaurant_manager'
FULL_SCHEMA = f'{CATALOG}.{SCHEMA}'

w = WorkspaceClient()


# ── SQL helper ───────────────────────────────────────────────

def sql_literal(value):
    """Convert a Python value into a safe SQL literal for Databricks."""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def run_sql(sql):
    """Execute SQL and return rows as a list of dicts."""
    try:
        response = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID,
            catalog=CATALOG,
            schema=SCHEMA,
            statement=sql,
            wait_timeout='30s'
        )
    except Exception as exc:
        raise RuntimeError(f'SQL execution failed: {exc}') from exc

    if not response.status:
        return []

    state = getattr(response.status, 'state', None)
    state_value = state.value if hasattr(state, 'value') else str(state)
    if state_value != 'SUCCEEDED':
        err = getattr(response.status, 'error', None)
        err_msg = 'Query failed'
        if err:
            err_msg = getattr(err, 'message', None) or str(err)
        app.logger.error(f'SQL query failed with state={state_value}, error={err}')
        raise RuntimeError(f'SQL failed (state={state_value}): {err_msg}')

    if not response.result or not response.manifest:
        return []
    columns = [c.name for c in response.manifest.schema.columns]
    return [dict(zip(columns, row)) for row in (response.result.data_array or [])]


# ── Auth decorators ─────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'employee_id' not in session:
            flash('Please log in first.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'employee_id' not in session:
            flash('Please log in first.')
            return redirect(url_for('login'))
        if session.get('role') != 'manager':
            flash('Manager access required.')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Auth routes ──────────────────────────────────────────────

@app.route('/')
def index():
    if 'employee_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    restaurants = _get_restaurants()

    if request.method == 'POST':
        restaurant_id = request.form.get('restaurant_id', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        role = request.form.get('role', 'server').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not all([restaurant_id, first_name, last_name, username, password]):
            flash('All fields are required.')
            return render_template('register.html', restaurants=restaurants)

        try:
            restaurant_id_int = int(restaurant_id)
            if run_sql(f"SELECT 1 FROM {FULL_SCHEMA}.employee WHERE username = {sql_literal(username)} LIMIT 1"):
                flash('Username already taken.')
                return render_template('register.html', restaurants=restaurants)

            if not run_sql(f"SELECT 1 FROM {FULL_SCHEMA}.restaurant WHERE restaurant_id = {restaurant_id_int} LIMIT 1"):
                flash('Restaurant not found.')
                return render_template('register.html', restaurants=restaurants)

            run_sql(f"""INSERT INTO {FULL_SCHEMA}.employee
                (restaurant_id, first_name, last_name, role, username, password, status)
                VALUES ({restaurant_id_int}, {sql_literal(first_name)}, {sql_literal(last_name)}, {sql_literal(role)},
                        {sql_literal(username)}, {sql_literal(password)}, 'active')""")
        except ValueError:
            flash('Restaurant ID must be a number.')
            return render_template('register.html', restaurants=restaurants)
        except Exception as exc:
            app.logger.exception('Registration failed')
            flash(f'Registration failed: {exc}')
            return render_template('register.html', restaurants=_get_restaurants())

        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))

    return render_template('register.html', restaurants=restaurants)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Username and password are required.')
            return render_template('login.html')

        try:
            rows = run_sql(f"""SELECT employee_id, restaurant_id, first_name, last_name, role, status
                FROM {FULL_SCHEMA}.employee
                WHERE username = {sql_literal(username)} AND password = {sql_literal(password)} LIMIT 1""")
        except Exception as exc:
            app.logger.exception('Login failed')
            flash(f'Login failed: {exc}')
            return render_template('login.html')

        if not rows:
            flash('Invalid username or password.')
            return render_template('login.html')

        user = rows[0]
        if user['status'] != 'active':
            flash('Account is inactive. Contact a manager.')
            return render_template('login.html')

        session['employee_id'] = user['employee_id']
        session['restaurant_id'] = user['restaurant_id']
        session['first_name'] = user['first_name']
        session['last_name'] = user['last_name']
        session['role'] = user['role']
        session['username'] = username

        flash(f"Welcome, {user['first_name']}!")
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('login'))


# ── Dashboard ────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    rid = session['restaurant_id']
    tables = run_sql(f"""SELECT t.table_id, t.table_number, t.capacity, t.status,
        (SELECT e.first_name FROM {FULL_SCHEMA}.server_table_assignment sta
         JOIN {FULL_SCHEMA}.employee e ON sta.employee_id = e.employee_id
         WHERE sta.table_id = t.table_id AND sta.status = 'active' LIMIT 1) as server_name
        FROM {FULL_SCHEMA}.restaurant_table t
        WHERE t.restaurant_id = {rid}
        ORDER BY t.table_number""")
    return render_template('dashboard.html', tables=tables)


# ── Menu ─────────────────────────────────────────────────────

@app.route('/menu')
@login_required
def menu():
    rid = session['restaurant_id']
    items = run_sql(f"""SELECT menu_item_id, name, description, price, category, available
        FROM {FULL_SCHEMA}.menu_item
        WHERE restaurant_id = {rid}
        ORDER BY category, name""")
    return render_template('menu.html', items=items, is_manager=(session['role'] == 'manager'))


@app.route('/menu/add', methods=['POST'])
@manager_required
def menu_add():
    rid = session['restaurant_id']
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    price = request.form.get('price', '0').strip()
    category = request.form.get('category', '').strip()
    available = 'true' if request.form.get('available') else 'false'

    if not name or not price:
        flash('Name and price are required.')
        return redirect(url_for('menu'))

    run_sql(f"""INSERT INTO {FULL_SCHEMA}.menu_item
        (restaurant_id, name, description, price, category, available)
        VALUES ({rid}, '{name}', '{description}', {price}, '{category}', {available})""")
    flash('Menu item added.')
    return redirect(url_for('menu'))


@app.route('/menu/update/<item_id>', methods=['POST'])
@manager_required
def menu_update(item_id):
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    price = request.form.get('price', '0').strip()
    category = request.form.get('category', '').strip()
    available = 'true' if request.form.get('available') else 'false'

    run_sql(f"""UPDATE {FULL_SCHEMA}.menu_item
        SET name = '{name}', description = '{description}', price = {price},
            category = '{category}', available = {available}
        WHERE menu_item_id = {item_id}""")
    flash('Menu item updated.')
    return redirect(url_for('menu'))


@app.route('/menu/delete/<item_id>', methods=['POST'])
@manager_required
def menu_delete(item_id):
    run_sql(f"DELETE FROM {FULL_SCHEMA}.menu_item WHERE menu_item_id = {item_id}")
    flash('Menu item deleted.')
    return redirect(url_for('menu'))


# ── Orders ───────────────────────────────────────────────────

@app.route('/orders', methods=['GET', 'POST'])
@login_required
def orders():
    rid = session['restaurant_id']

    if request.method == 'POST':
        seat_id = request.form.get('seat_id', '').strip()
        menu_item_id = request.form.get('menu_item_id', '').strip()
        quantity = request.form.get('quantity', '1').strip()

        if not seat_id or not menu_item_id:
            flash('Seat and menu item are required.')
            return redirect(url_for('orders'))

        run_sql(f"""INSERT INTO {FULL_SCHEMA}.seat_order_item
            (seat_id, menu_item_id, quantity)
            VALUES ({seat_id}, {menu_item_id}, {quantity})""")
        flash('Order added.')
        return redirect(url_for('orders'))

    tables = run_sql(f"""SELECT t.table_id, t.table_number, t.status
        FROM {FULL_SCHEMA}.restaurant_table t
        WHERE t.restaurant_id = {rid}
        ORDER BY t.table_number""")

    table_ids = [t['table_id'] for t in tables]
    seats, orders = [], []
    if table_ids:
        ids_csv = ','.join(str(tid) for tid in table_ids)
        seats = run_sql(f"""SELECT s.seat_id, s.table_id, s.seat_number
            FROM {FULL_SCHEMA}.seat s
            WHERE s.table_id IN ({ids_csv})
            ORDER BY s.table_id, s.seat_number""")
        orders = run_sql(f"""SELECT soi.seat_order_id, soi.seat_id, s.seat_number,
            t.table_number, m.name as menu_item_name, soi.quantity, soi.status
            FROM {FULL_SCHEMA}.seat_order_item soi
            JOIN {FULL_SCHEMA}.seat s ON soi.seat_id = s.seat_id
            JOIN {FULL_SCHEMA}.restaurant_table t ON s.table_id = t.table_id
            JOIN {FULL_SCHEMA}.menu_item m ON soi.menu_item_id = m.menu_item_id
            WHERE t.restaurant_id = {rid}
            ORDER BY t.table_number, s.seat_number""")

    menu_items = run_sql(f"""SELECT menu_item_id, name, price
        FROM {FULL_SCHEMA}.menu_item
        WHERE restaurant_id = {rid} AND available = true
        ORDER BY name""")

    return render_template('orders.html', tables=tables, seats=seats,
                          menu_items=menu_items, orders=orders,
                          is_manager=(session['role'] == 'manager'))


@app.route('/clear-table/<table_id>', methods=['POST'])
@login_required
def clear_table(table_id):
    rid = session['restaurant_id']

    if not run_sql(f"SELECT 1 FROM {FULL_SCHEMA}.restaurant_table WHERE table_id = {table_id} AND restaurant_id = {rid} LIMIT 1"):
        flash('Table not found.')
        return redirect(url_for('dashboard'))

    if session['role'] != 'manager':
        if not run_sql(f"""SELECT 1 FROM {FULL_SCHEMA}.server_table_assignment
            WHERE table_id = {table_id} AND employee_id = {session['employee_id']}
            AND status = 'active' LIMIT 1"""):
            flash('You can only clear tables assigned to you.')
            return redirect(url_for('dashboard'))

    seats = run_sql(f"SELECT seat_id FROM {FULL_SCHEMA}.seat WHERE table_id = {table_id}")
    if seats:
        seat_ids = ','.join(str(s['seat_id']) for s in seats)
        run_sql(f"DELETE FROM {FULL_SCHEMA}.seat_order_item WHERE seat_id IN ({seat_ids})")

    run_sql(f"""UPDATE {FULL_SCHEMA}.server_table_assignment
        SET status = 'inactive' WHERE table_id = {table_id} AND status = 'active'""")
    run_sql(f"UPDATE {FULL_SCHEMA}.restaurant_table SET status = 'available' WHERE table_id = {table_id}")
    flash('Table cleared.')
    return redirect(url_for('dashboard'))


# ── Assign server (manager only) ─────────────────────────────

@app.route('/assign-server', methods=['GET', 'POST'])
@manager_required
def assign_server():
    rid = session['restaurant_id']

    if request.method == 'POST':
        table_id = request.form.get('table_id', '').strip()
        employee_id = request.form.get('employee_id', '').strip()

        if not table_id or not employee_id:
            flash('Table and server are required.')
            return redirect(url_for('assign_server'))

        run_sql(f"""UPDATE {FULL_SCHEMA}.server_table_assignment
            SET status = 'inactive' WHERE table_id = {table_id} AND status = 'active'""")
        run_sql(f"""INSERT INTO {FULL_SCHEMA}.server_table_assignment
            (table_id, employee_id, status)
            VALUES ({table_id}, {employee_id}, 'active')""")
        flash('Server assigned to table.')
        return redirect(url_for('assign_server'))

    tables = run_sql(f"""SELECT t.table_id, t.table_number, t.status
        FROM {FULL_SCHEMA}.restaurant_table t
        WHERE t.restaurant_id = {rid}
        ORDER BY t.table_number""")
    servers = run_sql(f"""SELECT employee_id, first_name, last_name
        FROM {FULL_SCHEMA}.employee
        WHERE restaurant_id = {rid} AND role = 'server' AND status = 'active'
        ORDER BY first_name""")

    assignments = []
    if tables:
        table_ids = ','.join(str(t['table_id']) for t in tables)
        assignments = run_sql(f"""SELECT sta.assignment_id, t.table_number,
            e.first_name, e.last_name
            FROM {FULL_SCHEMA}.server_table_assignment sta
            JOIN {FULL_SCHEMA}.restaurant_table t ON sta.table_id = t.table_id
            JOIN {FULL_SCHEMA}.employee e ON sta.employee_id = e.employee_id
            WHERE sta.table_id IN ({table_ids}) AND sta.status = 'active'
            ORDER BY t.table_number""")

    return render_template('assign_server.html', tables=tables, servers=servers,
                          assignments=assignments)


# ── Reports (manager only) ───────────────────────────────────

@app.route('/reports')
@manager_required
def reports():
    rid = session['restaurant_id']

    total_orders = run_sql(f"""SELECT COUNT(*) as cnt
        FROM {FULL_SCHEMA}.seat_order_item soi
        JOIN {FULL_SCHEMA}.seat s ON soi.seat_id = s.seat_id
        JOIN {FULL_SCHEMA}.restaurant_table t ON s.table_id = t.table_id
        WHERE t.restaurant_id = {rid}""")

    revenue = run_sql(f"""SELECT SUM(m.price * soi.quantity) as total
        FROM {FULL_SCHEMA}.seat_order_item soi
        JOIN {FULL_SCHEMA}.seat s ON soi.seat_id = s.seat_id
        JOIN {FULL_SCHEMA}.restaurant_table t ON s.table_id = t.table_id
        JOIN {FULL_SCHEMA}.menu_item m ON soi.menu_item_id = m.menu_item_id
        WHERE t.restaurant_id = {rid}""")

    status_counts = run_sql(f"""SELECT soi.status, COUNT(*) as cnt
        FROM {FULL_SCHEMA}.seat_order_item soi
        JOIN {FULL_SCHEMA}.seat s ON soi.seat_id = s.seat_id
        JOIN {FULL_SCHEMA}.restaurant_table t ON s.table_id = t.table_id
        WHERE t.restaurant_id = {rid}
        GROUP BY soi.status""")

    table_status = run_sql(f"""SELECT status, COUNT(*) as cnt
        FROM {FULL_SCHEMA}.restaurant_table
        WHERE restaurant_id = {rid}
        GROUP BY status""")

    popular = run_sql(f"""SELECT m.name, m.category, SUM(soi.quantity) as qty,
        SUM(m.price * soi.quantity) as revenue
        FROM {FULL_SCHEMA}.seat_order_item soi
        JOIN {FULL_SCHEMA}.seat s ON soi.seat_id = s.seat_id
        JOIN {FULL_SCHEMA}.restaurant_table t ON s.table_id = t.table_id
        JOIN {FULL_SCHEMA}.menu_item m ON soi.menu_item_id = m.menu_item_id
        WHERE t.restaurant_id = {rid}
        GROUP BY m.name, m.category
        ORDER BY qty DESC
        LIMIT 10""")

    return render_template('reports.html',
                          total_orders=total_orders[0]['cnt'] if total_orders else 0,
                          revenue=revenue[0]['total'] if revenue and revenue[0]['total'] else 0,
                          status_counts=status_counts,
                          table_status=table_status,
                          popular=popular)


# ── Helpers ─────────────────────────────────────────────────

def _get_restaurants():
    try:
        return run_sql(f"SELECT restaurant_id, name FROM {FULL_SCHEMA}.restaurant ORDER BY restaurant_id") or []
    except Exception as exc:
        app.logger.exception('Failed to load restaurant list')
        return []


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)