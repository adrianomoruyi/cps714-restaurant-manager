import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.exceptions import BadRequest, Conflict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from orders import order_changes

MANAGER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen',
               role='manager', username='alex', status='active')
SERVER = {**MANAGER, 'role': 'server'}
ORDER = dict(seat_order_id='11', seat_id='4', table_id='3', quantity='2', status='pending')
SEAT = dict(seat_id='4', table_id='3', table_status='occupied')


class OrderRuleTests(unittest.TestCase):
    def test_order_can_be_edited_prepared_served_and_cancelled(self):
        for initial_status in ('pending', 'ordered'):
            with self.subTest(initial_status=initial_status):
                order = {**ORDER, 'status': initial_status}
                order = order_changes(order, {'quantity': '3'})
                self.assertEqual(order, {'quantity': 3, 'status': 'pending'})
                for status in ('preparing', 'served', 'cancelled'):
                    order = order_changes(order, {'status': status})
                    self.assertEqual(order, {'quantity': 3, 'status': status})

    def test_order_quantity_is_a_whole_number_from_one_to_99(self):
        for quantity in (1, 99):
            self.assertEqual(order_changes(ORDER, {'quantity': quantity})['quantity'], quantity)
        for quantity in (0, -1, 100, 1.5, True):
            with self.subTest(quantity=quantity), self.assertRaises(BadRequest):
                order_changes(ORDER, {'quantity': quantity})

    def test_invalid_workflow_changes_are_rejected(self):
        cases = [
            ('pending', {'status': 'served'}),
            ('preparing', {'status': 'pending'}),
            ('preparing', {'quantity': 4}),
        ]
        for status, changes in cases:
            with self.subTest(status=status, changes=changes), self.assertRaises(Conflict):
                order_changes({**ORDER, 'status': status}, changes)

    def test_paid_and_cancelled_items_cannot_be_reopened_or_edited(self):
        for status in ('paid', 'cancelled'):
            for changes in ({'status': 'pending'}, {'quantity': 3}):
                with self.subTest(status=status, changes=changes), self.assertRaises(Conflict):
                    order_changes({**ORDER, 'status': status}, changes)


class OrderApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True})
        self.client = self.app.test_client()
        auth_patch = patch('app.run_sql', return_value=[MANAGER])
        self.auth = auth_patch.start()
        self.addCleanup(auth_patch.stop)
        sql_patch = patch('orders.run_sql', return_value=[])
        self.sql = sql_patch.start()
        self.addCleanup(sql_patch.stop)
        self.headers = {'X-Restaurant-Authorization': 'Basic ' + base64.b64encode(b'alex:simple').decode()}

    def call(self, path='/api/orders', method='GET', data=None):
        return self.client.open(path, method=method, json=data, headers=self.headers)

    def test_order_routes_require_login(self):
        self.auth.return_value = []
        for path, method in [('/api/orders', 'GET'), ('/api/orders', 'POST'), ('/api/orders/11', 'PATCH')]:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(path, method, {}).status_code, 401)
        self.sql.assert_not_called()

    def test_order_list_is_scoped_and_marks_only_assigned_tables_editable(self):
        self.auth.return_value = [SERVER]
        tables = [dict(table_id='3', server_id='7'), dict(table_id='6', server_id='8')]
        seats = [dict(seat_id='4', table_id='3', seat_number='1')]
        orders = [ORDER, {**ORDER, 'seat_order_id': '12', 'table_id': '6'}]
        self.sql.side_effect = [tables, seats, [], orders]
        response = self.call('/api/orders?restaurant_id=999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([table['can_manage'] for table in response.json['tables']], [True, False])
        self.assertEqual([order['can_manage'] for order in response.json['orders']], [True, False])
        self.assertEqual(response.json['tables'][0]['seats'], seats)
        for call in self.sql.call_args_list:
            self.assertEqual(call.args[1], {'restaurant_id': 2})

    def test_manager_and_assigned_server_can_place_an_order(self):
        for user in (MANAGER, SERVER):
            with self.subTest(role=user['role']):
                self.auth.return_value = [user]
                results = [[{**SEAT, 'table_status': 'available'}]]
                if user['role'] == 'server':
                    results.append([{'employee_id': '7'}])
                self.sql.side_effect = results + [[{'menu_item_id': '5'}], [], []]
                response = self.call(method='POST', data={'seat_id': '4', 'menu_item_id': '5', 'quantity': '3'})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(self.sql.call_args.args[1], {'seat_id': 4, 'item_id': 5, 'quantity': 3})
                self.assertIn("'pending'", self.sql.call_args.args[0])
                self.assertIn("SET status = 'occupied'", self.sql.call_args_list[-2].args[0])
                self.sql.reset_mock()

    def test_server_cannot_create_or_change_orders_for_another_servers_table(self):
        self.auth.return_value = [SERVER]
        cases = [
            ('/api/orders', 'POST', {'seat_id': 4, 'menu_item_id': 5}, SEAT),
            ('/api/orders/11', 'PATCH', {'status': 'cancelled'}, ORDER),
        ]
        for path, method, payload, record in cases:
            with self.subTest(method=method):
                self.sql.reset_mock()
                self.sql.side_effect = [[record], [{'employee_id': '8'}]]
                self.assertEqual(self.call(path, method, payload).status_code, 403)
                self.assertEqual(self.sql.call_count, 2)

    def test_unavailable_menu_items_cannot_be_ordered(self):
        self.sql.side_effect = [[SEAT], []]
        response = self.call(method='POST', data={'seat_id': 4, 'menu_item_id': 5})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'item_id': 5})
        self.assertEqual(self.sql.call_count, 2)

    def test_seats_and_orders_outside_restaurant_cannot_be_changed(self):
        cases = [
            ('/api/orders', 'POST', {'seat_id': 999, 'menu_item_id': 5}),
            ('/api/orders/999', 'PATCH', {'quantity': 3}),
        ]
        for path, method, payload in cases:
            with self.subTest(method=method):
                self.sql.reset_mock()
                self.sql.side_effect = [[]]
                self.assertEqual(self.call(path, method, payload).status_code, 404)
                self.assertEqual(self.sql.call_count, 1)
                self.assertEqual(self.sql.call_args.args[1]['restaurant_id'], 2)

    def test_quantity_updates_and_cancellation_preserve_order_history(self):
        cases = [({'quantity': '4'}, 4, 'pending'), ({'status': 'cancelled'}, 2, 'cancelled')]
        for changes, quantity, status in cases:
            with self.subTest(changes=changes):
                self.sql.side_effect = [[ORDER], [{'num_affected_rows': '1'}]]
                response = self.call('/api/orders/11', 'PATCH', changes)
                self.assertEqual(response.status_code, 200)
                sql, values = self.sql.call_args.args
                self.assertIn('UPDATE', sql)
                self.assertNotIn('DELETE', sql)
                self.assertEqual(values, dict(restaurant_id=2, order_id=11, seat_id=4,
                                             previous_status='pending', quantity=quantity, status=status))


if __name__ == '__main__':
    unittest.main()
