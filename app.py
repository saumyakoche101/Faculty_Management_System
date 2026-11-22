import os
import sqlite3
import smtplib
from email.message import EmailMessage
from functools import wraps
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "faculty.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-development-secret-key")

ROLES = ("Faculty", "HOD", "Admin")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('Faculty','HOD','Admin')),
        department TEXT NOT NULL DEFAULT 'Computer Science',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id INTEGER NOT NULL,
        leave_type TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        reviewer_id INTEGER,
        review_note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(faculty_id) REFERENCES users(id),
        FOREIGN KEY(reviewer_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS workloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        day TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        hours REAL NOT NULL,
        semester TEXT NOT NULL DEFAULT 'Semester 1',
        FOREIGN KEY(faculty_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS substitutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leave_id INTEGER NOT NULL,
        substitute_id INTEGER NOT NULL,
        duty_date TEXT NOT NULL,
        subject TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(leave_id) REFERENCES leave_requests(id),
        FOREIGN KEY(substitute_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        demo_users = [
            ("Asha Faculty", "faculty@demo.com", generate_password_hash("Faculty@123"), "Faculty", "Computer Science"),
            ("Rahul HOD", "hod@demo.com", generate_password_hash("HOD@123"), "HOD", "Computer Science"),
            ("Admin User", "admin@demo.com", generate_password_hash("Admin@123"), "Admin", "Administration"),
            ("Neha Faculty", "neha@demo.com", generate_password_hash("Faculty@123"), "Faculty", "Computer Science"),
        ]
        db.executemany("INSERT INTO users(name,email,password_hash,role,department) VALUES(?,?,?,?,?)", demo_users)
        faculty_id = db.execute("SELECT id FROM users WHERE email='faculty@demo.com'").fetchone()[0]
        neha_id = db.execute("SELECT id FROM users WHERE email='neha@demo.com'").fetchone()[0]
        sample = [
            (faculty_id, "Software Engineering", "Monday", "09:00", "10:00", 1, "Semester 5"),
            (faculty_id, "Agile Development", "Tuesday", "11:00", "12:00", 1, "Semester 5"),
            (faculty_id, "Database Systems", "Wednesday", "10:00", "12:00", 2, "Semester 5"),
            (neha_id, "Web Technology", "Thursday", "09:00", "11:00", 2, "Semester 5"),
        ]
        db.executemany("INSERT INTO workloads(faculty_id,subject,day,start_time,end_time,hours,semester) VALUES(?,?,?,?,?,?,?)", sample)
    db.commit()
    db.close()

def refresh_session_user():
    """Validate the browser session against the current database.

    This clears stale sessions after a hosted database is recreated or reset,
    preventing foreign-key errors when a form is submitted.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = get_db().execute(
        "SELECT id, name, email, role, department FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if user is None:
        session.clear()
        return None
    session["user_id"] = user["id"]
    session["name"] = user["name"]
    session["role"] = user["role"]
    session["department"] = user["department"]
    return user

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if refresh_session_user() is None:
            flash("Your session expired. Please log in again.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = refresh_session_user()
            if user is None:
                flash("Your session expired. Please log in again.", "warning")
                return redirect(url_for("login"))
            if user["role"] not in roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

def notify(user_id, message):
    get_db().execute("INSERT INTO notifications(user_id,message) VALUES(?,?)", (user_id, message))
    get_db().commit()


def send_email(recipient, subject, body):
    """Send an email using SMTP settings stored in the hosting environment."""
    if not recipient:
        app.logger.warning("Email not sent: recipient address is missing.")
        return False

    mail_server = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    mail_port = int(os.environ.get("MAIL_PORT", "587"))
    mail_username = os.environ.get("MAIL_USERNAME", "")
    mail_password = os.environ.get("MAIL_PASSWORD", "")
    mail_sender = os.environ.get("MAIL_DEFAULT_SENDER") or mail_username
    use_tls = os.environ.get("MAIL_USE_TLS", "true").strip().lower() in ("1", "true", "yes", "on")

    if not mail_username or not mail_password or not mail_sender:
        app.logger.warning("Email not sent: Gmail SMTP environment variables are incomplete.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_sender
    message["To"] = recipient
    message.set_content(body)

    try:
        with smtplib.SMTP(mail_server, mail_port, timeout=20) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(mail_username, mail_password)
            smtp.send_message(message)
        app.logger.info("Email sent successfully to %s", recipient)
        return True
    except Exception:
        app.logger.exception("Email delivery failed for recipient %s", recipient)
        return False

@app.context_processor
def inject_globals():
    if session.get("user_id"):
        unread = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                                  (session["user_id"],)).fetchone()[0]
    else:
        unread = 0
    return {"unread_notifications": unread, "current_year": date.today().year}

@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department = request.form.get("department", "Computer Science").strip()
        if not name or not email or len(password) < 8:
            flash("Enter your name and email, and use a password with at least 8 characters.", "danger")
            return render_template("register.html")
        try:
            db = get_db()
            db.execute("INSERT INTO users(name,email,password_hash,role,department) VALUES(?,?,?,?,?)",
                       (name, email, generate_password_hash(password), "Faculty", department or "Computer Science"))
            db.commit()
            flash("Registration successful. You can now log in as Faculty.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["department"] = user["department"]
            return redirect(url_for("dashboard"))
        flash("Incorrect email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    uid, role = session["user_id"], session["role"]
    if role == "Faculty":
        leaves = db.execute("SELECT * FROM leave_requests WHERE faculty_id=? ORDER BY created_at DESC", (uid,)).fetchall()
        workload = db.execute("SELECT * FROM workloads WHERE faculty_id=? ORDER BY CASE day WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 ELSE 6 END, start_time", (uid,)).fetchall()
        total_hours = db.execute("SELECT COALESCE(SUM(hours),0) FROM workloads WHERE faculty_id=?", (uid,)).fetchone()[0]
    else:
        leaves = db.execute("""SELECT l.*,u.name AS faculty_name FROM leave_requests l
                               JOIN users u ON u.id=l.faculty_id ORDER BY l.created_at DESC LIMIT 10""").fetchall()
        workload = db.execute("""SELECT w.*,u.name AS faculty_name FROM workloads w
                                 JOIN users u ON u.id=w.faculty_id ORDER BY u.name,w.day,w.start_time""").fetchall()
        total_hours = db.execute("SELECT COALESCE(SUM(hours),0) FROM workloads").fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM leave_requests WHERE status='Pending'").fetchone()[0]
    faculty_count = db.execute("SELECT COUNT(*) FROM users WHERE role='Faculty'").fetchone()[0]
    return render_template("dashboard.html", leaves=leaves, workload=workload,
                           total_hours=total_hours, pending=pending, faculty_count=faculty_count)

@app.route("/leaves")
@login_required
def leaves():
    db = get_db()
    if session["role"] == "Faculty":
        rows = db.execute("SELECT * FROM leave_requests WHERE faculty_id=? ORDER BY created_at DESC",
                          (session["user_id"],)).fetchall()
    else:
        rows = db.execute("""SELECT l.*,u.name AS faculty_name FROM leave_requests l
                             JOIN users u ON u.id=l.faculty_id ORDER BY l.created_at DESC""").fetchall()
    return render_template("leaves.html", leaves=rows)

@app.route("/leaves/new", methods=["GET", "POST"])
@roles_required("Faculty")
def new_leave():
    if request.method == "POST":
        leave_type = request.form.get("leave_type", "").strip()
        start = request.form.get("start_date", "")
        end = request.form.get("end_date", "")
        reason = request.form.get("reason", "").strip()
        try:
            start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            flash("Please enter valid leave dates.", "danger")
            return render_template("leave_form.html", leave=None)
        if not leave_type or not reason or end_d < start_d:
            flash("Check the leave type, reason and date range.", "danger")
            return render_template("leave_form.html", leave=None)
        db = get_db()
        overlap = db.execute("""SELECT COUNT(*) FROM leave_requests WHERE faculty_id=?
                                AND status!='Rejected' AND NOT(end_date < ? OR start_date > ?)""",
                             (session["user_id"], start, end)).fetchone()[0]
        if overlap:
            flash("You already have a leave request overlapping those dates.", "danger")
            return render_template("leave_form.html", leave=None)
        db.execute("""INSERT INTO leave_requests(faculty_id,leave_type,start_date,end_date,reason)
                      VALUES(?,?,?,?,?)""", (session["user_id"], leave_type, start, end, reason))
        db.commit()
        reviewers = db.execute("SELECT id,email,name FROM users WHERE role IN ('HOD','Admin')").fetchall()
        for reviewer in reviewers:
            message = f"New leave request from {session['name']} ({start} to {end})."
            notify(reviewer["id"], message)
            send_email(
                reviewer["email"],
                "FacultyFlow: New leave request submitted",
                f"Hello {reviewer['name']},\\n\\n{message}\\nPlease log in to FacultyFlow to review the request."
            )
        flash("Leave request submitted for approval.", "success")
        return redirect(url_for("leaves"))
    return render_template("leave_form.html", leave=None)

@app.route("/leaves/<int:leave_id>/edit", methods=["GET", "POST"])
@roles_required("Faculty")
def edit_leave(leave_id):
    db = get_db()
    leave = db.execute("SELECT * FROM leave_requests WHERE id=? AND faculty_id=?",
                       (leave_id, session["user_id"])).fetchone()
    if not leave:
        flash("Leave request not found.", "danger")
        return redirect(url_for("leaves"))
    if leave["status"] != "Pending":
        flash("Only pending requests can be edited.", "warning")
        return redirect(url_for("leaves"))
    if request.method == "POST":
        start, end = request.form.get("start_date", ""), request.form.get("end_date", "")
        try:
            start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            flash("Please enter valid dates.", "danger")
            return render_template("leave_form.html", leave=leave)
        if end_d < start_d:
            flash("End date cannot be before start date.", "danger")
            return render_template("leave_form.html", leave=leave)
        db.execute("""UPDATE leave_requests SET leave_type=?,start_date=?,end_date=?,reason=?
                      WHERE id=? AND faculty_id=?""",
                   (request.form.get("leave_type"), start, end, request.form.get("reason","").strip(),
                    leave_id, session["user_id"]))
        db.commit()
        flash("Leave request updated.", "success")
        return redirect(url_for("leaves"))
    return render_template("leave_form.html", leave=leave)

@app.route("/leaves/<int:leave_id>/review", methods=["POST"])
@roles_required("HOD", "Admin")
def review_leave(leave_id):
    db = get_db()
    leave = db.execute("SELECT * FROM leave_requests WHERE id=?", (leave_id,)).fetchone()
    if not leave:
        flash("Leave request not found.", "danger")
        return redirect(url_for("leaves"))
    decision = request.form.get("decision")
    if decision not in ("Approved", "Rejected") or leave["status"] != "Pending":
        flash("This request cannot be reviewed.", "warning")
        return redirect(url_for("leaves"))
    note = request.form.get("review_note", "").strip()
    db.execute("""UPDATE leave_requests SET status=?,reviewer_id=?,review_note=? WHERE id=?""",
               (decision, session["user_id"], note, leave_id))
    db.commit()
    message = f"Your leave request ({leave['start_date']} to {leave['end_date']}) was {decision.lower()}."
    notify(leave["faculty_id"], message)
    faculty_user = db.execute("SELECT name,email FROM users WHERE id=?", (leave["faculty_id"],)).fetchone()
    if faculty_user:
        note_text = f"\\nReview note: {note}" if note else ""
        send_email(
            faculty_user["email"],
            f"FacultyFlow: Leave request {decision.lower()}",
            f"Hello {faculty_user['name']},\\n\\n{message}{note_text}\\n\\nPlease log in to FacultyFlow for details."
        )
    flash(f"Leave request {decision.lower()}.", "success")
    return redirect(url_for("leaves"))

@app.route("/workload")
@login_required
def workload():
    db = get_db()
    if session["role"] == "Faculty":
        rows = db.execute("SELECT w.*,u.name AS faculty_name FROM workloads w JOIN users u ON u.id=w.faculty_id WHERE faculty_id=? ORDER BY day,start_time",
                          (session["user_id"],)).fetchall()
    else:
        rows = db.execute("SELECT w.*,u.name AS faculty_name FROM workloads w JOIN users u ON u.id=w.faculty_id ORDER BY u.name,day,start_time").fetchall()
    faculty_options = db.execute("SELECT id,name FROM users WHERE role='Faculty' ORDER BY name").fetchall() if session["role"] in ("HOD", "Admin") else []
    return render_template("workload.html", workloads=rows, faculty_options=faculty_options)

@app.route("/workload/add", methods=["POST"])
@roles_required("HOD", "Admin")
def add_workload():
    db = get_db()
    faculty_id = request.form.get("faculty_id", type=int)
    faculty = db.execute("SELECT id FROM users WHERE id=? AND role='Faculty'", (faculty_id,)).fetchone()
    try:
        hours = float(request.form.get("hours", "0"))
    except ValueError:
        hours = 0
    if not faculty or hours <= 0:
        flash("Choose a faculty member and enter valid hours.", "danger")
        return redirect(url_for("workload"))
    db.execute("""INSERT INTO workloads(faculty_id,subject,day,start_time,end_time,hours,semester)
                  VALUES(?,?,?,?,?,?,?)""",
               (faculty_id, request.form.get("subject","").strip(), request.form.get("day"),
                request.form.get("start_time"), request.form.get("end_time"), hours,
                request.form.get("semester","Semester 1")))
    db.commit()
    flash("Workload entry added.", "success")
    return redirect(url_for("workload"))

@app.route("/substitutions", methods=["GET", "POST"])
@roles_required("HOD", "Admin")
def substitutions():
    db = get_db()
    if request.method == "POST":
        leave_id = request.form.get("leave_id", type=int)
        substitute_id = request.form.get("substitute_id", type=int)
        leave = db.execute("SELECT * FROM leave_requests WHERE id=? AND status='Approved'", (leave_id,)).fetchone()
        sub = db.execute("SELECT * FROM users WHERE id=? AND role='Faculty'", (substitute_id,)).fetchone()
        if not leave or not sub or sub["id"] == leave["faculty_id"]:
            flash("Select an approved leave and a different faculty substitute.", "danger")
        else:
            db.execute("""INSERT INTO substitutions(leave_id,substitute_id,duty_date,subject,notes)
                          VALUES(?,?,?,?,?)""",
                       (leave_id, substitute_id, leave["start_date"],
                        request.form.get("subject","Substitute class").strip(),
                        request.form.get("notes","").strip()))
            db.commit()
            assignment_message = f"You have been assigned substitute duty on {leave['start_date']} for {leave['end_date']}."
            notify(substitute_id, assignment_message)
            send_email(
                sub["email"],
                "FacultyFlow: Substitute duty assigned",
                f"Hello {sub['name']},\\n\\n{assignment_message}\\nSubject: {request.form.get('subject', 'Substitute class').strip()}\\nPlease log in to FacultyFlow for the assignment details."
            )
            flash("Substitute faculty assigned and notified.", "success")
        return redirect(url_for("substitutions"))
    approved = db.execute("""SELECT l.*,u.name AS faculty_name FROM leave_requests l
                             JOIN users u ON u.id=l.faculty_id WHERE l.status='Approved'
                             ORDER BY l.start_date DESC""").fetchall()
    faculty = db.execute("SELECT id,name FROM users WHERE role='Faculty' ORDER BY name").fetchall()
    assignments = db.execute("""SELECT s.*,u.name AS substitute_name,l.start_date,l.end_date,owner.name AS absent_name
                                FROM substitutions s JOIN users u ON u.id=s.substitute_id
                                JOIN leave_requests l ON l.id=s.leave_id
                                JOIN users owner ON owner.id=l.faculty_id
                                ORDER BY s.created_at DESC""").fetchall()
    return render_template("substitutions.html", approved=approved, faculty=faculty, assignments=assignments)

@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC",
                      (session["user_id"],)).fetchall()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    db.commit()
    return render_template("notifications.html", notifications=rows)

@app.route("/analytics")
@roles_required("HOD", "Admin")
def analytics():
    db = get_db()
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    leave_stats = db.execute("""SELECT status,COUNT(*) AS count FROM leave_requests
                                WHERE substr(start_date,1,7)=? GROUP BY status""", (month,)).fetchall()
    workload_stats = db.execute("""SELECT u.name,COALESCE(SUM(w.hours),0) AS hours
                                   FROM users u LEFT JOIN workloads w ON w.faculty_id=u.id
                                   WHERE u.role='Faculty' GROUP BY u.id ORDER BY hours DESC""").fetchall()
    return render_template("analytics.html", month=month, leave_stats=leave_stats,
                           workload_stats=workload_stats)

@app.route("/profile")
@login_required
def profile():
    user = get_db().execute("SELECT id,name,email,role,department,created_at FROM users WHERE id=?",
                            (session["user_id"],)).fetchone()
    return render_template("profile.html", user=user)

@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404

init_db()

if __name__ == "__main__":
    app.run(debug=True)
