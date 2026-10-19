"""Flask API and React entry point for the current class sprint."""

import os
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.datastructures import Authorization
from werkzeug.exceptions import HTTPException

from database import FULL_SCHEMA, run_sql

FRONTEND_DIST = Path(__file__).parent / 'frontend' / 'dist'
USER_FIELDS = ('employee_id', 'restaurant_id', 'first_name', 'last_name', 'role', 'username')


def create_app(config=None):
    app = Flask(__name__, static_folder=str(FRONTEND_DIST / 'assets'), static_url_path='/assets')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
    if config:
        app.config.update(config)

    @app.after_request
    def response_headers(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith('/api/'):
            return jsonify(error=error.description), error.code
        return error

    @app.errorhandler(RuntimeError)
    def database_error(error):
        app.logger.exception('Database request failed')
        return jsonify(error='Could not reach the database. Please try again shortly.'), 503

    def form_data():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def text(data, key):
        value = data.get(key, '')
        return value if isinstance(value, str) else ''

    def authenticate(username, password):
        if not username or not password or len(username) > 64 or len(password) > 128:
            return None
        rows = run_sql(f"""SELECT employee_id, restaurant_id, first_name, last_name, role, username, status
            FROM {FULL_SCHEMA}.employee
            WHERE lower(username) = :username AND password = :password LIMIT 1""",
            {'username': username.strip().lower(), 'password': password})
        return rows[0] if rows else None

    @app.get('/api/restaurants')
    def restaurants():
        rows = run_sql(f'SELECT restaurant_id, name FROM {FULL_SCHEMA}.restaurant ORDER BY name')
        return jsonify(restaurants=rows)

    @app.post('/api/register')
    def register():
        data = form_data()
        first_name = text(data, 'first_name').strip()
        last_name = text(data, 'last_name').strip()
        username = text(data, 'username').strip().lower()
        password = text(data, 'password')
        role = text(data, 'role') or 'server'
        if not first_name or not last_name or len(first_name) > 100 or len(last_name) > 100:
            return jsonify(error='Enter a first and last name, each at most 100 characters.'), 400
        if not re.fullmatch(r'[a-z0-9_.-]{3,64}', username):
            return jsonify(error='Use 3–64 letters, numbers, dots, underscores, or hyphens for your username.'), 400
        if not password or len(password) > 128:
            return jsonify(error='Enter a password of at most 128 characters.'), 400
        if role not in ('manager', 'server'):
            return jsonify(error='Choose a valid role.'), 400
        restaurant_id = data.get('restaurant_id')
        if not re.fullmatch(r'[1-9][0-9]{0,18}', str(restaurant_id)):
            return jsonify(error='Select a valid restaurant.'), 400
        restaurant_id = int(restaurant_id)
        if restaurant_id > 2**63 - 1:
            return jsonify(error='Select a valid restaurant.'), 400
        if run_sql(f'SELECT 1 FROM {FULL_SCHEMA}.employee WHERE lower(username) = :username LIMIT 1',
                   {'username': username}):
            return jsonify(error='That username is already taken.'), 409
        if not run_sql(f'SELECT 1 FROM {FULL_SCHEMA}.restaurant WHERE restaurant_id = :restaurant_id LIMIT 1',
                       {'restaurant_id': restaurant_id}):
            return jsonify(error='Restaurant not found.'), 400

        run_sql(f"""INSERT INTO {FULL_SCHEMA}.employee
            (restaurant_id, first_name, last_name, role, username, password, status)
            VALUES (:restaurant_id, :first_name, :last_name, :role, :username, :password, 'active')""",
            {'restaurant_id': restaurant_id, 'first_name': first_name, 'last_name': last_name,
             'role': role, 'username': username, 'password': password})
        return jsonify(message='Account created. You can now log in.'), 201

    @app.post('/api/login')
    def login():
        data = form_data()
        username, password = text(data, 'username'), text(data, 'password')
        if not username.strip() or not password:
            return jsonify(error='Enter your username and password.'), 400
        user = authenticate(username, password)
        if not user:
            return jsonify(error='Invalid username or password.'), 401
        if user['status'] != 'active':
            return jsonify(error='Your account is inactive. Contact your manager.'), 403
        return jsonify(user={field: user[field] for field in USER_FIELDS})

    @app.get('/api/dashboard')
    def dashboard():
        # React holds credentials in memory and sends them with this read-only request.
        # Use a separate header so the Databricks proxy can handle Authorization.
        # Employee login still has no Flask session or persistent browser storage.
        auth = Authorization.from_header(request.headers.get('X-Restaurant-Authorization'))
        user = authenticate(auth.username, auth.password) if auth and auth.type == 'basic' else None
        if not user:
            return jsonify(error='Please log in to continue.'), 401
        if user['status'] != 'active':
            return jsonify(error='Your account is inactive. Contact your manager.'), 403
        tables = run_sql(f"""SELECT t.table_id, t.table_number, t.capacity, t.status,
            e.first_name AS server_name
            FROM {FULL_SCHEMA}.restaurant_table t
            LEFT JOIN (
                SELECT table_id, employee_id,
                    ROW_NUMBER() OVER (PARTITION BY table_id ORDER BY assigned_at DESC, assignment_id DESC) AS rn
                FROM {FULL_SCHEMA}.server_table_assignment WHERE status = 'active'
            ) a ON a.table_id = t.table_id AND a.rn = 1
            LEFT JOIN {FULL_SCHEMA}.employee e
                ON e.employee_id = a.employee_id AND e.restaurant_id = t.restaurant_id
            WHERE t.restaurant_id = :restaurant_id ORDER BY t.table_number""",
            {'restaurant_id': int(user['restaurant_id'])})
        return jsonify(tables=tables)

    @app.get('/')
    @app.get('/login')
    @app.get('/register')
    @app.get('/dashboard')
    def frontend():
        if not (FRONTEND_DIST / 'index.html').is_file():
            return 'Build the React frontend first: cd frontend && npm ci && npm run build', 503
        return send_from_directory(FRONTEND_DIST, 'index.html')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
