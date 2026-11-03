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
    def test_pending_quantities_can_be_changed(self):
        self.assertEqual(order_changes(ORDER, {'quantity': '3'}), {'quantity': 3, 'status': 'pending'})
        self.assertEqual(order_changes(ORDER, {'quantity': 99})['quantity'], 99)

    def test_invalid_quantities_are_rejected(self):
        for quantity in (0, -1, 100, 1.5, True, '2 OR 1=1', None):
            with self.subTest(quantity=quantity), self.assertRaises(BadRequest):
                order_changes(ORDER, {'quantity': quantity})

    def test_workflow_progresses_in_order(self):
        self.assertEqual(order_changes(ORDER, {'status': 'preparing'})['status'], 'preparing')
        self.assertEqual(order_changes({**ORDER, 'status': 'preparing'}, {'status': 'served'})['status'], 'served')
        for current, target in [('pending', 'served'), ('preparing', 'pending'), ('served', 'preparing')]:
            with self.subTest(current=current, target=target), self.assertRaises(Conflict):
                order_changes({**ORDER, 'status': current}, {'status': target})

    def test_quantity_cannot_change_after_preparation_starts(self):
        for status in ('preparing', 'served'):
            with self.subTest(status=status), self.assertRaises(Conflict):
                order_changes({**ORDER, 'status': status}, {'quantity': 3})

    def test_any_active_item_can_be_cancelled(self):
        for status in ('pending', 'preparing', 'served', 'ordered'):
            self.assertEqual(order_changes({**ORDER, 'status': status}, {'status': 'cancelled'})['status'], 'cancelled')

    def test_closed_and_unknown_orders_cannot_be_reopened(self):
        for status in ('cancelled', 'paid', 'unknown', None):
            with self.subTest(status=status), self.assertRaises(Conflict):
                order_changes({**ORDER, 'status': status}, {'status': 'pending'})

    def test_legacy_ordered_status_is_treated_as_pending(self):
        self.assertEqual(order_changes({**ORDER, 'status': 'ordered'}, {'quantity': '4'}),
                         {'quantity': 4, 'status': 'pending'})

    def test_payment_and_unrelated_order_fields_cannot_be_set(self):
        for data in ({}, {'status': 'paid'}, {'status': []}, {'menu_item_id': 5}, {'seat_id': 4},
                     {'quantity': 2, 'price': '0.01'}):
            with self.subTest(data=data), self.assertRaises(BadRequest):
                order_changes(ORDER, data)


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
            self.assertEqual(self.call(path, method, {}).status_code, 401)
        self.sql.assert_not_called()

    def test_inactive_employees_cannot_order(self):
        self.auth.return_value = [{**MANAGER, 'status': 'inactive'}]
        self.assertEqual(self.call(method='POST', data={'seat_id': 4, 'menu_item_id': 5}).status_code, 403)
        self.sql.assert_not_called()

    def test_other_roles_cannot_mutate_orders(self):
        self.auth.return_value = [{**MANAGER, 'role': 'chef'}]
        self.assertEqual(self.call(method='POST', data={}).status_code, 403)
        self.assertEqual(self.call('/api/orders/11', 'PATCH', {}).status_code, 403)
        self.sql.assert_not_called()

    def test_order_context_limits_data_and_permissions_to_employee_restaurant(self):
        self.auth.return_value = [SERVER]
        tables = [dict(table_id='3', table_number='1', server_id='7'), dict(table_id='6', table_number='2', server_id='8')]
        seats = [dict(seat_id='4', table_id='3', seat_number='1')]
        orders = [ORDER, {**ORDER, 'seat_order_id': '12', 'table_id': '6', 'status': 'ordered'}]
        self.sql.side_effect = [tables, seats, [], orders]
        response = self.call('/api/orders?restaurant_id=999')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['tables'][0]['can_manage'])
        self.assertFalse(response.json['tables'][1]['can_manage'])
        self.assertEqual(response.json['tables'][0]['seats'], seats)
        self.assertTrue(response.json['orders'][0]['can_manage'])
        self.assertFalse(response.json['orders'][1]['can_manage'])
        self.assertEqual(response.json['orders'][1]['status'], 'pending')
        for call in self.sql.call_args_list:
            self.assertEqual(call.args[1], {'restaurant_id': 2})
        self.assertIn('available = true', self.sql.call_args_list[2].args[0])
        self.assertIn('m.restaurant_id = t.restaurant_id', self.sql.call_args_list[3].args[0])

    def test_manager_can_manage_unassigned_tables(self):
        self.sql.side_effect = [[dict(table_id='3', server_id=None)], [], [], [ORDER]]
        response = self.call()
        self.assertTrue(response.json['tables'][0]['can_manage'])
        self.assertTrue(response.json['orders'][0]['can_manage'])

    def test_manager_can_place_item_on_a_seat(self):
        self.sql.side_effect = [[SEAT], [{'menu_item_id': '5'}], []]
        response = self.call(method='POST', data={'seat_id': '4', 'menu_item_id': '5', 'quantity': '3'})
        self.assertEqual(response.status_code, 201)
        sql, values = self.sql.call_args.args
        self.assertIn("'pending'", sql)
        self.assertEqual(values, {'seat_id': 4, 'item_id': 5, 'quantity': 3})

    def test_server_can_order_for_their_current_assignment(self):
        self.auth.return_value = [SERVER]
        self.sql.side_effect = [[SEAT], [{'employee_id': '7'}], [{'menu_item_id': '5'}], []]
        response = self.call(method='POST', data={'seat_id': 4, 'menu_item_id': 5})
        self.assertEqual(response.status_code, 201)
        self.assertIn('ORDER BY assigned_at DESC, assignment_id DESC', self.sql.call_args_list[1].args[0])
        self.assertEqual(self.sql.call_args.args[1]['quantity'], 1)

    def test_server_cannot_order_for_another_server_or_unassigned_table(self):
        self.auth.return_value = [SERVER]
        for assignment in ([], [{'employee_id': '8'}]):
            self.sql.reset_mock()
            self.sql.side_effect = [[SEAT], assignment]
            response = self.call(method='POST', data={'seat_id': 4, 'menu_item_id': 5})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.sql.call_count, 2)

    def test_seat_outside_restaurant_is_not_found(self):
        response = self.call(method='POST', data={'seat_id': 999, 'menu_item_id': 5})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'seat_id': 999})
        self.assertEqual(self.sql.call_count, 1)

    def test_unavailable_or_foreign_menu_item_is_rejected(self):
        self.sql.side_effect = [[SEAT], []]
        response = self.call(method='POST', data={'seat_id': 4, 'menu_item_id': 999})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'item_id': 999})
        self.assertEqual(self.sql.call_count, 2)

    def test_invalid_order_payload_never_reaches_database(self):
        for data in ([], {}, {'seat_id': 4, 'menu_item_id': 5, 'quantity': 0},
                     {'seat_id': True, 'menu_item_id': 5}, {'seat_id': 4, 'menu_item_id': '5 OR 1=1'}):
            self.assertEqual(self.call(method='POST', data=data).status_code, 400)
        self.sql.assert_not_called()

    def test_placing_order_marks_available_table_occupied_before_inserting(self):
        self.sql.side_effect = [[{**SEAT, 'table_status': 'available'}], [{'menu_item_id': '5'}], [], []]
        response = self.call(method='POST', data={'seat_id': 4, 'menu_item_id': 5, 'status': 'paid'})
        self.assertEqual(response.status_code, 201)
        self.assertIn("SET status = 'occupied'", self.sql.call_args_list[2].args[0])
        self.assertEqual(self.sql.call_args_list[2].args[1], {'restaurant_id': 2, 'table_id': 3})
        self.assertIn("'pending'", self.sql.call_args.args[0])

    def test_failed_occupancy_change_does_not_insert_an_order(self):
        self.sql.side_effect = [[{**SEAT, 'table_status': 'available'}], [{'menu_item_id': '5'}], RuntimeError('Unavailable')]
        with self.assertLogs(self.app.logger, level='ERROR'):
            response = self.call(method='POST', data={'seat_id': 4, 'menu_item_id': 5})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.sql.call_count, 3)
        self.assertNotIn('INSERT', self.sql.call_args.args[0])

    def test_pending_quantity_update_is_scoped_and_state_checked(self):
        self.sql.side_effect = [[ORDER], [{'num_affected_rows': '1'}]]
        response = self.call('/api/orders/11', 'PATCH', {'quantity': '4'})
        self.assertEqual(response.status_code, 200)
        sql, values = self.sql.call_args.args
        self.assertIn('status = :previous_status', sql)
        self.assertEqual(values, dict(restaurant_id=2, order_id=11, seat_id=4, previous_status='pending', quantity=4, status='pending'))

    def test_cancellation_keeps_the_order_record(self):
        self.sql.side_effect = [[{**ORDER, 'status': 'served'}], []]
        response = self.call('/api/orders/11', 'PATCH', {'status': 'cancelled'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('History was kept', response.json['message'])
        self.assertIn('UPDATE', self.sql.call_args.args[0])
        self.assertNotIn('DELETE', self.sql.call_args.args[0])
        self.assertEqual(self.sql.call_args.args[1]['status'], 'cancelled')

    def test_legacy_order_can_enter_preparation_without_bulk_migration(self):
        self.sql.side_effect = [[{**ORDER, 'status': 'ordered'}], []]
        self.assertEqual(self.call('/api/orders/11', 'PATCH', {'status': 'preparing'}).status_code, 200)
        self.assertEqual(self.sql.call_args.args[1]['previous_status'], 'ordered')
        self.assertEqual(self.sql.call_args.args[1]['status'], 'preparing')

    def test_closed_order_is_not_written(self):
        for status in ('paid', 'cancelled'):
            self.sql.reset_mock()
            self.sql.side_effect = [[{**ORDER, 'status': status}]]
            self.assertEqual(self.call('/api/orders/11', 'PATCH', {'quantity': 3}).status_code, 409)
            self.assertEqual(self.sql.call_count, 1)

    def test_foreign_order_cannot_be_edited(self):
        self.assertEqual(self.call('/api/orders/999', 'PATCH', {'quantity': 3}).status_code, 404)
        self.assertEqual(self.sql.call_args.args[1], {'restaurant_id': 2, 'order_id': 999})

    def test_server_cannot_change_order_after_table_is_reassigned(self):
        self.auth.return_value = [SERVER]
        self.sql.side_effect = [[ORDER], [{'employee_id': '8'}]]
        self.assertEqual(self.call('/api/orders/11', 'PATCH', {'status': 'cancelled'}).status_code, 403)
        self.assertEqual(self.sql.call_count, 2)

    def test_server_can_update_their_assigned_tables_order(self):
        self.auth.return_value = [SERVER]
        self.sql.side_effect = [[ORDER], [{'employee_id': '7'}], []]
        self.assertEqual(self.call('/api/orders/11', 'PATCH', {'status': 'preparing'}).status_code, 200)

    def test_raced_status_update_reports_a_conflict(self):
        self.sql.side_effect = [[ORDER], [{'num_affected_rows': '0'}]]
        response = self.call('/api/orders/11', 'PATCH', {'quantity': 3})
        self.assertEqual(response.status_code, 409)
        self.assertIn('Refresh', response.json['error'])


if __name__ == '__main__':
    unittest.main()
