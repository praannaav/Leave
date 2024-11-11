from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import and_
import math

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///leave_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'  # Replace with a secure random key
db = SQLAlchemy(app)

# Session Lifetime
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=7)

# Admin Credentials
app.config['ADMIN_USERNAME'] = 'admin'
app.config['ADMIN_PASSWORD'] = 'password123'

# Database Models
class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_number = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(100))
    leaves = db.relationship('Leave', backref='employee', lazy=True)

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)

class Replacement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_on_leave_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    replacement_employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)

# Create the database tables
with app.app_context():
    db.create_all()

# Helper function to calculate the leave limit based on the date
def is_within_limit(date):
    total_employees = Employee.query.count()
    leaves_on_date = Leave.query.filter_by(date=date).count()
    if total_employees == 0:
        return True
    # Determine the limit based on the date
    if date.month == 11:
        # November
        limit = 0.33
    elif date.month == 12:
        if date.day >= 1 and date.day <= 15:
            # December 1 to December 15
            limit = 0.33
        elif date.day >= 16 and date.day <= 31 and date.year == 2024:
            # December 16 to December 31, 2024
            limit = 0.70
        else:
            # For other December dates, assume 33%
            limit = 0.33
    else:
        # For other months, assume 33%
        limit = 0.33
    return (leaves_on_date / total_employees) < limit

# Routes
@app.route('/')
def index():
    employees = Employee.query.order_by(Employee.employee_number).all()
    return render_template('index.html', employees=employees)

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    name = request.form['name']
    if not name:
        return redirect(url_for('index'))
    # Assign next employee number
    last_employee = Employee.query.order_by(Employee.employee_number.desc()).first()
    next_number = last_employee.employee_number + 1 if last_employee else 1
    new_employee = Employee(name=name, employee_number=next_number)
    db.session.add(new_employee)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/calendar/<int:employee_id>')
def calendar(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    employees = Employee.query.filter(Employee.id != employee_id).order_by(Employee.employee_number).all()
    return render_template('calendar.html', employee=employee, employees=employees)

@app.route('/request_leave', methods=['POST'])
def request_leave():
    data = request.get_json()
    employee_id = data['employee_id']
    dates = data['dates']
    replacement_employee_id = data.get('replacement_employee_id')
    if replacement_employee_id == 'None':
        replacement_employee_id = None
    else:
        replacement_employee_id = int(replacement_employee_id)

    employee = Employee.query.get(employee_id)
    replacement_employee = Employee.query.get(replacement_employee_id) if replacement_employee_id else None

    approved_dates = []
    declined_dates = []

    for date_str in dates:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Initialize decline reason
        decline_reason = None

        # Check leave limit
        if not is_within_limit(date):
            decline_reason = 'Leave limit exceeded for this date.'
        # Check if replacement is on leave on the same day
        elif replacement_employee and Leave.query.filter_by(employee_id=replacement_employee_id, date=date).first():
            decline_reason = f'Replacement {replacement_employee.name} is on leave on {date_str}.'
        # Check for mutual replacements on the same day
        elif replacement_employee and Replacement.query.filter(
            and_(
                Replacement.employee_on_leave_id == replacement_employee_id,
                Replacement.replacement_employee_id == employee_id,
                Replacement.date == date
            )
        ).first():
            decline_reason = f'You and {replacement_employee.name} cannot replace each other on the same day.'
        # Check if replacement is already assigned on the same day
        elif replacement_employee and Replacement.query.filter(
            and_(
                Replacement.replacement_employee_id == replacement_employee_id,
                Replacement.date == date
            )
        ).first():
            decline_reason = f'Replacement {replacement_employee.name} is already assigned on {date_str}.'

        if decline_reason:
            declined_dates.append({'date': date_str, 'reason': decline_reason})
            continue

        # Approve leave and assign replacement (if any)
        new_leave = Leave(date=date, employee_id=employee_id)
        db.session.add(new_leave)
        if replacement_employee_id:
            new_replacement = Replacement(
                employee_on_leave_id=employee_id,
                replacement_employee_id=replacement_employee_id,
                date=date
            )
            db.session.add(new_replacement)
        else:
            # No replacement assigned
            new_replacement = Replacement(
                employee_on_leave_id=employee_id,
                replacement_employee_id=None,
                date=date
            )
            db.session.add(new_replacement)
        approved_dates.append(date_str)

    db.session.commit()

    response = {
        'approved': approved_dates,
        'declined': declined_dates
    }
    return jsonify(response)

@app.route('/get_leaves')
def get_leaves():
    leaves = Leave.query.all()
    leave_list = [{'title': leave.employee.name, 'start': leave.date.strftime('%Y-%m-%d')} for leave in leaves]
    return jsonify(leave_list)

@app.route('/get_replacements')
def get_replacements():
    replacements = Replacement.query.all()
    data = []
    for r in replacements:
        employee_on_leave = Employee.query.get(r.employee_on_leave_id)
        if r.replacement_employee_id:
            replacement_employee = Employee.query.get(r.replacement_employee_id)
            replacement_name = replacement_employee.name
        else:
            replacement_name = 'No Replacement'
        data.append({
            'employee_on_leave': employee_on_leave.name,
            'replacement_employee': replacement_name,
            'date': r.date.strftime('%Y-%m-%d')
        })
    return jsonify(data)

@app.route('/leave_schedule')
def leave_schedule():
    leaves = Leave.query.order_by(Leave.date).all()
    schedule = []

    for leave in leaves:
        employee = Employee.query.get(leave.employee_id)
        replacement = Replacement.query.filter_by(employee_on_leave_id=employee.id, date=leave.date).first()
        if replacement and replacement.replacement_employee_id:
            replacement_employee = Employee.query.get(replacement.replacement_employee_id)
            replacement_name = replacement_employee.name
        else:
            replacement_name = 'No Replacement'
        schedule.append({
            'employee_name': employee.name,
            'date': leave.date.strftime('%Y-%m-%d'),
            'replacement_name': replacement_name
        })

    return render_template('leave_schedule.html', schedule=schedule)

# New Route for Leave Calendar
@app.route('/leave_calendar')
def leave_calendar():
    return render_template('leave_calendar.html')

# Admin Authentication Routes
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == app.config['ADMIN_USERNAME'] and password == app.config['ADMIN_PASSWORD']:
            session['is_admin'] = True
            session.permanent = True  # Use permanent session for timeout
            return redirect(url_for('index'))
        else:
            error = 'Invalid credentials'
            return render_template('admin_login.html', error=error)
    return render_template('admin_login.html')

@app.before_request
def make_session_permanent():
    if 'is_admin' in session:
        session.permanent = True

@app.route('/admin_logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))

# Admin Dashboard
@app.route('/admin_dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    # Prepare data for graphs and charts
    # Example: Number of leaves per day
    leaves = Leave.query.all()
    leave_counts = {}
    for leave in leaves:
        date_str = leave.date.strftime('%Y-%m-%d')
        leave_counts[date_str] = leave_counts.get(date_str, 0) + 1

    # Prepare data to send to template
    leave_dates = list(leave_counts.keys())
    leave_values = list(leave_counts.values())

    return render_template('admin_dashboard.html', leave_dates=leave_dates, leave_values=leave_values)

# Admin Routes for Editing Employees
@app.route('/edit_employees')
def edit_employees():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    employees = Employee.query.order_by(Employee.employee_number).all()
    return render_template('edit_employees.html', employees=employees)

@app.route('/edit_employee/<int:employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    employee = Employee.query.get_or_404(employee_id)
    if request.method == 'POST':
        new_name = request.form['name']
        if new_name:
            employee.name = new_name
            db.session.commit()
            return redirect(url_for('edit_employees'))
    return render_template('edit_employee.html', employee=employee)

@app.route('/delete_employee/<int:employee_id>', methods=['POST'])
def delete_employee(employee_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    employee = Employee.query.get_or_404(employee_id)
    # Delete associated leaves and replacements
    Leave.query.filter_by(employee_id=employee_id).delete()
    Replacement.query.filter_by(employee_on_leave_id=employee_id).delete()
    Replacement.query.filter_by(replacement_employee_id=employee_id).delete()
    db.session.delete(employee)
    db.session.commit()
    return redirect(url_for('edit_employees'))

# Admin Routes for Editing Leaves
@app.route('/edit_leaves')
def edit_leaves():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    leaves = Leave.query.order_by(Leave.date).all()
    schedule = []

    for leave in leaves:
        employee = Employee.query.get(leave.employee_id)
        replacement = Replacement.query.filter_by(employee_on_leave_id=employee.id, date=leave.date).first()
        if replacement and replacement.replacement_employee_id:
            replacement_employee = Employee.query.get(replacement.replacement_employee_id)
            replacement_name = replacement_employee.name
        else:
            replacement_name = 'No Replacement'
        schedule.append({
            'leave_id': leave.id,
            'employee_name': employee.name,
            'date': leave.date.strftime('%Y-%m-%d'),
            'replacement_name': replacement_name
        })

    return render_template('edit_leaves.html', schedule=schedule)

@app.route('/edit_leave/<int:leave_id>', methods=['GET', 'POST'])
def edit_leave(leave_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    leave = Leave.query.get_or_404(leave_id)
    employee = Employee.query.get(leave.employee_id)
    if request.method == 'POST':
        new_date_str = request.form['date']
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
        # Update leave date
        old_date = leave.date
        leave.date = new_date
        # Update replacement date
        replacement = Replacement.query.filter_by(employee_on_leave_id=employee.id, date=old_date).first()
        if replacement:
            replacement.date = new_date
        db.session.commit()
        return redirect(url_for('edit_leaves'))
    return render_template('edit_leave.html', leave=leave, employee=employee)

@app.route('/delete_leave/<int:leave_id>', methods=['POST'])
def delete_leave(leave_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    leave = Leave.query.get_or_404(leave_id)
    # Delete associated replacement
    Replacement.query.filter_by(employee_on_leave_id=leave.employee_id, date=leave.date).delete()
    db.session.delete(leave)
    db.session.commit()
    return redirect(url_for('edit_leaves'))

if __name__ == '__main__':
    app.run(debug=True)
