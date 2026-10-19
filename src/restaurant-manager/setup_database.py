"""Run after the original database creation notebook; safe to rerun."""

from database import FULL_SCHEMA, run_sql


def setup_database():
    columns = {row['col_name'] for row in run_sql(f'DESCRIBE TABLE {FULL_SCHEMA}.employee')}
    missing = [f'{name} STRING' for name in ('username', 'password') if name not in columns]
    if missing:
        run_sql(f"ALTER TABLE {FULL_SCHEMA}.employee ADD COLUMNS ({', '.join(missing)})")

    # The dashboard reads this table, originally created by the operations notebooks.
    run_sql(f'''CREATE TABLE IF NOT EXISTS {FULL_SCHEMA}.server_table_assignment (
        assignment_id BIGINT GENERATED ALWAYS AS IDENTITY,
        table_id BIGINT NOT NULL,
        employee_id BIGINT NOT NULL,
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status STRING DEFAULT 'active',
        CONSTRAINT pk_server_table_assignment PRIMARY KEY (assignment_id),
        CONSTRAINT fk_assignment_table FOREIGN KEY (table_id)
            REFERENCES {FULL_SCHEMA}.restaurant_table (table_id),
        CONSTRAINT fk_assignment_employee FOREIGN KEY (employee_id)
            REFERENCES {FULL_SCHEMA}.employee (employee_id)
    ) TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')''')


if __name__ == '__main__':
    setup_database()
    print('Sprint setup complete. Create an account on the registration page.')
