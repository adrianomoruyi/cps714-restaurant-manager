import base64
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from werkzeug.exceptions import BadRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from billing import DEFAULT_PLAN, split_bill

USER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen', role='manager', username='alex', status='active')
ITEMS = [dict(seat_order_id='11', seat_id='4', seat_number='1', menu_item_name='Soup', unit_price='10.01', quantity='1'),
         dict(seat_order_id='12', seat_id='5', seat_number='2', menu_item_name='Tea', unit_price='5.00', quantity='1')]
TABLE = dict(table_id='3', table_number='1')


class BillTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app({'TESTING': True}).test_client()
        self.headers = {'X-Restaurant-Authorization': 'Basic ' + base64.b64encode(b'alex:simple').decode()}
        auth = patch('app.run_sql', return_value=[USER])
        self.auth = auth.start()
        self.addCleanup(auth.stop)
        sql = patch('billing.run_sql')
        self.sql = sql.start()
        self.addCleanup(sql.stop)

    def test_seat_group_and_equal_splits_preserve_every_cent_after_discount(self):
        for mode, groups, totals in [
            ('seats', [], ['9.01', '4.50']),
            ('groups', [['4', '5']], ['13.51']),
            ('equal', [], ['4.51', '4.50', '4.50']),
        ]:
            with self.subTest(mode=mode):
                result = split_bill(ITEMS, {**DEFAULT_PLAN, 'mode': mode, 'people': 3, 'groups': groups,
                                            'discount_kind': 'percentage', 'discount_value': '10'})
                self.assertEqual(result['subtotal'], '15.01')
                self.assertEqual(result['discount_total'], '1.50')
                self.assertEqual([share['total'] for share in result['bills']], totals)
                self.assertEqual(sum(Decimal(share['total']) for share in result['bills']), Decimal(result['total']))
        fixed = split_bill(ITEMS, {**DEFAULT_PLAN, 'discount_kind': 'fixed', 'discount_value': '100'})
        self.assertEqual(fixed['total'], '0.00')

    def test_invalid_groups_and_discount_values_are_rejected(self):
        for groups in ([['4']], [['4'], ['4', '5']], [['4', '5', '999']]):
            with self.subTest(groups=groups), self.assertRaises(BadRequest):
                split_bill(ITEMS, {**DEFAULT_PLAN, 'mode': 'groups', 'groups': groups})
        for value in ('101', '-1', 'NaN', '1.001'):
            with self.subTest(discount=value), self.assertRaises(BadRequest):
                split_bill(ITEMS, {**DEFAULT_PLAN, 'discount_kind': 'percentage', 'discount_value': value})

    def test_assigned_server_can_save_split_but_cannot_approve_or_inject_discount(self):
        self.auth.return_value = [{**USER, 'role': 'server'}]
        self.sql.side_effect = [[TABLE], [{'employee_id': '7'}], [], ITEMS, []]
        response = self.client.put('/api/bills/3/split', json={'mode': 'equal', 'people': 3}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        query, values = self.sql.call_args.args
        self.assertIn('MERGE INTO', query)
        self.assertEqual(values['people'], 3)
        self.assertNotIn('discount_value', values)

        for suffix, payload, assignment, status in [
            ('discount', {'kind': 'fixed', 'value': '1', 'reason': 'Server attempt'}, '7', 403),
            ('split', {'mode': 'equal', 'people': 2, 'discount_value': '99'}, '7', 400),
            ('split', {'mode': 'equal', 'people': 2}, '8', 403),
        ]:
            with self.subTest(suffix=suffix, assignment=assignment):
                self.sql.reset_mock()
                self.sql.side_effect = [[TABLE], [{'employee_id': assignment}]]
                response = self.client.put('/api/bills/3/' + suffix, json=payload, headers=self.headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(self.sql.call_count, 2)

    def test_manager_discount_is_saved_with_approver_and_used_when_bill_is_reopened(self):
        self.sql.side_effect = [[TABLE], [], ITEMS, []]
        response = self.client.put('/api/bills/3/discount', json={'kind': 'fixed', 'value': '2.01', 'reason': 'Service recovery'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sql.call_args.args[1], dict(table_id=3, discount_kind='fixed', discount_value='2.01',
                                                        discount_reason='Service recovery', discount_employee_id=7))
        self.sql.side_effect = [[TABLE], [dict(split_mode='equal', people='2', discount_kind='fixed', discount_value='2.01', discount_reason='Service recovery', discount_employee_id='7')], ITEMS]
        response = self.client.get('/api/bills/3', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['total'], '13.00')
        self.assertEqual([share['total'] for share in response.json['bills']], ['6.50', '6.50'])
        self.assertEqual(self.sql.call_args.args[1], {'table_id': 3, 'restaurant_id': 2})


if __name__ == '__main__':
    unittest.main()
