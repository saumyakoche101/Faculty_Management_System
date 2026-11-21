# FacultyFlow — Faculty Leave & Workload Management System

## Included features
- Authentication: faculty registration, login, logout, role-based access (Faculty/HOD/Admin)
- Faculty dashboard and profile
- Leave application, pending-request editing, status tracking, date-overlap validation
- HOD/Admin approval and rejection with review notes
- Faculty workload timetable and HOD/Admin workload entry
- Substitute allocation for approved leave, with notifications
- In-app notifications
- Monthly leave counts and workload analytics

## Requirements
- Python 3.10+
- Windows, macOS, or Linux

## Run on Windows
1. Extract the ZIP.
2. Open the extracted `Faculty_Management_System` folder in VS Code.
3. Open Terminal > New Terminal.
4. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, run this once in the same terminal:
   `Set-ExecutionPolicy -Scope Process Bypass`
   Then activate again.

5. Install packages:

   ```powershell
   pip install -r requirements.txt
   ```

6. Start the application:

   ```powershell
   python app.py
   ```

7. Open http://127.0.0.1:5000 in Chrome.

## Demo accounts
- Faculty: `faculty@demo.com` / `Faculty@123`
- HOD: `hod@demo.com` / `HOD@123`
- Admin: `admin@demo.com` / `Admin@123`

The database `faculty.db` is created automatically on first run and seeded with demo accounts and sample workload. To reset demo data, stop the server and delete `faculty.db`, then run `python app.py` again.

## Important notes
- This is a college demonstration prototype. Change the development `SECRET_KEY`, add CSRF protection, HTTPS, stronger administrative account provisioning, audit logging and production deployment controls before real institutional use.
- New self-registrations are assigned the Faculty role. HOD/Admin demo accounts are seeded for jury demonstration; do not expose demo credentials on a public deployment.
