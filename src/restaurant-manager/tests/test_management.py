import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.exceptions import BadRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from management import menu_values, positive_integer

MANAGER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen',
               role='manager', username='alex', status='active')
TABLE = dict(table_id='3', table_number='1', capacity='4', status='available')
ITEM = dict(name="Chef's soup", description='Seasonal', category='Starter', price='8.50', available=True)


class ValidationTests(unittest.TestCase):
    def test_money_is_normalized_without_rounding(self):
        self.assertEqual(menu_values({**ITEM, 'price': '8.5'})['price'], '8.50')
        self.assertEqual(menu_values({**ITEM, 'price': 0})['price'], '0.00')
        self.assertEqual(menu_values({**ITEM, 'available': False})['available'], 'false')

    def test_invalid_prices_and_availability_are_rejected(self):
        for price in ('NaN', 'Infinity', '-1', '1.005', '1000000', True, None, ''):
            with self.subTest(price=price), self.assertRaises(BadRequest):
                menu_values({**ITEM, 'price': price})
        with self.assertRaises(BadRequest):
            menu_values({**ITEM, 'available': 'false'})

    def test_identifiers_and_capacity_must_be_positive_integers(self):
        self.assertEqual(positive_integer('30', 'Capacity', 30), 30)
        for value in (0, -1, 1.5, True, '1 OR 1=1', 31, 2**64):
            with self.subTest(value=value), self.assertRaises(BadRequest):
                positive_integer(value, 'Capacity', 30)


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

    def test_all_management_routes_require_employee_login(self):
        self.auth.return_value = []
        for path, method in [('/api/menu', 'GET'), ('/api/tables', 'GET'),
                             ('/api/menu', 'POST'), ('/api/tables/3/assignment', 'PUT')]:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(path, method, {}).status_code, 401)
        self.sql.assert_not_called()

    def test_all_mutations_require_manager_role(self):
        self.auth.return_value = [{**MANAGER, 'role': 'server'}]
        endpoints = [('/api/menu', 'POST'), ('/api/menu/1', 'PUT'), ('/api/menu/1', 'DELETE'),
                     ('/api/tables', 'POST'), ('/api/tables/3', 'PUT'), ('/api/tables/3', 'DELETE'),
                     ('/api/tables/3/assignment', 'PUT'), ('/api/tables/3/assignment', 'DELETE')]
        for path, method in endpoints:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(path, method, {}).status_code, 403)
        self.sql.assert_not_called()

    def test_inactive_manager_cannot_make_changes(self):
        self.auth.return_value = [{**MANAGER, 'status': 'inactive'}]
        self.assertEqual(self.call('/api/menu', 'POST', ITEM).status_code, 403)
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

    def test_optional_menu_fields_are_editable_when_database_values_are_null(self):
        self.sql.return_value = [{**ITEM, 'menu_item_id': '1', 'description': None, 'category': None}]
        response = self.call('/api/menu')
        item = response.json['items'][0]
        self.assertEqual(item['description'], '')
        self.assertEqual(item['category'], '')
        self.sql.side_effect = [[{'menu_item_id': '1'}], []]
        self.assertEqual(self.call('/api/menu/1', 'PUT', {**item, 'available': False}).status_code, 200)

    def test_invalid_menu_does_not_write(self):
        self.assertEqual(self.call('/api/menu', 'POST', {**ITEM, 'price': '8.001'}).status_code, 400)
        self.assertEqual(self.call('/api/menu', 'POST', []).status_code, 400)
        self.sql.assert_not_called()

    def test_menu_update_rejects_an_item_outside_the_restaurant(self):
        self.assertEqual(self.call('/api/menu/99', 'PUT', ITEM).status_code, 404)
        self.assertEqual(self.sql.call_count, 1)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'item_id': 99})

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

    def test_unused_menu_item_can_be_deleted(self):
        self.sql.side_effect = [[{'menu_item_id': '1'}], [], []]
        self.assertEqual(self.call('/api/menu/1', 'DELETE').status_code, 200)
        self.assertTrue(self.sql.call_args.args[0].startswith('DELETE'))
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'item_id': 1})

    def test_table_list_groups_seats_and_limits_servers_to_the_restaurant(self):
        self.auth.return_value = [{**MANAGER, 'role': 'server'}]
        seats = [dict(seat_id='10', table_id='3', seat_number='1'), dict(seat_id='11', table_id='4', seat_number='1')]
        self.sql.side_effect = [[TABLE, {**TABLE, 'table_id': '4'}], seats, [{'employee_id': '8'}]]
        response = self.call('/api/tables?restaurant_id=999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['tables'][0]['seats'], [seats[0]])
        self.assertEqual(response.json['tables'][1]['seats'], [seats[1]])
        for call in self.sql.call_args_list:
            self.assertEqual(call.args[1], {'restaurant_id': 2})
        self.assertIn("role = 'server'", self.sql.call_args.args[0])

    def test_creating_table_generates_numbered_seats(self):
        self.sql.side_effect = [[], [], [{'table_id': '3'}], []]
        self.assertEqual(self.call('/api/tables', 'POST', {'table_number': '1', 'capacity': '3'}).status_code, 201)
        self.assertIn('VALUES (1), (2), (3)', self.sql.call_args.args[0])
        self.assertEqual(self.sql.call_args.args[1], {'table_id': 3})

    def test_duplicate_table_number_does_not_insert(self):
        self.sql.return_value = [{'1': '1'}]
        self.assertEqual(self.call('/api/tables', 'POST', {'table_number': 1, 'capacity': 4}).status_code, 409)
        self.assertEqual(self.sql.call_count, 1)

    def test_invalid_capacity_does_not_query_database(self):
        for capacity in (0, 31, 1.5):
            self.assertEqual(self.call('/api/tables', 'POST', {'table_number': 1, 'capacity': capacity}).status_code, 400)
        self.sql.assert_not_called()

    def test_failed_seat_creation_attempts_to_remove_empty_new_table(self):
        self.sql.side_effect = [[], [], [{'table_id': '3'}], RuntimeError('Seat insert failed'), []]
        with self.assertLogs(self.app.logger, level='ERROR'):
            response = self.call('/api/tables', 'POST', {'table_number': 1, 'capacity': 4})
        self.assertEqual(response.status_code, 503)
        self.assertIn('NOT EXISTS', self.sql.call_args.args[0])
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'table_id': 3})

    def test_table_from_another_restaurant_cannot_be_edited(self):
        response = self.call('/api/tables/99', 'PUT', {'table_number': 1, 'capacity': 4, 'status': 'reserved'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.sql.call_count, 1)

    def test_seats_with_orders_cannot_be_removed_by_resizing(self):
        self.sql.side_effect = [[TABLE], [], [{'1': '1'}]]
        response = self.call('/api/tables/3', 'PUT', {'table_number': 1, 'capacity': 2, 'status': 'available'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('order history', response.json['error'])
        self.assertEqual(self.sql.call_count, 3)

    def test_table_with_assignment_cannot_be_made_available(self):
        self.sql.side_effect = [[TABLE], [], [], [], [{'1': '1'}]]
        response = self.call('/api/tables/3', 'PUT', {'table_number': 1, 'capacity': 4, 'status': 'available'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('assignment', response.json['error'])

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

    def test_empty_available_table_can_be_deleted(self):
        self.sql.side_effect = [[TABLE], [], [], [], [], []]
        self.assertEqual(self.call('/api/tables/3', 'DELETE').status_code, 200)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'table_id': 3})

    def test_assignment_rejects_servers_outside_restaurant_or_inactive(self):
        self.sql.side_effect = [[TABLE], []]
        self.assertEqual(self.call('/api/tables/3/assignment', 'PUT', {'employee_id': '8'}).status_code, 400)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'employee_id': 8})
        self.assertEqual(self.sql.call_count, 2)

    def test_assignment_rejects_table_outside_restaurant(self):
        self.assertEqual(self.call('/api/tables/99/assignment', 'PUT', {'employee_id': 8}).status_code, 404)
        self.assertEqual(self.sql.call_count, 1)

    def test_assignment_inserts_replacement_before_retiring_old_assignment(self):
        self.sql.side_effect = [[TABLE], [{'employee_id': '8'}], [], [], []]
        self.assertEqual(self.call('/api/tables/3/assignment', 'PUT', {'employee_id': 8}).status_code, 200)
        self.assertIn('INSERT INTO', self.sql.call_args_list[2].args[0])
        self.assertIn("SET status = 'inactive'", self.sql.call_args_list[3].args[0])
        self.assertIn("SET status = 'occupied'", self.sql.call_args.args[0])

    def test_removing_assignment_keeps_table_status(self):
        self.sql.side_effect = [[TABLE], []]
        self.assertEqual(self.call('/api/tables/3/assignment', 'DELETE').status_code, 200)
        self.assertEqual(self.sql.call_count, 2)
        self.assertIn('server_table_assignment', self.sql.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
