# Lumora Ecommerce

## Run the application

Install the backend dependencies into the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create a PostgreSQL database (for example, `lumora`) and set its connection
string in the backend terminal:

```powershell
$env:DATABASE_URL = "postgresql://postgres:your-password@localhost:5432/lumora"
```

The backend creates its tables when it starts. Keep `DATABASE_URL` set in the
same terminal whenever you run the backend.

Start the FastAPI backend from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

Start the React frontend in a second terminal:

```powershell
Set-Location frontend
npm run dev
```

Open the URL printed by Vite (normally `http://localhost:5173`).

## Authentication

New users sign up with a name, email, and strong password. The backend validates
the fields and stores users in PostgreSQL. Passwords are stored as
PBKDF2-SHA256 hashes, never as plain text.

Ensure an admin account is configured securely in PostgreSQL before deploying
the application.

Login returns a short-lived-in-process session token to the frontend. The
frontend stores that token while the user is logged in and sends it when an
admin adds, edits, or deletes a product. Logout removes the frontend token and
invalidates it on the backend.

## Authentication API

- `POST /auth/signup` creates a normal user account.
- `POST /auth/login` verifies credentials and returns the user and session token.
- `POST /auth/logout` invalidates the current session token.

Product reads remain public for the shop. Product add, edit, and delete
operations require a logged-in user with the `admin` role.
