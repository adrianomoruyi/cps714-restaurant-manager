"""Run after the original database creation notebook; safe to rerun."""

from database import FULL_SCHEMA, run_sql


def setup_database():
    columns = {row['col_name'] for row in run_sql(f'DESCRIBE TABLE {FULL_SCHEMA}.employee')}
    missing = [f'{name} STRING' for name in ('username', 'password') if name not in columns]
    if missing:
        run_sql(f"ALTER TABLE {FULL_SCHEMA}.employee ADD COLUMNS ({', '.join(missing)})")

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

    # One current plan per table. Missing fields in an initial MERGE use API defaults.
    run_sql(f'''CREATE TABLE IF NOT EXISTS {FULL_SCHEMA}.bill_plan (
        table_id BIGINT NOT NULL,
        split_mode STRING,
        people INT,
        groups_json STRING,
        discount_kind STRING,
        discount_value DECIMAL(12,2),
        discount_reason STRING,
        discount_employee_id BIGINT,
        updated_at TIMESTAMP
    )''')

    # Undo the removed role if the earlier promotion command was used.
    run_sql(f"UPDATE {FULL_SCHEMA}.employee SET role = 'manager' WHERE role = 'admin'")


if __name__ == '__main__':
    setup_database()
    print('Database setup complete.')
