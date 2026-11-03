# CPS714 Restaurant Manager

The current app includes **registration, login, logout, a read-only dashboard, menu management, table/seat management, server assignments, and seat-level orders**. The frontend uses React and Vite; Flask provides a JSON API backed by Databricks SQL. Managers make management changes and manage all orders in their restaurant; servers can manage orders for their assigned tables and view the menu, floor layout, and assignments.

Checkout (together or per seat), manager discounts, and employee/restaurant management are planned for later batches. Reports are excluded.

## Structure

```text
src/restaurant-manager/
  app.py                 Flask API and serving the built React app
  management.py          Menu, table/seat, and assignment API with role checks
  orders.py              Order entry, quantity/status rules, and table permissions
  database.py            Databricks connection and parameterized queries
  setup_database.py      Adds the login columns and dashboard assignment table
  package.json           Databricks deployment build entry point
  app.yaml               Databricks app startup configuration
  frontend/
    src/App.jsx          Login, registration, and dashboard components
    src/Management.jsx   Menu, tables/seats, and assignment pages
    src/Orders.jsx       Seat-level order entry, service status, and history
    src/useRestaurantResource.js  Shared loading and saving behavior
    src/api.js           Requests to the Flask API
    src/styles.css       Responsive page styles
    vite.config.js       Local /api proxy to Flask on port 8000
  tests/                 Backend tests with mocked database access
src/querying/            Original database and CRUD notebooks (reference)
src/helpers/             Original operations and checkout notebook (reference)
```

The notebooks are retained unchanged as reference. The running app adapts their menu, table, assignment, and order logic into Flask endpoints; it does not execute the notebooks.

## Management features and permissions

| Feature | Manager | Server |
| --- | --- | --- |
| Dashboard, menu, tables/seats, server assignments | View | View |
| Menu items | Add, edit, change availability, delete unused items | View |
| Tables and seats | Create, resize, change table number/status, delete unused tables | View |
| Server assignments | Assign, reassign, remove | View |
| Order items | Add, change pending quantities, progress status, cancel at any table in the restaurant | Same actions for assigned tables; view other tables |

Permissions are checked in Flask on every request, using the current employee record. All reads and changes are limited to the employee's restaurant. The classroom registration form still supports choosing manager or server, as before.

- Prices are in CAD and support up to two decimal places. Menu items with existing orders cannot be deleted; mark them unavailable instead.
- Tables have a unique number within a restaurant and a capacity of 1–30. Creating or editing capacity generates numbered seats from 1 to capacity. Reducing capacity removes the highest numbered seats only when the table is available and those seats have no order history. Existing seats within capacity keep their IDs.
- Only available tables without orders or active assignments can be deleted. A table with active orders or an assignment cannot be marked available.
- Assigning a server marks a table occupied. Only active servers from the same restaurant can be assigned. Reassignment retires the previous active assignment. Removing an assignment preserves table status; mark it available separately when service is finished.

## Orders

Open **Orders**, choose a table, then select its seat, an available menu item, and a quantity from 1–99. Adding an item marks the table occupied. Managers can order for any table in their restaurant; servers need the latest active assignment to that table. The backend rechecks these permissions on every change, including after reassignment.

- New items start **pending**, then move to **preparing**, then **served**. Status cannot move backwards or skip preparation.
- Quantities can be changed while an item is pending. Preparation and serving lock the quantity.
- Any active item can be cancelled after confirmation. Cancellation preserves the record instead of deleting it.
- Cancelled and paid items are read-only. Enable **Show cancelled and paid items** to view them. Order controls cannot mark an item paid; checkout is a later feature.
- Existing notebook items with status `ordered` appear as pending and can enter this workflow without a bulk migration. Other unrecognized statuses are read-only history.
- Only available items from the employee's restaurant can be added. Existing order items remain visible when their menu item becomes unavailable.
- Unit prices and line totals reflect the current menu prices, matching the original schema. Historical price snapshots and payment records will belong to checkout.

Orders use the existing `seat_order_item` table; no new database columns or notebook changes are required. The app identity needs SELECT, INSERT, and UPDATE access to the order table and UPDATE access to restaurant tables.

These features use the original database tables. If starting from a new database, run the creation/population notebooks and `setup_database.py` as described below. The app identity needs SELECT access plus INSERT, UPDATE, and DELETE access for the management tables. Multi-step table and assignment changes use separate Databricks SQL statements; they do not provide transactions across tables.

## Login requirements

- Databricks authentication with access to the SQL warehouse and `cps714.restaurant_manager` tables.
- An existing restaurant to select during registration.
- `username` and `password` string columns on `employee`, in addition to its existing employee, restaurant, name, role, and status fields.
- An employee with credentials and `status = 'active'`. Registering creates this account; the original sample employees have no credentials.

For this classroom prototype, passwords remain plain text in the database as requested. React holds the current user and credentials only in memory. Dashboard requests send those credentials in a separate `X-Restaurant-Authorization` header so Flask can look up the employee's restaurant without creating app session cookies or tokens. The standard `Authorization` header is reserved for the Databricks proxy. API requests allow same-origin cookies so the platform can recognize your existing Databricks sign-in; these are managed by Databricks, not our employee login. Logging out clears React's state; refreshing or reopening the page requires logging in again. New usernames are stored in lowercase and login is case-insensitive for usernames. Passwords are matched exactly.

## Install and prepare the database

Use Python 3.10+ and Node.js 22.12+ (Node 24 works).

From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/restaurant-manager/requirements.txt
```

Configure Databricks authentication on your machine, for example with `databricks auth login --host https://YOUR-WORKSPACE`. The SDK can also use your existing Databricks CLI profile or supported environment credentials. Keep credentials out of frontend code.

If the database is new, run these notebooks in Databricks in order:

1. `src/querying/Create databases.dbquery.ipynb`
2. `src/querying/Populate tables.dbquery.ipynb`

Then, from the activated environment:

```sh
cd src/restaurant-manager
python setup_database.py
```

This script adds missing `username` and `password` columns and creates `server_table_assignment` if needed. It preserves existing rows and credentials and can be rerun. It does not create demo credentials or modify existing passwords. If you already have a populated database, run only this setup script.

The default warehouse, catalog, and schema match the original project. Optional overrides are listed in `.env.example`. To use them, copy it to `.env`, edit it, and load it in each backend terminal:

```sh
set -a
source .env
set +a
```

## Run locally

In one terminal, with the Python environment activated:

```sh
cd src/restaurant-manager
python app.py
```

In another terminal:

```sh
cd src/restaurant-manager/frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**, register an account, and log in. Vite proxies API calls to Flask on port 8000. The dashboard shows tables, capacity, status, and assigned servers for the logged-in employee's restaurant. Use the navigation to open Menu, Tables & seats, Server assignments, and Orders. Log in as a manager to create tables/menu items and assign servers, then use a server account to take orders for its tables.

## Run the built app

Build the frontend first:

```sh
cd src/restaurant-manager/frontend
npm ci
npm run build
cd ..
python app.py
```

Open **http://127.0.0.1:8000**. Flask serves both the built React frontend and API. `npm run preview` previews frontend assets only; use Flask to run the complete built app.

## Deploy from GitHub to Databricks

Set the app's Git source to this repository, branch `main`, with **`src/restaurant-manager` as the app directory** (the folder containing `app.yaml`, `requirements.txt`, and the deployment `package.json`).

Databricks automatically performs these steps on deployment:

1. Detects `package.json` in the app directory and installs Node dependencies.
2. Installs the Python dependencies from `requirements.txt`.
3. Runs `npm run build`. Our build script installs the frontend's locked dependencies, including Vite even when `NODE_ENV=production`, and generates `frontend/dist/`.
4. Starts Flask using `python app.py`, as specified in `app.yaml`.

**No local frontend build or committed build files are needed for GitHub deployments.** Build output remains ignored by Git. After syncing the latest commit, deploy/redeploy the app in Databricks. Database setup and app permissions are still required as described above.

You can verify the same deployment build locally from `src/restaurant-manager` with `npm run build`.

Reference: [Databricks deployment logic](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/deploy).

## Core tests

From the repository root with the virtual environment active:

```sh
python -m unittest discover -s src/restaurant-manager/tests -v
cd src/restaurant-manager/frontend
npm test
```

The suite covers the sprint's basic workflows and permissions. It includes pure unit tests for order rules, Flask route tests with mocked database calls, and React component tests for the main user workflows. Both suites intentionally sample core behavior rather than testing every validation case, database adapter detail, or management operation.

| Test file | Tests | What they demonstrate |
| --- | ---: | --- |
| `tests/test_api.py` | 4 | Successful login, rejected credentials/inactive employees, registration, and authenticated dashboard access scoped to the employee's restaurant |
| `tests/test_management.py` | 3 | Manager-only changes, menu creation with bound values, and table creation with numbered seats |
| `tests/test_orders.py` | 3 | Order editing/preparation/serving/cancellation, quantity limits, and blocking changes to another server's table |
| `frontend/src/api.test.js` | 1 | Regression coverage for Databricks sign-in cookies |
| `frontend/src/App.test.jsx` | 3 | Registration, failed login, and successful login → dashboard → logout |
| `frontend/src/Management.test.jsx` | 2 | Menu creation and server assignment/removal in the UI |
| `frontend/src/Orders.test.jsx` | 2 | Seat-level ordering and read-only access to another server's table |

There are **18 core tests: 10 Python and 8 frontend**. Small data-driven cases check shared rules such as manager permissions and quantity limits. Each test targets a basic workflow or access rule.

The Python tests use `unittest`; frontend tests use Vitest and React Testing Library. Database and HTTP calls are mocked, so tests need no Databricks credentials and do not access or change the live database. They demonstrate application logic and UI behavior; live SQL execution, Databricks permissions, and deployment connectivity still need a deployed check.

For a class demonstration, run both commands above, then show three representative tests: `test_all_mutations_require_manager_role`, `test_dashboard_requires_login_and_uses_employees_restaurant`, and `test_order_can_be_edited_prepared_served_and_cancelled`. Together they explain role permissions, restaurant isolation, and the main business workflow.

`npm run build` from the frontend directory is a separate deployment/build check, rather than a unit test.
