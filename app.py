import os
import io
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'safer_power_secret_key'

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///requisition_system.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email Configuration (Update with actual SMTP credentials)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USER', 'ckjass29@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASS', 'byaglqntpxzvjgof')
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

db = SQLAlchemy(app)
mail = Mail(app)

# Hierarchy Constants
ROLES = ['Employee', 'Supervisor', 'HR', 'Procurement', 'Finance', 'GM']

# ------------------ Database Models ------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False) # Employee, Supervisor, HR, etc.

class Requisition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requestor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Pending Supervisor Approval')
    current_approver_role = db.Column(db.String(50), default='Supervisor')
    
    requestor = db.relationship('User', backref='requisitions')
    items = db.relationship('RequisitionItem', backref='requisition', cascade="all, delete-orphan")

class RequisitionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requisition_id = db.Column(db.Integer, db.ForeignKey('requisition.id'), nullable=False)
    description = db.Column(db.String(250), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    estimated_cost = db.Column(db.Float, nullable=False) # In KES

# ------------------ Helper Functions ------------------

def send_email_notification(recipient_email, subject, body_text):
    try:
        msg = Message(subject, recipients=[recipient_email])
        msg.body = body_text
        mail.send(msg)
    except Exception as e:
        print(f"Failed to send email to {recipient_email}: {e}")

def route_to_next_approver(requisition):
    hierarchy = ['Supervisor', 'HR', 'Procurement', 'Finance', 'GM']
    try:
        current_index = hierarchy.index(requisition.current_approver_role)
        if current_index + 1 < len(hierarchy):
            next_role = hierarchy[current_index + 1]
            requisition.current_approver_role = next_role
            requisition.status = f'Pending {next_role} Approval'
            
            # Notify next approvers
            approvers = User.query.filter_by(role=next_role).all()
            for approver in approvers:
                send_email_notification(
                    approver.email,
                    f"Action Required: Requisition #{requisition.id} Pending Approval",
                    f"Hello {approver.name},\n\nRequisition #{requisition.id} from {requisition.requestor.name} requires your review.\n\nLog in to the system to take action."
                )
        else:
            requisition.status = 'Approved'
            requisition.current_approver_role = 'None'
            send_email_notification(
                requisition.requestor.email,
                f"Requisition #{requisition.id} Fully Approved!",
                f"Great news {requisition.requestor.name},\n\nYour requisition #{requisition.id} has been fully approved by the GM."
            )
    except ValueError:
        pass
    db.session.commit()

# ------------------ Routes ------------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
def change_password():
    if request.method == 'POST':
        # Processing password updates would happen here
        pass
    
    # Renders your new password reset or change page form
    return render_template('change_password.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        action = request.form.get('action')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if action == 'register':
            name = request.form.get('name')
            role = request.form.get('role')
            if User.query.filter_by(email=email).first():
                flash('Email already registered!', 'danger')
                return redirect(url_for('login'))
            
            hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
            new_user = User(name=name, email=email, password=hashed_pw, role=role)
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
            
        elif action == 'login':
            user = User.query.filter_by(email=email).first()
            if user and check_password_hash(user.password, password):
                session['user_id'] = user.id
                session['user_name'] = user.name
                session['user_role'] = user.role
                flash(f'Welcome back, {user.name}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid credentials. Check email and password.', 'danger')
    
    return render_template('login.html', roles=ROLES)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_role = session['user_role']
    user_id = session['user_id']
    
    if user_role == 'Employee':
        requisitions = Requisition.query.filter_by(requestor_id=user_id).all()
    else:
        # Approvers see items requiring their action OR items already approved past them
        requisitions = Requisition.query.all()

    return render_template('dashboard.html', requisitions=requisitions, role=user_role)

@app.route('/requisition/new', methods=['GET', 'POST'])
def new_requisition():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        reason = request.form.get('reason')
        descriptions = request.form.getlist('description[]')
        quantities = request.form.getlist('quantity[]')
        costs = request.form.getlist('cost[]')
        
        if not descriptions or len(descriptions) == 0:
            flash('You must add at least one item.', 'danger')
            return redirect(url_for('new_requisition'))
            
        req = Requisition(requestor_id=session['user_id'], reason=reason)
        db.session.add(req)
        db.session.flush() # Fetch req.id before committing
        
        for desc, qty, cost in zip(descriptions, quantities, costs):
            if desc.strip():
                item = RequisitionItem(
                    requisition_id=req.id,
                    description=desc,
                    quantity=int(qty),
                    estimated_cost=float(cost)
                )
                db.session.add(item)
                
        db.session.commit()
        
        # Notify initial workflows (Supervisors)
        supervisors = User.query.filter_by(role='Supervisor').all()
        for sup in supervisors:
            send_email_notification(
                sup.email,
                "New Requisition Pending Approval",
                f"Hello {sup.name},\n\nA new requisition #{req.id} has been submitted by {session['user_name']} and requires your review."
            )
            
        flash('Requisition submitted successfully!', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('requisition.html')

@app.route('/requisition/action/<int:req_id>/<string:action>')
def handle_action(req_id, action):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    req = Requisition.query.filter_by(id=req_id).first()
    if not req:
        req = Requisition(id=req_id)
        db.session.add(req)
        db.session.commit()
    
    if req.current_approver_role != session['user_role']:
        flash('You are not authorized to approve this at this stage.', 'danger')
        return redirect(url_for('dashboard'))
        
    if action == 'approve':
        route_to_next_approver(req)
        send_email_notification(req.requestor.email,
        f"Requisition #{req.id} Approved by supervisor",
        f"hello {req.requestor.name},\n\nYuor requisition #{req.id} has been approved by your supervisor and is now pending hr approval."
)
        flash(f'Requisition #{req.id} approved and routed.', 'success')
    elif action == 'reject':
        req.status = f'Rejected by {session["user_role"]}'
        req.current_approver_role = 'None'
        db.session.commit()
        
        send_email_notification(
            req.requestor.email,
            f"Requisition #{req.id} Rejected",
            f"Hello {req.requestor.name},\n\nYour requisition #{req.id} has been rejected by {session['user_role']}."
        )
        flash(f'Requisition #{req.id} has been rejected.', 'warning')
        
    return redirect(url_for('dashboard'))

@app.route('/requisition/delete/<int:req_id>')
def delete_requisition(req_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    req = Requisition.query.get_or_404(req_id)
    if req.requestor_id != session['user_id'] and session['user_role'] != 'GM':
        flash('Unauthorized deletion.', 'danger')
        return redirect(url_for('dashboard'))
        
    db.session.delete(req)
    db.session.commit()
    flash('Requisition canceled and deleted successfully.', 'info')
    return redirect(url_for('dashboard'))
@app.route('/account/delete', methods=['POST'])
def delete_account():
    # Ensure the user is logged in before deleting
    user_id = session.get('user_id')
    if not user_id:
        flash("You must be logged in to perform this action.", "danger")
        return redirect(url_for('login'))
    
    try:
        # Replace 'User' with your actual User model name if it differs
        user_to_delete = User.query.get(user_id)
        
        if user_to_delete:
            # Delete the user from the database session
            db.session.delete(user_to_delete)
            db.session.commit()
            
            # Clear the session to log them out completely
            session.clear()
            
            flash("Your account has been successfully deleted.", "success")
            return redirect(url_for('login'))
        else:
            flash("Account not found.", "danger")
            return redirect(url_for('dashboard'))
            
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while deleting your account: {e}", "danger")
        return redirect(url_for('dashboard'))

@app.route('/export/excel')
def export_excel():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    requisitions = Requisition.query.all()
    data = []
    
    for r in requisitions:
        for item in r.items:
            data.append({
                'Requisition ID': r.id,
                'Requestor Name': r.requestor.name,
                'Requestor Email': r.requestor.email,
                'Reason': r.reason,
                'Date Created': r.date_created.strftime('%Y-%m-%d %H:%M'),
                'Item Description': item.description,
                'Quantity': item.quantity,
                'Cost (KES)': item.estimated_cost,
                'Total Cost (KES)': item.quantity * item.estimated_cost,
                'Status': r.status
            })
            
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Requisitions')
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"Safer_Power_Requisitions_{datetime.now().strftime('%Y%m%d')}.xlsx"
    )

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)