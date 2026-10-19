"""Shared Databricks SQL access for the API and sprint setup script."""

import os
import re
from functools import lru_cache

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout, StatementParameterListItem

WAREHOUSE_ID = os.environ.get('DATABRICKS_WAREHOUSE_ID', 'af22ac66ae5c1302')
CATALOG = os.environ.get('DATABRICKS_CATALOG', 'cps714')
SCHEMA = os.environ.get('DATABRICKS_SCHEMA', 'restaurant_manager')
if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in (CATALOG, SCHEMA)):
    raise ValueError('Database catalog and schema must be simple SQL identifiers.')
FULL_SCHEMA = f'{CATALOG}.{SCHEMA}'


@lru_cache(maxsize=1)
def workspace():
    return WorkspaceClient()


def run_sql(statement, parameters=None):
    """Bind form values separately from SQL and return rows as dictionaries."""
    bound = [StatementParameterListItem(name=name, value=str(value),
             type='BIGINT' if isinstance(value, int) else 'STRING')
             for name, value in (parameters or {}).items()]
    try:
        api = workspace().statement_execution
        response = api.execute_statement(
            warehouse_id=WAREHOUSE_ID, catalog=CATALOG, schema=SCHEMA,
            statement=statement, parameters=bound, wait_timeout='50s',
            on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
        )
        state = response.status.state if response.status else None
        state_value = state.value if hasattr(state, 'value') else str(state)
        if state_value != 'SUCCEEDED':
            raise RuntimeError(f'SQL failed with state {state_value}.')
        if not response.result or not response.manifest:
            return []
        if response.manifest.truncated:
            raise RuntimeError('SQL result was truncated.')
        columns = [column.name for column in response.manifest.schema.columns]
        rows = []
        chunk = response.result
        while chunk:
            rows.extend(dict(zip(columns, row)) for row in (chunk.data_array or []))
            if chunk.next_chunk_index is None:
                break
            chunk = api.get_statement_result_chunk_n(response.statement_id, chunk.next_chunk_index)
        return rows
    except Exception as exc:
        raise RuntimeError('Databricks SQL execution failed.') from exc
