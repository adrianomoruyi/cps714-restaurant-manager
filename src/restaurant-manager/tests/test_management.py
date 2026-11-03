import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

MANAGER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen',
               role='manager', username='alex', status='active')
TABLE = dict(table_id='3', table_number='1', capacity='4', status='available')
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

    def test_servers_can_browse_the_menu_in_their_restaurant(self):
        self.auth.return_value = [{**MANAGER, 'role': 'server'}]
        self.sql.return_value = [{**ITEM, 'menu_item_id': '1', 'available': 'false'}]
        response = self.call('/api/menu?restaurant_id=999')
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json['items'][0]['available'], False)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2})

    def test_manager_can_add_menu_item_with_bound_values(self):
        response = self.call('/api/menu', 'POST', ITEM)
        self.assertEqual(response.status_code, 201)
        sql, parameters = self.sql.call_args.args
        self.assertNotIn("Chef's soup", sql)
        self.assertEqual(parameters['name'], "Chef's soup")
        self.assertEqual(parameters['price'], '8.50')
        self.assertEqual(parameters['restaurant_id'], 2)

    def test_invalid_menu_does_not_write(self):
        self.assertEqual(self.call('/api/menu', 'POST', {**ITEM, 'price': '8.001'}).status_code, 400)
        self.assertEqual(self.call('/api/menu', 'POST', []).status_code, 400)
        self.sql.assert_not_called()

    def test_manager_can_update_menu_availability(self):
        self.sql.side_effect = [[{'menu_item_id': '1'}], []]
        self.assertEqual(self.call('/api/menu/1', 'PUT', {**ITEM, 'available': False}).status_code, 200)
        self.assertEqual(self.sql.call_args.args[1]['available'], 'false')
        self.assertEqual(self.sql.call_args.args[1]['restaurant_id'], 2)

    def test_menu_item_with_orders_cannot_be_deleted(self):
        self.sql.side_effect = [[{'menu_item_id': '1'}], [{'1': '1'}]]
        response = self.call('/api/menu/1', 'DELETE')
        self.assertEqual(response.status_code, 409)
        self.assertIn('unavailable', response.json['error'])
        self.assertEqual(self.sql.call_count, 2)

    def test_creating_table_generates_numbered_seats(self):
        self.sql.side_effect = [[], [], [{'table_id': '3'}], []]
        self.assertEqual(self.call('/api/tables', 'POST', {'table_number': '1', 'capacity': '3'}).status_code, 201)
        self.assertIn('VALUES (1), (2), (3)', self.sql.call_args.args[0])
        self.assertEqual(self.sql.call_args.args[1], {'table_id': 3})

    def test_seats_with_orders_cannot_be_removed_by_resizing(self):
        self.sql.side_effect = [[TABLE], [], [{'1': '1'}]]
        response = self.call('/api/tables/3', 'PUT', {'table_number': 1, 'capacity': 2, 'status': 'available'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('order history', response.json['error'])
        self.assertEqual(self.sql.call_count, 3)

    def test_manager_can_resize_and_change_status(self):
        self.sql.side_effect = [[TABLE], [], [], [], [], []]
        response = self.call('/api/tables/3', 'PUT', {'table_number': '2', 'capacity': '6', 'status': 'reserved'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('(6)', self.sql.call_args_list[3].args[0])
        self.assertEqual(self.sql.call_args.args[1], dict(restaurant_id=2, table_id=3, table_number=2, capacity=6, status='reserved'))

    def test_table_with_orders_cannot_be_deleted(self):
        self.sql.side_effect = [[TABLE], [{'1': '1'}]]
        self.assertEqual(self.call('/api/tables/3', 'DELETE').status_code, 409)
        self.assertEqual(self.sql.call_count, 2)

    def test_restaurant_boundaries_apply_to_menu_tables_and_servers(self):
        cases = [
            ('/api/menu/99', ITEM, [[]], 404),
            ('/api/tables/99', {'table_number': 1, 'capacity': 4, 'status': 'reserved'}, [[]], 404),
            ('/api/tables/3/assignment', {'employee_id': 8}, [[TABLE], []], 400),
        ]
        for path, payload, results, status in cases:
            with self.subTest(path=path):
                self.sql.reset_mock()
                self.sql.side_effect = results
                self.assertEqual(self.call(path, 'PUT', payload).status_code, status)
                self.assertEqual(self.sql.call_args.args[1]['restaurant_id'], 2)
                for call in self.sql.call_args_list:
                    self.assertTrue(call.args[0].lstrip().startswith('SELECT'))

    def test_manager_can_assign_a_server_and_remove_the_assignment_without_freeing_table(self):
        self.sql.side_effect = [[TABLE], [{'employee_id': '8'}], [], [], []]
        response = self.call('/api/tables/3/assignment', 'PUT', {'employee_id': 8})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sql.call_args_list[1].args[1], {'restaurant_id': 2, 'employee_id': 8})
        self.assertIn('INSERT INTO', self.sql.call_args_list[2].args[0])
        self.assertIn("SET status = 'inactive'", self.sql.call_args_list[3].args[0])
        self.assertIn("SET status = 'occupied'", self.sql.call_args.args[0])

        self.sql.reset_mock()
        self.sql.side_effect = [[{**TABLE, 'status': 'occupied'}], []]
        self.assertEqual(self.call('/api/tables/3/assignment', 'DELETE').status_code, 200)
        self.assertIn('server_table_assignment', self.sql.call_args.args[0])
        self.assertEqual(self.sql.call_count, 2)


if __name__ == '__main__':
    unittest.main()
