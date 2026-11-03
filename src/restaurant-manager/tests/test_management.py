import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

MANAGER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen',
               role='manager', username='alex', status='active')
ITEM = dict(name="Chef's soup", description='Seasonal', category='Starter', price='8.50', available=True)


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True})
        self.client = self.app.test_client()
        auth_patch = patch('app.run_sql', return_value=[MANAGER])
        self.auth = auth_patch.start()
        self.addCleanup(auth_patch.stop)
        sql_patch = patch('management.run_sql')
        self.sql = sql_patch.start()
        self.sql.return_value = []
        self.addCleanup(sql_patch.stop)
        self.headers = {'X-Restaurant-Authorization': 'Basic ' + base64.b64encode(b'alex:simple').decode()}

    def call(self, path, method='GET', data=None):
        return self.client.open(path, method=method, json=data, headers=self.headers)

    def test_all_mutations_require_manager_role(self):
        self.auth.return_value = [{**MANAGER, 'role': 'server'}]
        endpoints = [('/api/menu', 'POST'), ('/api/menu/1', 'PUT'), ('/api/menu/1', 'DELETE'),
                     ('/api/tables', 'POST'), ('/api/tables/3', 'PUT'), ('/api/tables/3', 'DELETE'),
                     ('/api/tables/3/assignment', 'PUT'), ('/api/tables/3/assignment', 'DELETE')]
        for path, method in endpoints:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(path, method, {}).status_code, 403)
        self.sql.assert_not_called()

    def test_manager_can_add_menu_item_with_bound_values(self):
        response = self.call('/api/menu', 'POST', ITEM)
        self.assertEqual(response.status_code, 201)
        sql, parameters = self.sql.call_args.args
        self.assertNotIn("Chef's soup", sql)
        self.assertEqual(parameters['name'], "Chef's soup")
        self.assertEqual(parameters['price'], '8.50')
        self.assertEqual(parameters['restaurant_id'], 2)

    def test_creating_table_generates_numbered_seats(self):
        self.sql.side_effect = [[], [], [{'table_id': '3'}], []]
        self.assertEqual(self.call('/api/tables', 'POST', {'table_number': '1', 'capacity': '3'}).status_code, 201)
        self.assertIn('VALUES (1), (2), (3)', self.sql.call_args.args[0])
        self.assertEqual(self.sql.call_args.args[1], {'table_id': 3})


if __name__ == '__main__':
    unittest.main()
