import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import run_sql


class DatabaseTests(unittest.TestCase):
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
