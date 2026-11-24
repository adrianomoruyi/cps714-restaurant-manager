# CPS714 Restaurant Manager

The app includes **registration/login, a dashboard, menu and table/seat management, server assignments, seat-level orders, bill splitting, manager-approved discounts, employee management, and restaurant configuration**. React and Vite provide the frontend; Flask provides a JSON API backed by Databricks SQL. Managers manage their restaurant; servers handle orders and bill splits for assigned tables; managers can configure their restaurant and create restaurants for new teams. The only app roles are manager and server.

Actual payment processing, payroll, hardware, inventory, and reports are outside this app’s scope. Bills show amounts owed and save split settings; they do not collect payments or mark orders paid.

## Structure

```text
src/restaurant-manager/
  app.py                 Flask API and serving the built React app
  management.py          Menu, table/seat, and assignment API with role checks
  orders.py              Order entry, quantity/status rules, and table permissions
  billing.py             Bill totals, saved splits, and approved discounts
  administration.py      Restaurant and employee CRUD with role checks
  database.py            Databricks connection and parameterized queries
  setup_database.py      Idempotent database additions and role recovery
  package.json           Databricks deployment build entry point
  app.yaml               Databricks app startup configuration
  frontend/
    src/App.jsx          Login, registration, and dashboard components
    src/Management.jsx   Menu, tables/seats, and assignment pages
    src/Orders.jsx       Seat-level order entry, service status, and history
    src/Billing.jsx      Separate, grouped-seat, and equal bill splits
    src/Administration.jsx  Employee and restaurant management
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
| Restaurant configuration | Edit own restaurant’s contact details; create restaurants for new teams | — |
| Dashboard, menu, floor, assignments, bills | View own restaurant | View own restaurant |
| Menu items | Add, edit, toggle availability, delete unused items | View |
| Tables and individual seats | Create, edit, resize, delete unused tables/seats | View |
| Server assignments | Assign, reassign, remove | View |
| Orders and bill splits | Manage all tables in own restaurant | Manage assigned tables; view other tables |
| Discounts | Approve, change, remove | View approved discount |
| Employees | Manage own restaurant’s employees | — |

Flask checks permissions against the current employee record on every request. All operational data is scoped to that employee’s restaurant. The app supports only **manager** and **server**, including in employee creation/editing and public registration. Accounts cannot switch restaurants.

- Prices are in CAD and support up to two decimal places. Menu items with existing orders cannot be deleted; mark them unavailable instead.
- Tables have a unique number within a restaurant and a capacity of 1–30. Creation generates numbered seats. Increasing capacity fills unused seat numbers; reducing it removes the highest numbered seats only when the table is available and those seats have no order history. Saving an unchanged capacity preserves individual seat numbers and IDs.
- Under **Tables & seats**, use **Add seat**, or **Edit** beside a seat to renumber or delete it. Seat numbers are unique within a table and range from 1–99; a table still holds at most 30 seats and must keep at least one. Adding/removing a seat updates capacity. Renumbering/deletion requires an available table and a seat without order history.
- Only available tables without orders or active assignments can be deleted. A table with active orders or an assignment cannot be marked available.
- Assigning a server marks a table occupied. Only active servers from the same restaurant can be assigned. Reassignment retires the previous active assignment. Removing an assignment preserves table status; mark it available separately when service is finished.

## Orders

Open **Orders**, choose a table, then select its seat, an available menu item, and a quantity from 1–99. Adding an item marks the table occupied. Managers can order for any table in their restaurant; servers need the latest active assignment to that table. The backend rechecks these permissions on every change, including after reassignment.

- New items start **pending**, then move to **preparing**, then **served**. Status cannot move backwards or skip preparation.
- Quantities can be changed while an item is pending. Preparation and serving lock the quantity.
- Any active item can be cancelled after confirmation. Cancellation preserves the record instead of deleting it.
- Cancelled and paid items are read-only. Enable **Show cancelled and paid items** to view them. The app does not mark items paid or collect payments; existing paid records from the notebooks remain visible in history.
- Existing notebook items with status `ordered` appear as pending and can enter this workflow without a bulk migration. Other unrecognized statuses are read-only history.
- Only available items from the employee's restaurant can be added. Existing order items remain visible when their menu item becomes unavailable.
- Unit prices and line totals reflect the current menu prices, matching the original schema. Bill previews also use current prices; they are not historical receipts.

Orders use the existing `seat_order_item` table. Billing adds the `bill_plan` table through the setup script; the reference notebooks stay unchanged. The app identity needs SELECT, INSERT, and UPDATE access to the order table and UPDATE access to restaurant tables.

These features use the original database tables. If starting from a new database, run the creation/population notebooks and `setup_database.py` as described below. The app identity needs SELECT access plus INSERT, UPDATE, and DELETE access for the management tables. Multi-step table and assignment changes use separate Databricks SQL statements; they do not provide transactions across tables.

## Bill splitting and discounts

From **Orders**, choose a table and click **Split bill**, or open **Bills & splits** from the navigation and choose a table. The screen shows current order items, subtotal, approved discount, total to split, and the amount owed on each bill.

- **Separate bill for each seat**: each seat pays for its items.
- **Group seats onto bills**: select a bill for every seat with current orders. Every seat must appear exactly once.
- **Split equally**: choose 1–30 people. Any extra cents are distributed so shares differ by at most one cent and add up exactly.
- Click **Calculate & save split** to persist the selected method and grouping. Reopening the table retrieves those settings and recalculates amounts from current active orders. Cancelled and paid items are excluded. If a grouped split no longer matches the ordered seats, the screen falls back to separate seats and asks you to review it.
- Managers can approve a **percentage (0–100%)** or **fixed CAD amount** with a reason. Fixed discounts are capped at the current subtotal. Discounts are distributed across seat/group subtotals proportionally; equal splits divide the final discounted total evenly. The approving employee is recorded. Servers can retain an approved discount while changing the split, but cannot approve, change, or remove it.

These are saved bill plans, not completed payments. Prices/quantities and the approved discount can change the preview. No tax, tip, payment provider, or settlement is added.

## Employees and restaurant configuration

Managers open **Employees** to create accounts, edit names/usernames/roles, optionally reset passwords, and activate/deactivate accounts. A blank password on edit keeps the existing password; stored passwords are never returned to the UI. Deactivation or moving a server to a different role retires their active table assignments. Table occupancy is preserved. Employees with assignment/discount history must be deactivated instead of deleted; unused accounts can be deleted. Self-deletion and changes to your own login/role/active status are blocked to avoid losing access. Only manager and server roles can be assigned.

Managers open **Restaurant settings** to edit their own restaurant’s name, address, and phone. They can also create a restaurant for a new team, which makes it available during registration. Creating a restaurant leaves the manager’s account attached to their existing restaurant; a new team registers manager/server accounts for the new restaurant. Managers cannot edit another restaurant, switch their account’s restaurant, or delete restaurants through the app.

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

This script adds missing `username` and `password` columns and creates `server_table_assignment` and **`bill_plan`** if needed. It preserves existing rows and credentials and can be rerun. If you already have a populated database, run only this setup script. Run it **before deploying these new features**, using a database owner or another identity allowed to create tables. The app identity needs SELECT and MODIFY on the operational tables, including `employee`, `restaurant`, and `bill_plan`.

No special account promotion is needed: register or log in as a **manager** to access employee management, restaurant settings, and discounts. If the earlier admin-promotion command was used, rerunning `python setup_database.py` restores those accounts to manager without changing their passwords or active status. The script does not create default credentials.

The default warehouse, catalog, and schema match the original project. Optional environment overrides are `DATABRICKS_WAREHOUSE_ID`, `DATABRICKS_CATALOG`, and `DATABRICKS_SCHEMA`. If you store these in a local `.env`, load it in each backend terminal:

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

Open **http://127.0.0.1:5173**, register an account, and log in. Vite proxies API calls to Flask on port 8000. The dashboard shows tables, capacity, status, and assigned servers for the logged-in employee's restaurant. Use the navigation to open Menu, Tables & seats, Server assignments, Orders, and Bills & splits. Managers also see Employees and Restaurant settings. Log in as a manager to create tables/menu items and assign servers, then use a server account to take orders for its tables.

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

The bill-plan upsert and seat capacity synchronization use [Databricks MERGE](https://docs.databricks.com/aws/en/sql/language-manual/delta-merge-into).

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
| `tests/test_administration.py` | 4 | Manager restaurant configuration, scoped employee changes, two-role/self-lockout checks, and protected employee history |
| `tests/test_billing.py` | 4 | Exact split/discount amounts, invalid inputs, assigned-server permissions, discount authorization, and reopened bills |
| `tests/test_seats.py` | 2 | Individual seat CRUD, capacity updates, history protection, and preserving custom seat numbers |
| `tests/test_orders.py` | 3 | Order editing/preparation/serving/cancellation, quantity limits, and blocking changes to another server's table |
| `frontend/src/api.test.js` | 1 | Regression coverage for Databricks sign-in cookies |
| `frontend/src/App.test.jsx` | 4 | Registration, failed login, login → dashboard → logout, and manager-only navigation without restaurant switching |
| `frontend/src/Management.test.jsx` | 2 | Menu creation and server assignment/removal in the UI |
| `frontend/src/Orders.test.jsx` | 2 | Seat-level ordering and read-only access to another server's table |
| `frontend/src/Completion.test.jsx` | 4 | Bill splitting/discounts, employee deactivation, restaurant creation, and individual seat creation |

There are **33 core tests: 20 Python and 13 frontend**. Small data-driven cases check shared rules such as manager permissions and quantity limits. Each test targets a basic workflow or access rule.

The Python tests use `unittest`; frontend tests use Vitest and React Testing Library. Database and HTTP calls are mocked, so tests need no Databricks credentials and do not access or change the live database. They demonstrate application logic and UI behavior; live SQL execution, Databricks permissions, and deployment connectivity still need a deployed check.

For a class demonstration, run both commands above, then show three representative tests: `test_all_mutations_require_manager_role`, `test_dashboard_requires_login_and_uses_employees_restaurant`, and `test_order_can_be_edited_prepared_served_and_cancelled`. Together they explain role permissions, restaurant isolation, and the main business workflow.

`npm run build` from the frontend directory is a separate deployment/build check, rather than a unit test.
