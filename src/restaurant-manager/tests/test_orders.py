import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.exceptions import BadRequest

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


if __name__ == '__main__':
    unittest.main()
