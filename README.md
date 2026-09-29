# Assignment Management System — Review & Resubmission (Python / Flask)

Teachers review submissions (feedback, marks, Accepted / Needs Changes). Students view feedback,
submit updated versions when changes are requested, and see full version history.

## Run
```
python -m venv venv
venv\Scripts\activate          # Windows   (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 . Register a Teacher and a Student (separate sections on the login page).

## Stack
Flask, SQLite (`app.db`, created automatically), Jinja templates, plain CSS. Uploaded files go to `uploads/`.

## Features
- Separate Student / Teacher login and registration; role-based dashboards
- Teacher: post assignments (due date, max marks), search/filter/sort submissions, feedback, marks, status
- Student: submit with optional file, see status and feedback, resubmit only when "Needs Changes"
- Every version is kept; the latest is reviewed; history shows all versions with their feedback
- Late flags, downloadable attachments (access-controlled), light/dark theme
- Dynamic UI: forms submit without page reload (toast messages), live search/filter/sort, clickable stat cards, live auto-refresh via polling (`/api/sig`), pending count in the tab title, drag-and-drop uploads, word count and auto-saved drafts. Works without JavaScript too (falls back to normal forms).

## Security notes
Passwords hashed (Werkzeug), CSRF tokens on all forms, uploads limited to 10 MB and stored under random names.
Set `SECRET_KEY` as an environment variable in production and run behind a real WSGI server (e.g. gunicorn/waitress).

## Deploy from GitHub (Render)
1. Push this folder to a GitHub repository.
2. Render dashboard -> New -> Web Service -> connect the repo.
3. Build command: `pip install -r requirements.txt` | Start command: `gunicorn app:app`
4. Environment variables: `SECRET_KEY` (long random string). For persistent data on a paid plan, add a Disk mounted at `/var/data` and set `DATA_DIR=/var/data`.
Free plans have an ephemeral filesystem: `app.db` and `uploads/` reset on redeploy/restart.
