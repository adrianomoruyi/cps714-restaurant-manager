import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

USER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen', role='manager', username='alex', status='active')
EMPLOYEE = dict(employee_id='8', first_name='Sam', last_name='Lee', username='sam', role='server', status='active')


class AdministrationTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app({'TESTING': True}).test_client()
        self.headers = {'X-Restaurant-Authorization': 'Basic ' + base64.b64encode(b'alex:simple').decode()}
        auth = patch('app.run_sql', return_value=[USER])
        self.auth = auth.start()
        self.addCleanup(auth.stop)
        sql = patch('administration.run_sql', return_value=[])
        self.sql = sql.start()
        self.addCleanup(sql.stop)

    def test_managers_can_configure_only_their_restaurant_and_create_restaurants(self):
        payload = dict(name='New restaurant', address='123 Main St', phone='555-0100')
        self.auth.return_value = [{**USER, 'role': 'server'}]
        for method, path in [('GET', '/api/restaurant'), ('POST', '/api/restaurants'), ('PUT', '/api/restaurants/2')]:
            with self.subTest(method=method):
                self.assertEqual(self.client.open(path, method=method, json=payload, headers=self.headers).status_code, 403)
        self.sql.assert_not_called()
        self.auth.return_value = [USER]
        response = self.client.post('/api/restaurants', json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.sql.call_args.args[1], payload)
        self.sql.reset_mock()
        self.sql.return_value = [{'restaurant_id': '2', **payload}]
        response = self.client.get('/api/restaurant', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2})
        self.sql.reset_mock()
        self.sql.side_effect = [[{'restaurant_id': '2'}], []]
        self.assertEqual(self.client.put('/api/restaurants/2', json=payload, headers=self.headers).status_code, 200)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, **payload})
        self.sql.reset_mock()
        self.sql.side_effect = None
        self.assertEqual(self.client.put('/api/restaurants/9', json=payload, headers=self.headers).status_code, 404)
        self.sql.assert_not_called()
        response = self.client.get('/api/dashboard', headers={**self.headers, 'X-Restaurant-ID': '9'})
        self.assertEqual(response.status_code, 403)

    def test_employee_creation_and_deactivation_are_scoped_and_retire_assignments(self):
        payload = dict(first_name='Sam', last_name='Lee', username='Sam', password='simple', role='server', status='active')
        response = self.client.post('/api/employees', json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.sql.call_args.args[1]['restaurant_id'], 2)
        self.assertEqual(self.sql.call_args.args[1]['username'], 'sam')

        self.sql.reset_mock()
        self.sql.side_effect = [[EMPLOYEE], [], [], []]
        response = self.client.put('/api/employees/8', json={**payload, 'password': '', 'status': 'inactive'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn('server_table_assignment', self.sql.call_args_list[-2].args[0])
        self.assertEqual(self.sql.call_args.args[1]['status'], 'inactive')
        self.assertEqual(self.sql.call_args.args[1]['restaurant_id'], 2)
        self.assertNotIn('password', self.sql.call_args.args[1])

    def test_employee_management_rejects_servers_unsupported_roles_and_self_lockout(self):
        self.auth.return_value = [{**USER, 'role': 'server'}]
        self.assertEqual(self.client.get('/api/employees', headers=self.headers).status_code, 403)
        self.sql.assert_not_called()
        self.auth.return_value = [USER]
        payload = dict(first_name='Alex', last_name='Chen', username='alex', password='simple', role='admin')
        self.assertEqual(self.client.post('/api/employees', json=payload, headers=self.headers).status_code, 400)
        self.sql.assert_not_called()
        self.sql.return_value = [USER]
        self.assertEqual(self.client.delete('/api/employees/7', headers=self.headers).status_code, 409)
        self.assertEqual(self.client.put('/api/employees/7', json={**payload, 'role': 'manager', 'status': 'inactive'}, headers=self.headers).status_code, 409)

    def test_employee_history_and_restaurant_boundaries_are_protected(self):
        self.sql.side_effect = [[EMPLOYEE], [{'1': '1'}]]
        self.assertEqual(self.client.delete('/api/employees/8', headers=self.headers).status_code, 409)
        self.assertEqual(self.sql.call_count, 2)
        self.sql.reset_mock()
        self.sql.side_effect = [[]]
        self.assertEqual(self.client.delete('/api/employees/99', headers=self.headers).status_code, 404)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'employee_id': 99})


if __name__ == '__main__':
    unittest.main()
