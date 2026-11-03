import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import run_sql


class DatabaseTests(unittest.TestCase):
    def response(self, **changes):
        values = dict(
            status=Obj(state='SUCCEEDED'), statement_id='statement-1',
            manifest=Obj(truncated=False, schema=Obj(columns=[Obj(name='server_name')])),
            result=Obj(data_array=[[None]], next_chunk_index=None),
        )
        return Obj(**{**values, **changes})

    @patch('database.workspace')
    def test_bound_parameters_and_multiple_result_chunks(self, workspace):
        api = workspace.return_value.statement_execution
        api.execute_statement.return_value = Obj(
            status=Obj(state='SUCCEEDED'), statement_id='statement-1',
            manifest=Obj(truncated=False, schema=Obj(columns=[Obj(name='table_id')])),
            result=Obj(data_array=[['1']], next_chunk_index=1),
        )
        api.get_statement_result_chunk_n.return_value = Obj(data_array=[['2']], next_chunk_index=None)
        rows = run_sql('SELECT :name, :restaurant_id', {'name': "O'Neil", 'restaurant_id': 2})
        self.assertEqual(rows, [{'table_id': '1'}, {'table_id': '2'}])
        params = api.execute_statement.call_args.kwargs['parameters']
        self.assertEqual([(p.name, p.value, p.type) for p in params],
                         [('name', "O'Neil", 'STRING'), ('restaurant_id', '2', 'BIGINT')])
        api.get_statement_result_chunk_n.assert_called_once_with('statement-1', 1)

    @patch('database.workspace')
    def test_failed_or_unfinished_query_is_not_treated_as_empty_success(self, workspace):
        for state in ('FAILED', 'PENDING', 'CANCELED'):
            workspace.return_value.statement_execution.execute_statement.return_value = Obj(status=Obj(state=state))
            with self.assertRaises(RuntimeError):
                run_sql('SELECT 1')

    @patch('database.workspace')
    def test_null_values_are_preserved_for_unassigned_servers(self, workspace):
        workspace.return_value.statement_execution.execute_statement.return_value = self.response()
        self.assertEqual(run_sql('SELECT server_name FROM tables'), [{'server_name': None}])

    @patch('database.workspace')
    def test_successful_insert_without_result_rows_returns_empty_list(self, workspace):
        workspace.return_value.statement_execution.execute_statement.return_value = self.response(
            result=None, manifest=None)
        self.assertEqual(run_sql('INSERT INTO employee VALUES (:name)', {'name': 'Alex'}), [])

    @patch('database.workspace')
    def test_truncated_result_is_rejected_instead_of_returning_partial_data(self, workspace):
        workspace.return_value.statement_execution.execute_statement.return_value = self.response(
            manifest=Obj(truncated=True))
        with self.assertRaises(RuntimeError) as caught:
            run_sql('SELECT * FROM tables')
        self.assertIn('truncated', str(caught.exception.__cause__))

    @patch('database.workspace')
    def test_connection_error_preserves_cause_for_server_logs(self, workspace):
        original = ConnectionError('Warehouse is unreachable')
        workspace.side_effect = original
        with self.assertRaises(RuntimeError) as caught:
            run_sql('SELECT 1')
        self.assertIs(caught.exception.__cause__, original)

    @patch('database.workspace')
    def test_missing_query_status_is_rejected(self, workspace):
        workspace.return_value.statement_execution.execute_statement.return_value = self.response(status=None)
        with self.assertRaises(RuntimeError):
            run_sql('SELECT 1')

    @patch('database.workspace')
    def test_later_chunk_failure_does_not_return_an_incomplete_dashboard(self, workspace):
        api = workspace.return_value.statement_execution
        api.execute_statement.return_value = self.response(
            result=Obj(data_array=[['Alex']], next_chunk_index=1))
        original = ConnectionError('Could not retrieve the next result chunk')
        api.get_statement_result_chunk_n.side_effect = original
        with self.assertRaises(RuntimeError) as caught:
            run_sql('SELECT server_name FROM tables')
        self.assertIs(caught.exception.__cause__, original)
