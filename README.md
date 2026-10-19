# CPS714 Restaurant Manager

The current sprint includes **registration, login, logout, and a read-only table dashboard**. The frontend uses React and Vite; Flask provides a small JSON API backed by Databricks SQL. Menu management, orders, table clearing, server assignment, and reports are outside this sprint and have no web pages or API routes.

## Structure

```text
src/restaurant-manager/
  app.py                 Flask API and serving the built React app
  database.py            Databricks connection and parameterized queries
  setup_database.py      Adds the login columns and dashboard assignment table
  package.json           Databricks deployment build entry point
  app.yaml               Databricks app startup configuration
  frontend/
    src/App.jsx          Login, registration, and dashboard components
    src/api.js           Requests to the Flask API
    src/styles.css       Responsive page styles
    vite.config.js       Local /api proxy to Flask on port 8000
  tests/                 Backend tests with mocked database access
src/querying/            Original database and CRUD notebooks (reference)
src/helpers/             Original operations and checkout notebook (reference)
```

The notebooks are retained unchanged as reference for future sprints. The running app does not import them.

## Login requirements

- Databricks authentication with access to the SQL warehouse and `cps714.restaurant_manager` tables.
- An existing restaurant to select during registration.
- `username` and `password` string columns on `employee`, in addition to its existing employee, restaurant, name, role, and status fields.
- An employee with credentials and `status = 'active'`. Registering creates this account; the original sample employees have no credentials.

For this classroom prototype, passwords remain plain text in the database as requested. React holds the current user and credentials only in memory. Dashboard requests send those credentials using an HTTP Basic authorization header, so Flask can look up the employee's restaurant without session cookies or tokens. Logging out clears React's state; refreshing or reopening the page requires logging in again. New usernames are stored in lowercase and login is case-insensitive for usernames. Passwords are matched exactly.

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

Open **http://127.0.0.1:5173**, register an account, and log in. Vite proxies API calls to Flask on port 8000. The dashboard shows tables, capacity, status, and assigned servers for the logged-in employee's restaurant. An empty restaurant shows an empty state; creating tables is outside this sprint.

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

## Checks

From the repository root with the virtual environment active:

```sh
python -m unittest discover -s src/restaurant-manager/tests -v
cd src/restaurant-manager/frontend
npm test
npm run build
```

Tests mock database responses; they do not access or change the live Databricks database.
