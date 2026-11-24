import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

USER = dict(employee_id='7', restaurant_id='2', first_name='Alex', last_name='Chen', role='manager', username='alex', status='active')
TABLE = dict(table_id='3', table_number='1', capacity='2', status='available')
SEATS = [dict(seat_id='11', seat_number='1'), dict(seat_id='12', seat_number='4')]


class SeatTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app({'TESTING': True}).test_client()
        self.headers = {'X-Restaurant-Authorization': 'Basic ' + base64.b64encode(b'alex:simple').decode()}
        auth = patch('app.run_sql', return_value=[USER])
        auth.start()
        self.addCleanup(auth.stop)
        sql = patch('management.run_sql')
        self.sql = sql.start()
        self.addCleanup(sql.stop)

    def test_individual_seats_can_be_added_renumbered_and_removed(self):
        self.sql.side_effect = [[TABLE], SEATS, [], []]
        response = self.client.post('/api/tables/3/seats', json={'seat_number': 6}, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.sql.call_args_list[-2].args[1], {'table_id': 3, 'seat_number': 6})
        self.assertIn('COUNT(*)', self.sql.call_args.args[0])
        self.sql.side_effect = [[TABLE], SEATS, [], []]
        response = self.client.put('/api/tables/3/seats/12', json={'seat_number': 7}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sql.call_args.args[1], {'table_id': 3, 'seat_id': 12, 'seat_number': 7})
        self.sql.side_effect = [[TABLE], SEATS, [], [], []]
        response = self.client.delete('/api/tables/3/seats/12', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn('COUNT(*)', self.sql.call_args.args[0])
        self.assertEqual(self.sql.call_args.args[1], {'table_id': 3, 'restaurant_id': 2})

    def test_history_is_protected_and_table_edits_preserve_custom_seat_numbers(self):
        self.sql.side_effect = [[TABLE], SEATS, [{'1': '1'}]]
        response = self.client.delete('/api/tables/3/seats/12', headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.sql.call_count, 3)
        self.sql.reset_mock()
        self.sql.side_effect = [[TABLE], [], SEATS, [], [], []]
        response = self.client.put('/api/tables/3', json={'table_number': 1, 'capacity': 2, 'status': 'available'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        for call in self.sql.call_args_list:
            self.assertNotIn('INSERT INTO', call.args[0])
            self.assertNotIn('DELETE FROM', call.args[0])


if __name__ == '__main__':
    unittest.main()
