import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

USER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen',
            role='server', username='alex', status='active')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True})
        self.client = self.app.test_client()
        self.sql_patch = patch('app.run_sql')
        self.sql = self.sql_patch.start()
        self.addCleanup(self.sql_patch.stop)

    def auth(self, username='alex', password='class-password'):
        encoded = base64.b64encode(f'{username}:{password}'.encode()).decode()
        return {'X-Restaurant-Authorization': f'Basic {encoded}'}

    def test_login_returns_employee_identity(self):
        self.sql.return_value = [USER]
        response = self.client.post('/api/login', json={'username': ' Alex ', 'password': 'class-password'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['user']['employee_id'], '7')
        self.assertNotIn('password', response.json['user'])
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertEqual(self.sql.call_args.args[1], {'username': 'alex', 'password': 'class-password'})

    def test_bad_login_and_inactive_employee(self):
        self.sql.return_value = []
        self.assertEqual(self.client.post('/api/login', json={'username': 'alex', 'password': 'bad'}).status_code, 401)
        self.sql.return_value = [{**USER, 'status': 'inactive'}]
        self.assertEqual(self.client.post('/api/login', json={'username': 'alex', 'password': 'correct'}).status_code, 403)

    def registration(self):
        return dict(restaurant_id='2', first_name="O'Neil", last_name='Chen',
                    username='Alex', password='simple', role='server')

    def test_registration_creates_active_employee(self):
        self.sql.side_effect = [[], [{'1': '1'}], []]
        response = self.client.post('/api/register', json=self.registration())
        self.assertEqual(response.status_code, 201)
        query, values = self.sql.call_args.args
        self.assertNotIn("O'Neil", query)
        self.assertEqual(values['password'], 'simple')
        self.assertEqual(values['username'], 'alex')
        self.assertEqual(values['restaurant_id'], 2)
        self.assertIn("'active'", query)
        self.assertNotIn('Set-Cookie', response.headers)

    def test_duplicate_username_does_not_insert(self):
        self.sql.return_value = [{'1': '1'}]
        self.assertEqual(self.client.post('/api/register', json=self.registration()).status_code, 409)
        self.assertEqual(self.sql.call_count, 1)

    def test_missing_restaurant_does_not_insert(self):
        self.sql.side_effect = [[], []]
        self.assertEqual(self.client.post('/api/register', json=self.registration()).status_code, 400)
        self.assertEqual(self.sql.call_count, 2)

    def test_invalid_registration_does_not_query_database(self):
        for field, value in [('restaurant_id', '1 OR 1=1'), ('restaurant_id', True),
                             ('restaurant_id', 2**64), ('role', 'unknown'),
                             ('username', 'a'), ('first_name', ''), ('password', '')]:
            payload = self.registration()
            payload[field] = value
            self.assertEqual(self.client.post('/api/register', json=payload).status_code, 400)
        self.sql.assert_not_called()

    def test_dashboard_requires_valid_credentials(self):
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)
        self.sql.assert_not_called()
        self.sql.return_value = []
        self.assertEqual(self.client.get('/api/dashboard', headers=self.auth()).status_code, 401)
        self.sql.return_value = [{**USER, 'status': 'inactive'}]
        self.assertEqual(self.client.get('/api/dashboard', headers=self.auth()).status_code, 403)

    def test_dashboard_uses_employees_restaurant(self):
        tables = [dict(table_id='3', table_number='1', capacity='4', status='available', server_name=None)]
        self.sql.side_effect = [[USER], tables]
        response = self.client.get('/api/dashboard?restaurant_id=999', headers=self.auth())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['tables'], tables)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2})
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_database_error_is_friendly(self):
        self.sql.side_effect = RuntimeError('sensitive connection information')
        with self.assertLogs(self.app.logger, level='ERROR'):
            response = self.client.post('/api/login', json={'username': 'alex', 'password': 'password'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('sensitive', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
