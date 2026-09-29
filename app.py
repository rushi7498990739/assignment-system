"""Assignment Management System - Review & Resubmission (Flask + SQLite)."""
import os, re, secrets, sqlite3, uuid
from datetime import datetime
from functools import wraps
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE)   # point this at a persistent disk in production
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")
UPLOADS = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "change-me-in-production"),
                  MAX_CONTENT_LENGTH=10 * 1024 * 1024)  # 10 MB uploads

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
  pw TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN('student','teacher')));
CREATE TABLE IF NOT EXISTS assignments(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT, due TEXT,
  max_marks INTEGER NOT NULL DEFAULT 100, created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS submissions(
  id INTEGER PRIMARY KEY,
  assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES users(id),
  UNIQUE(assignment_id, student_id));
CREATE TABLE IF NOT EXISTS versions(
  id INTEGER PRIMARY KEY,
  submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
  n INTEGER NOT NULL, content TEXT NOT NULL, file_name TEXT, file_path TEXT,
  created_at TEXT NOT NULL,
  status TEXT CHECK(status IN('Accepted','Needs Changes')),  -- NULL = pending
  feedback TEXT, marks REAL, reviewed_at TEXT,
  UNIQUE(submission_id, n));
"""

# ---------- database helpers ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript(SCHEMA)

def q(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows

def run(sql, args=()):
    cur = db().execute(sql, args)
    db().commit()
    return cur.lastrowid

def now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

# ---------- auth / security ----------
def current_user():
    uid = session.get("uid")
    return q("SELECT * FROM users WHERE id=?", (uid,), one=True) if uid else None

def login_required(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            u = current_user()
            if not u:
                return redirect(url_for("login", role=role))
            if u["role"] != role:
                abort(403)
            g.user = u
            return fn(*a, **k)
        return wrapper
    return deco

@app.before_request
def csrf_protect():
    if request.method == "POST":
        if not session.get("csrf") or request.form.get("csrf") != session["csrf"]:
            abort(400, "Invalid CSRF token")

@app.context_processor
def inject():
    session.setdefault("csrf", secrets.token_hex(16))
    return {"csrf": session["csrf"], "user": current_user()}

@app.template_filter("dt")
def fmt_dt(v):
    try:
        return datetime.fromisoformat(v).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return v or ""

@app.template_filter("filesize")
def filesize(path):
    try:
        b = os.path.getsize(os.path.join(UPLOADS, path))
        return f"{b/1048576:.1f} MB" if b > 1048576 else f"{max(1, b // 1024)} KB"
    except OSError:
        return ""

@app.route("/")
def home():
    u = current_user()
    return redirect(url_for("dashboard") if u else url_for("login", role="student"))

@app.route("/register/<role>", methods=["GET", "POST"])
def register(role):
    if role not in ("student", "teacher"):
        abort(404)
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        pw = request.form["password"]
        if not name or not re.match(r"^\S+@\S+\.\S+$", email) or len(pw) < 6:
            flash("Enter a name, a valid email and a password of 6+ characters.", "error")
        elif q("SELECT 1 FROM users WHERE email=?", (email,), one=True):
            flash("That email is already registered.", "error")
        else:
            uid = run("INSERT INTO users(name,email,pw,role) VALUES(?,?,?,?)",
                      (name, email, generate_password_hash(pw), role))
            session.clear(); session["uid"] = uid
            return redirect(url_for("dashboard"))
    return render_template("auth.html", role=role, mode="register")

@app.route("/login/<role>", methods=["GET", "POST"])
def login(role):
    if role not in ("student", "teacher"):
        abort(404)
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE email=? AND role=?",
              (request.form["email"].strip().lower(), role), one=True)
        if u and check_password_hash(u["pw"], request.form["password"]):
            session.clear(); session["uid"] = u["id"]
            return redirect(url_for("dashboard"))
        flash("Invalid credentials for this section.", "error")
    return render_template("auth.html", role=role, mode="login")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login", role="student"))

@app.route("/dashboard")
def dashboard():
    u = current_user()
    if not u:
        return redirect(url_for("login", role="student"))
    return redirect(url_for("student_dashboard" if u["role"] == "student" else "teacher_dashboard"))

# ---------- data loading ----------
def load_subs(student_id=None):
    sql = """SELECT s.id, s.assignment_id AS aid, a.title, a.due, a.max_marks,
                    u.name AS student, u.email
             FROM submissions s JOIN assignments a ON a.id=s.assignment_id
             JOIN users u ON u.id=s.student_id"""
    args = ()
    if student_id:
        sql += " WHERE s.student_id=?"; args = (student_id,)
    subs = []
    for r in q(sql, args):
        s = dict(r)
        s["versions"] = q("SELECT * FROM versions WHERE submission_id=? ORDER BY n", (s["id"],))
        s["latest"] = s["versions"][-1]
        s["status"] = s["latest"]["status"] or "Pending"
        subs.append(s)
    return subs

def store_file(f):
    if not f or not f.filename:
        return None, None
    name = secure_filename(f.filename) or "file"
    path = f"{uuid.uuid4().hex}_{name}"
    f.save(os.path.join(UPLOADS, path))
    return name, path

# ---------- student ----------
@app.route("/student")
@login_required("student")
def student_dashboard():
    assignments = q("SELECT * FROM assignments ORDER BY COALESCE(due,'9999'), id")
    subs = {s["aid"]: s for s in load_subs(g.user["id"])}
    count = lambda st: sum(1 for s in subs.values() if s["status"] == st)
    stats = [("Assignments", len(assignments)), ("Submitted", len(subs)),
             ("Pending", count("Pending")), ("Accepted", count("Accepted")),
             ("Needs changes", count("Needs Changes"))]
    pct = round(count("Accepted") / len(assignments) * 100) if assignments else 0
    return render_template("student.html", assignments=assignments, subs=subs,
                           stats=stats, pct=pct, now=now())

@app.post("/student/submit/<int:aid>")
@login_required("student")
def submit(aid):
    content = request.form["content"].strip()
    if not q("SELECT 1 FROM assignments WHERE id=?", (aid,), one=True):
        abort(404)
    if q("SELECT 1 FROM submissions WHERE assignment_id=? AND student_id=?", (aid, g.user["id"]), one=True):
        flash("You have already submitted this assignment.", "error")
    elif not content:
        flash("Please write an answer.", "error")
    else:
        sid = run("INSERT INTO submissions(assignment_id,student_id) VALUES(?,?)", (aid, g.user["id"]))
        fn, fp = store_file(request.files.get("file"))
        run("INSERT INTO versions(submission_id,n,content,file_name,file_path,created_at) VALUES(?,?,?,?,?,?)",
            (sid, 1, content, fn, fp, now()))
        flash("Assignment submitted.")
    return redirect(url_for("student_dashboard"))

@app.post("/student/resubmit/<int:sid>")
@login_required("student")
def resubmit(sid):
    s = q("SELECT * FROM submissions WHERE id=? AND student_id=?", (sid, g.user["id"]), one=True) or abort(404)
    last = q("SELECT * FROM versions WHERE submission_id=? ORDER BY n DESC LIMIT 1", (sid,), one=True)
    content = request.form["content"].strip()
    if last["status"] != "Needs Changes":
        flash("Resubmission is only allowed when changes are requested.", "error")
    elif not content:
        flash("Please write your updated answer.", "error")
    else:
        fn, fp = store_file(request.files.get("file"))
        run("INSERT INTO versions(submission_id,n,content,file_name,file_path,created_at) VALUES(?,?,?,?,?,?)",
            (sid, last["n"] + 1, content, fn, fp, now()))
        flash(f"Version {last['n'] + 1} submitted.")
    return redirect(url_for("student_dashboard"))

# ---------- teacher ----------
@app.route("/teacher")
@login_required("teacher")
def teacher_dashboard():
    assignments = q("SELECT * FROM assignments ORDER BY id DESC")
    subs = load_subs()
    f_q = request.args.get("q", "").strip().lower()
    f_st = request.args.get("status", "All")
    f_as = request.args.get("aid", "All")
    sort = request.args.get("sort", "new")
    shown = [s for s in subs
             if (f_st == "All" or s["status"] == f_st)
             and (f_as == "All" or str(s["aid"]) == f_as)
             and (not f_q or f_q in f"{s['student']} {s['email']} {s['title']}".lower())]
    key = {"new": lambda s: s["latest"]["created_at"], "old": lambda s: s["latest"]["created_at"],
           "name": lambda s: s["student"].lower()}[sort if sort in ("new", "old", "name") else "new"]
    shown.sort(key=key, reverse=(sort == "new"))
    count = lambda st: sum(1 for s in subs if s["status"] == st)
    stats = [("Assignments", len(assignments)), ("Submissions", len(subs)), ("Pending", count("Pending")),
             ("Accepted", count("Accepted")), ("Needs changes", count("Needs Changes"))]
    counts = {a["id"]: sum(1 for s in subs if s["aid"] == a["id"]) for a in assignments}
    return render_template("teacher.html", assignments=assignments, subs=shown, stats=stats,
                           counts=counts, pending=count("Pending"), f=dict(q=request.args.get("q", ""), status=f_st, aid=f_as, sort=sort))

@app.post("/teacher/assignments")
@login_required("teacher")
def add_assignment():
    title = request.form["title"].strip()
    try:
        mx = int(request.form.get("max_marks", 100))
    except ValueError:
        mx = 0
    if not title or mx <= 0:
        flash("Title and a positive max marks value are required.", "error")
    else:
        run("INSERT INTO assignments(title,description,due,max_marks,created_by) VALUES(?,?,?,?,?)",
            (title, request.form.get("description", "").strip(), request.form.get("due") or None, mx, g.user["id"]))
        flash("Assignment posted.")
    return redirect(url_for("teacher_dashboard"))

@app.post("/teacher/assignments/<int:aid>/delete")
@login_required("teacher")
def delete_assignment(aid):
    run("DELETE FROM assignments WHERE id=?", (aid,))
    flash("Assignment deleted.")
    return redirect(url_for("teacher_dashboard"))

@app.post("/teacher/review/<int:sid>")
@login_required("teacher")
def review(sid):
    s = q("""SELECT s.id, a.max_marks FROM submissions s JOIN assignments a ON a.id=s.assignment_id
             WHERE s.id=?""", (sid,), one=True) or abort(404)
    last = q("SELECT id FROM versions WHERE submission_id=? ORDER BY n DESC LIMIT 1", (sid,), one=True)
    status = request.form.get("status")
    raw = request.form.get("marks", "").strip()
    try:
        marks = float(raw) if raw else None
    except ValueError:
        marks = -1
    if status not in ("Accepted", "Needs Changes"):
        flash("Choose a status.", "error")
    elif marks is not None and not (0 <= marks <= s["max_marks"]):
        flash(f"Marks must be between 0 and {s['max_marks']}.", "error")
    else:
        run("UPDATE versions SET status=?,feedback=?,marks=?,reviewed_at=? WHERE id=?",
            (status, request.form.get("feedback", "").strip(), marks, now(), last["id"]))
        flash("Review saved.")
    return redirect(url_for("teacher_dashboard"))

# ---------- live-update signature (polled by static/app.js) ----------
@app.get("/api/sig")
def api_sig():
    u = current_user() or abort(401)
    where, args = ("WHERE s.student_id=?", (u["id"],)) if u["role"] == "student" else ("", ())
    v = q(f"""SELECT COUNT(v.id) c, COALESCE(MAX(v.id),0) m, COALESCE(SUM(v.status IS NOT NULL),0) r,
                    COALESCE(MAX(v.reviewed_at),'') t
             FROM versions v JOIN submissions s ON s.id=v.submission_id {where}""", args, one=True)
    a = q("SELECT COUNT(*) c, COALESCE(MAX(id),0) m FROM assignments", one=True)
    return jsonify(sig=f"{v['c']}|{v['m']}|{v['r']}|{v['t']}|{a['c']}|{a['m']}")

# ---------- file download (teacher, or the student who owns it) ----------
@app.route("/file/<int:vid>")
def download(vid):
    u = current_user() or abort(401)
    v = q("""SELECT v.*, s.student_id FROM versions v JOIN submissions s ON s.id=v.submission_id
             WHERE v.id=?""", (vid,), one=True) or abort(404)
    if u["role"] == "student" and v["student_id"] != u["id"]:
        abort(403)
    if not v["file_path"]:
        abort(404)
    return send_from_directory(UPLOADS, v["file_path"], as_attachment=True, download_name=v["file_name"])

init_db()
if __name__ == "__main__":
    app.run(debug=True)
