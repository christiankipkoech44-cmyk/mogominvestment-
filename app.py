
import os
import re
import uuid
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from functools import wraps

import requests
from flask import (
    Flask, request, redirect, url_for, session, flash,
    render_template_string, abort, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ------------------------------------------------------------
# MOGOM INVESTMENT - Loan and customer management
# ------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-in-railway")

database_url = os.environ.get("DATABASE_URL", "sqlite:///mogom.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", "uploads")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "true").lower() == "true"

db = SQLAlchemy(app)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mogom")

LOAN_TYPES = ("Business Loans", "Financial Support")
CHANNELS = ("Call", "SMS", "WhatsApp", "Email", "In-person")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx"}
DOCUMENT_TYPES = ("National ID", "Loan Form", "Passport Photo", "Business Photo", "Other Document")


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default="employee", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(20), nullable=False, index=True)
    national_id = db.Column(db.String(80), unique=True, nullable=True)
    address = db.Column(db.String(255))
    occupation = db.Column(db.String(160))
    loan_applied_for = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    loans = db.relationship("Loan", backref="customer", lazy=True)
    communications = db.relationship(
        "Communication",
        backref="customer",
        lazy=True,
        order_by="Communication.created_at.desc()"
    )
    documents = db.relationship(
        "CustomerDocument",
        backref="customer",
        lazy=True,
        order_by="CustomerDocument.uploaded_at.desc()"
    )


class CustomerDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    document_type = db.Column(db.String(80), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    uploaded_by = db.Column(db.String(80))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    loan_type = db.Column(db.String(80), default="Business Loans")
    principal = db.Column(db.Numeric(14, 2), nullable=False)
    rate_percent = db.Column(db.Numeric(7, 2), default=0)
    term_months = db.Column(db.Integer, default=1)
    total_due = db.Column(db.Numeric(14, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(14, 2), default=0)
    status = db.Column(db.String(30), default="Pending")
    purpose = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.String(80))
    payments = db.relationship("Payment", backref="loan", lazy=True)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loan.id"), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    reference = db.Column(db.String(120))
    received_by = db.Column(db.String(80))
    paid_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="Posted")
    void_reason = db.Column(db.Text)


class Communication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    channel = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text)
    outcome = db.Column(db.String(255))
    next_followup = db.Column(db.Date)
    employee = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80))
    action = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Prospect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(20), nullable=False, index=True)
    business_type = db.Column(db.String(160))
    location = db.Column(db.String(255))
    feedback = db.Column(db.Text)
    interest = db.Column(db.String(100))
    notes = db.Column(db.Text)
    status = db.Column(db.String(30), default="New")
    next_followup = db.Column(db.Date)
    sms_consent = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    converted_customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    converted_customer = db.relationship(
        "Customer",
        foreign_keys=[converted_customer_id]
    )


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)


class SMSLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(30))
    message = db.Column(db.Text)
    category = db.Column(db.String(80))
    status = db.Column(db.String(30), default="Pending")
    provider_response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_by = db.Column(db.String(80))


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def is_admin():
    user = current_user()
    return bool(user and user.role == "admin")


def log_action(action):
    user = current_user()
    db.session.add(
        AuditLog(
            username=user.username if user else "system",
            action=str(action)
        )
    )


def setting_value(key, default=""):
    item = Setting.query.filter_by(key=key).first()
    return item.value if item and item.value is not None else default


    item = Setting.query.filter_by(key=key).first()
    return item.value if item and item.value is not None else default


def set_setting(key, value):
    item = Setting.query.filter_by(key=key).first()
    if not item:
        item = Setting(key=key)
        db.session.add(item)
    item.value = str(value)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        if not is_admin():
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def normalize_phone(raw):
    value = re.sub(r"[\s\-()]", "", (raw or "").strip())
    if value.startswith("0") and len(value) == 10:
        value = "+254" + value[1:]
    elif value.startswith("254") and len(value) == 12:
        value = "+" + value
    elif value.startswith("7") or value.startswith("1"):
        if len(value) == 9:
            value = "+254" + value
    if not re.fullmatch(r"\+254[17]\d{8}", value):
        raise ValueError("Enter a valid Kenyan mobile number, e.g. 0712345678 or +254712345678.")
    return value


def money(value):
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid amount.")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def care_number():
    return setting_value("customer_care_number", "0721780503")


def acknowledgment_message(kind, name):
    if kind == "prospect":
        return f"Hello {name}, thank you for your interest in MOGOM INVESTMENT. Our team will contact you. For assistance call {care_number()}."
    if kind == "application":
        return f"Hello {name}, we have received your loan application. Our team will review it and contact you. MOGOM INVESTMENT: {care_number()}."
    return f"Hello {name}, welcome to MOGOM INVESTMENT. Your details have been registered. For assistance call {care_number()}."


def send_sms(phone, message, category="General"):
    record = SMSLog(
        recipient=phone, message=message, category=category,
        status="Not configured", sent_by=(current_user().username if current_user() else "system")
    )
    db.session.add(record)
    username = os.environ.get("AT_USERNAME")
    api_key = os.environ.get("AT_API_KEY")
    if not username or not api_key:
        record.provider_response = "Africa's Talking credentials are not configured."
        return record
    try:
        environment = os.environ.get("AT_ENVIRONMENT", "sandbox").lower()
        endpoint = ("https://api.africastalking.com/version1/messaging"
                    if environment == "production"
                    else "https://api.sandbox.africastalking.com/version1/messaging")
        response = requests.post(
            endpoint,
            data={"username": username, "to": phone, "message": message},
            headers={"apiKey": api_key, "Accept": "application/json"},
            timeout=20
        )
        record.provider_response = response.text[:4000]
        record.status = "Submitted" if response.ok else "Failed"
    except requests.RequestException as exc:
        record.status = "Failed"
        record.provider_response = str(exc)[:1000]
        logger.exception("SMS sending failed")
    return record


def migrate_existing_database():
    """Additive migrations only; never drop existing tables or customer data."""
    inspector = inspect(db.engine)
    additions = {
        "user": {
            "created_at": "DATETIME",
        },
        "customer": {
            "loan_applied_for": "VARCHAR(160)",
        },
        "loan": {
            "purpose": "TEXT",
            "approved_by": "VARCHAR(80)",
        },
        "payment": {
            "status": "VARCHAR(20) DEFAULT 'Posted'",
            "void_reason": "TEXT",
        },
        "prospect": {
            "business_type": "VARCHAR(160)",
            "location": "VARCHAR(255)",
            "feedback": "TEXT",
            "interest": "VARCHAR(100)",
            "notes": "TEXT",
            "status": "VARCHAR(30) DEFAULT 'New'",
            "next_followup": "DATE",
            "sms_consent": "BOOLEAN DEFAULT TRUE",
            "converted_customer_id": "INTEGER",
        },
    }
    for table, columns in additions.items():
        if table not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column, sql_type in columns.items():
            if column not in existing:
                db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}'))
    # PostgreSQL supports making the legacy ID column optional without rebuilding the table.
    if db.engine.dialect.name == "postgresql" and "customer" in inspector.get_table_names():
        db.session.execute(text('ALTER TABLE customer ALTER COLUMN national_id DROP NOT NULL'))
    db.session.commit()


def bootstrap():
    with app.app_context():
        db.create_all()
        migrate_existing_database()
        owner_name = os.environ.get("ADMIN_USERNAME", "Christian")
        owner_password = os.environ.get("ADMIN_PASSWORD")
        owner = User.query.filter_by(username=owner_name).first()
        if owner:
            owner.role = "admin"
            owner.active = True
        elif owner_password:
            db.session.add(User(
                username=owner_name,
                password_hash=generate_password_hash(owner_password),
                role="admin",
                active=True
            ))
        if not Setting.query.filter_by(key="customer_care_number").first():
            set_setting("customer_care_number", "0721780503")
        db.session.commit()


BASE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title or 'MOGOM INVESTMENT' }}</title>
<style>
:root{--green:#123c2b;--gold:#e7c76b;--silver:#d8dedb}
*{box-sizing:border-box}body{margin:0;background:#f4f6f4;color:#17231d;font:15px Arial,sans-serif}
header{background:var(--green);color:white;padding:17px 4%;border-bottom:4px solid var(--gold)}
.brand{font-size:22px;font-weight:bold;letter-spacing:1px;color:var(--gold)}
.tag{font-size:12px;color:var(--silver);margin-top:4px}
nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}nav a{color:white;text-decoration:none;padding:8px 10px;background:#ffffff18;border-radius:5px;font-size:13px}
main{max-width:1100px;margin:22px auto;padding:0 14px}.panel{background:white;padding:18px;border-radius:9px;box-shadow:0 2px 10px #0000000c;margin-bottom:16px}
h1{font-size:23px;margin:0 0 16px;color:var(--green)}h2{font-size:18px;color:var(--green)}
input,select,textarea{width:100%;padding:11px;border:1px solid #ccd5cf;border-radius:5px;margin:5px 0 13px;font:inherit}
textarea{min-height:85px}label{font-weight:bold;font-size:13px}
</style></head><body>
<header><div class="brand">MOGOM INVESTMENT</div>
<div class="tag">YOUR FINANCIAL PARTNER</div>
{% if current_user %}
<nav>
<a href="{{ url_for('dashboard') }}">Dashboard</a>
<a href="{{ url_for('customers') }}">Customers</a>
<a href="{{ url_for('loans') }}">Loans</a>
<a href="{{ url_for('payments') }}">Payments</a>
<a href="{{ url_for('prospects') }}">Prospects</a>
<a href="{{ url_for('communications') }}">Communications</a>
<a href="{{ url_for('logout') }}">Logout</a>
</nav>
{% endif %}</header><main>
{% with messages = get_flashed_messages(with_categories=true) %}
{% for category, message in messages %}
<div class="flash {{ category }}">{{ message }}</div>
{% endfor %}{% endwith %}
{{ content|safe }}
</main></body></html>
"""

def page(body, **context):
    context["user"] = current_user()
    return render_template_string(BASE, body=render_template_string(body, **context), **context)


@app.route("/")
def home():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


@app.route("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}, 200
    except Exception as exc:
        logger.exception("Health check failed")
        return {"status": "error", "database": str(exc)[:200]}, 503


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username, active=True).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            log_action("Logged in")
            db.session.commit()
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Incorrect username or password, or the account is inactive.")
    return page("""
    <div class="panel" style="max-width:430px;margin:35px auto"><h1>Staff Login</h1>
    <form method="post"><label>Username</label><input name="username" required autocomplete="username">
    <label>Password</label><input type="password" name="password" required autocomplete="current-password">
    <button type="submit">Sign In</button></form>
    <p class="muted">If the administrator account has not yet been initialized, set ADMIN_PASSWORD in Railway Variables.</p></div>
    """, title="Login")


@app.route("/logout")
@login_required
def logout():
    log_action("Logged out")
    db.session.commit()
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    customers_count = Customer.query.count()
    prospects_count = Prospect.query.count()
    loans_count = Loan.query.count()
    pending = Loan.query.filter_by(status="Pending").count()
    paid = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter_by(status="Posted").scalar()
    outstanding = sum((Decimal(str(l.total_due or 0)) - Decimal(str(l.amount_paid or 0)) for l in Loan.query.filter(Loan.status != "Rejected").all()), Decimal("0"))
    return page("""
    <h1>Dashboard</h1><div class="grid">
    <div class="stat">Customers<b>{{customers_count}}</b></div><div class="stat">Prospects<b>{{prospects_count}}</b></div>
    <div class="stat">Loans<b>{{loans_count}}</b></div><div class="stat">Pending loans<b>{{pending}}</b></div>
    <div class="stat">Payments received<b>KES {{'%.2f'|format(paid|float)}}</b></div>
    <div class="stat">Outstanding balance<b>KES {{'%.2f'|format(outstanding|float)}}</b></div></div>
    <div class="panel"><h2>Quick actions</h2><a class="btn" href="{{url_for('new_customer')}}">Register Customer</a>
    <a class="btn" href="{{url_for('new_prospect')}}">Add Prospect</a><a class="btn" href="{{url_for('new_loan')}}">Create Loan</a></div>
    """, customers_count=customers_count, prospects_count=prospects_count, loans_count=loans_count,
    pending=pending, paid=paid, outstanding=outstanding, title="Dashboard")


@app.route("/customers")
@login_required
def customers():
    rows = Customer.query.order_by(Customer.created_at.desc()).all()
    return page("""
    <h1>Customers</h1><div class="panel"><a class="btn" href="{{url_for('new_customer')}}">Add Customer</a>
    <table><tr><th>Name</th><th>Phone</th><th>National ID</th><th>Loan applied for</th><th>Registered</th><th></th></tr>
    {% for c in rows %}<tr><td>{{c.full_name}}</td><td>{{c.phone}}</td><td>{{c.national_id or '—'}}</td>
    <td>{{c.loan_applied_for or '—'}}</td><td>{{c.created_at.strftime('%d %b %Y') if c.created_at else '—'}}</td>
    <td><a href="{{url_for('customer_detail', customer_id=c.id)}}">Open</a></td></tr>{% endfor %}</table></div>
    """, rows=rows, title="Customers")



@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def new_customer():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()

        try:
            phone = normalize_phone(request.form.get("phone"))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("new_customer"))

        if not name:
            flash("Customer name is required.")
            return redirect(url_for("new_customer"))

        if Customer.query.filter_by(phone=phone).first():
            flash("A customer with this phone number already exists.")
            return redirect(url_for("new_customer"))

        national_id = request.form.get("national_id", "").strip() or None

        if national_id and Customer.query.filter_by(national_id=national_id).first():
            flash("This National ID is already registered.")
            return redirect(url_for("new_customer"))

        customer = Customer(
            full_name=name,
            phone=phone,
            national_id=national_id,
            address=request.form.get("address", "").strip(),
            occupation=request.form.get("occupation", "").strip(),
            loan_applied_for=request.form.get("loan_applied_for", "").strip()
        )

        try:
            db.session.add(customer)
            db.session.flush()

            send_sms(
                phone,
                acknowledgment_message("customer", name),
                "Customer Registration"
            )

            log_action(f"Registered customer: {name}")
            db.session.commit()

            flash("Customer registered successfully.")
            return redirect(url_for(
                "customer_detail",
                customer_id=customer.id
            ))

        except Exception:
            db.session.rollback()
            logger.exception("Customer registration failed")
            flash("Customer registration failed. Please try again.")
            return redirect(url_for("new_customer"))

    return page("""
    <h1>Register New Customer</h1>
    <div class="panel">
    <form method="post">
        <label>Full Name</label>
        <input name="full_name" required>

        <label>Phone Number</label>
        <input name="phone" placeholder="0712345678" required>

        <label>National ID</label>
        <input name="national_id">

        <label>Address</label>
        <input name="address">

        <label>Occupation</label>
        <input name="occupation">

        <label>Loan Applied For</label>
        <select name="loan_applied_for">
            <option value="">Select loan type</option>
            <option value="Business Loans">Business Loans</option>
            <option value="Financial Support">Financial Support</option>
        </select>

        <button type="submit">Register Customer</button>
    </form>
    </div>
    """, title="Register Customer")

    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        if not is_admin():
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def normalize_phone(raw):
    value = re.sub(r"[\s\-()]", "", (raw or "").strip())
    if value.startswith("0") and len(value) == 10:
        value = "+254" + value[1:]
    elif value.startswith("254") and len(value) == 12:
        value = "+" + value
    elif value.startswith("7") or value.startswith("1"):
        if len(value) == 9:
            value = "+254" + value
    if not re.fullmatch(r"\+254[17]\d{8}", value):
        raise ValueError("Enter a valid Kenyan mobile number, e.g. 0712345678 or +254712345678.")
    return value


def money(value):
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid amount.")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def care_number():
    return setting_value("customer_care_number", "0721780503")


def acknowledgment_message(kind, name):
    if kind == "prospect":
        return f"Hello {name}, thank you for your interest in MOGOM INVESTMENT. Our team will contact you. For assistance call {care_number()}."
    if kind == "application":
        return f"Hello {name}, we have received your loan application. Our team will review it and contact you. MOGOM INVESTMENT: {care_number()}."
    return f"Hello {name}, welcome to MOGOM INVESTMENT. Your details have been registered. For assistance call {care_number()}."


def send_sms(phone, message, category="General"):
    record = SMSLog(
        recipient=phone, message=message, category=category,
        status="Not configured", sent_by=(current_user().username if current_user() else "system")
    )
    db.session.add(record)
    username = os.environ.get("AT_USERNAME")
    api_key = os.environ.get("AT_API_KEY")
    if not username or not api_key:
        record.provider_response = "Africa's Talking credentials are not configured."
        return record
    try:
        environment = os.environ.get("AT_ENVIRONMENT", "sandbox").lower()
        endpoint = ("https://api.africastalking.com/version1/messaging"
                    if environment == "production"
                    else "https://api.sandbox.africastalking.com/version1/messaging")
        response = requests.post(
            endpoint,
            data={"username": username, "to": phone, "message": message},
            headers={"apiKey": api_key, "Accept": "application/json"},
            timeout=20
        )
        record.provider_response = response.text[:4000]
        record.status = "Submitted" if response.ok else "Failed"
    except requests.RequestException as exc:
        record.status = "Failed"
        record.provider_response = str(exc)[:1000]
        logger.exception("SMS sending failed")
    return record


def migrate_existing_database():
    """Additive migrations only; never drop existing tables or customer data."""
    inspector = inspect(db.engine)
    additions = {
        "user": {
            "created_at": "DATETIME",
        },
        "customer": {
            "loan_applied_for": "VARCHAR(160)",
        },
        "loan": {
            "purpose": "TEXT",
            "approved_by": "VARCHAR(80)",
        },
        "payment": {
            "status": "VARCHAR(20) DEFAULT 'Posted'",
            "void_reason": "TEXT",
        },
        "prospect": {
            "business_type": "VARCHAR(160)",
            "location": "VARCHAR(255)",
            "feedback": "TEXT",
            "interest": "VARCHAR(100)",
            "notes": "TEXT",
            "status": "VARCHAR(30) DEFAULT 'New'",
            "next_followup": "DATE",
            "sms_consent": "BOOLEAN DEFAULT TRUE",
            "converted_customer_id": "INTEGER",
        },
    }
    for table, columns in additions.items():
        if table not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column, sql_type in columns.items():
            if column not in existing:
                db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}'))
    # PostgreSQL supports making the legacy ID column optional without rebuilding the table.
    if db.engine.dialect.name == "postgresql" and "customer" in inspector.get_table_names():
        db.session.execute(text('ALTER TABLE customer ALTER COLUMN national_id DROP NOT NULL'))
    db.session.commit()


def bootstrap():
    with app.app_context():
        db.create_all()
        migrate_existing_database()
        owner_name = os.environ.get("ADMIN_USERNAME", "Christian")
        owner_password = os.environ.get("ADMIN_PASSWORD")
        owner = User.query.filter_by(username=owner_name).first()
        if owner:
            owner.role = "admin"
            owner.active = True
        elif owner_password:
            db.session.add(User(
                username=owner_name,
                password_hash=generate_password_hash(owner_password),
                role="admin",
                active=True
            ))
        if not Setting.query.filter_by(key="customer_care_number").first():
            set_setting("customer_care_number", "0721780503")
        db.session.commit()


BASE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title or 'MOGOM INVESTMENT' }}</title>
<style>
:root{--green:#123c2b;--gold:#e7c76b;--silver:#d8dedb}
*{box-sizing:border-box}body{margin:0;background:#f4f6f4;color:#17231d;font:15px Arial,sans-serif}
header{background:var(--green);color:white;padding:17px 4%;border-bottom:4px solid var(--gold)}
.brand{font-size:22px;font-weight:bold;letter-spacing:1px;color:var(--gold)}
.tag{font-size:12px;color:var(--silver);margin-top:4px}
nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}nav a{color:white;text-decoration:none;padding:8px 10px;background:#ffffff18;border-radius:5px;font-size:13px}
main{max-width:1100px;margin:22px auto;padding:0 14px}.panel{background:white;padding:18px;border-radius:9px;box-shadow:0 2px 10px #0000000c;margin-bottom:16px}
h1{font-size:23px;margin:0 0 16px;color:var(--green)}h2{font-size:18px;color:var(--green)}
input,select,textarea{width:100%;padding:11px;border:1px solid #ccd5cf;border-radius:5px;margin:5px 0 13px;font:inherit}
textarea{min-height:85px}label{font-weight:bold;font-size:13px}
button,.btn{background:var(--green);color:white;padding:10px 14px;border:0;border-radius:5px;text-decoration:none;display:inline-block;cursor:pointer}
.btn.gold{background:#9b7826}.danger{background:#9c2f2f}.muted{color:#68756d;font-size:13px}
table{width:100%;border-collapse:collapse;display:block;overflow-x:auto;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #e4e9e5;text-align:left}th{background:#edf2ee;color:#234333}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.stat{background:#f0f5f1;padding:15px;border-radius:7px}.stat b{font-size:22px;color:var(--green);display:block;margin-top:5px}
.flash{padding:11px;background:#fff4d7;border-left:4px solid #c59a35;margin-bottom:12px;border-radius:4px}
footer{text-align:center;color:#77837c;padding:25px;font-size:12px}
@media(max-width:600px){header{padding:14px}main{margin:14px auto}.panel{padding:14px}}
</style></head><body><header><div class="brand">MOGOM INVESTMENT</div><div class="tag">YOUR FINANCIAL PARTNER</div>
{% if user %}<nav>
<a href="{{url_for('dashboard')}}">Dashboard</a><a href="{{url_for('customers')}}">Customers</a>
<a href="{{url_for('new_customer')}}">Add Customer</a><a href="{{url_for('prospects')}}">Prospects</a>
<a href="{{url_for('new_prospect')}}">Add Prospect</a><a href="{{url_for('loans')}}">Loans</a>
<a href="{{url_for('new_loan')}}">New Loan</a><a href="{{url_for('reports')}}">Reports</a>
{% if user.role == 'admin' %}<a href="{{url_for('employees')}}">Employees</a><a href="{{url_for('settings')}}">Settings</a>
<a href="{{url_for('sms_logs')}}">SMS Logs</a><a href="{{url_for('audit_logs')}}">Audit Log</a>{% endif %}
<a href="{{url_for('logout')}}">Logout ({{user.username}})</a></nav>{% endif %}</header>
<main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="flash">{{message}}</div>{% endfor %}{% endwith %}
{{body|safe}}</main><footer>MOGOM INVESTMENT · Your Financial Partner</footer></body></html>
"""


def page(body, **context):
    context["user"] = current_user()
    return render_template_string(BASE, body=render_template_string(body, **context), **context)





@app.route("/dashboard")
@login_required
def dashboard():
    customers_count = Customer.query.count()
    prospects_count = Prospect.query.count()
    loans_count = Loan.query.count()
    pending = Loan.query.filter_by(status="Pending").count()
    paid = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter_by(status="Posted").scalar()
    outstanding = sum((Decimal(str(l.total_due or 0)) - Decimal(str(l.amount_paid or 0)) for l in Loan.query.filter(Loan.status != "Rejected").all()), Decimal("0"))
    return page("""
    <h1>Dashboard</h1><div class="grid">
    <div class="stat">Customers<b>{{customers_count}}</b></div><div class="stat">Prospects<b>{{prospects_count}}</b></div>
    <div class="stat">Loans<b>{{loans_count}}</b></div><div class="stat">Pending loans<b>{{pending}}</b></div>
    <div class="stat">Payments received<b>KES {{'%.2f'|format(paid|float)}}</b></div>
    <div class="stat">Outstanding balance<b>KES {{'%.2f'|format(outstanding|float)}}</b></div></div>
    <div class="panel"><h2>Quick actions</h2><a class="btn" href="{{url_for('new_customer')}}">Register Customer</a>
    <a class="btn" href="{{url_for('new_prospect')}}">Add Prospect</a><a class="btn" href="{{url_for('new_loan')}}">Create Loan</a></div>
    """, customers_count=customers_count, prospects_count=prospects_count, loans_count=loans_count,
    pending=pending, paid=paid, outstanding=outstanding, title="Dashboard")


@app.route("/customers")
@login_required
def customers():
    rows = Customer.query.order_by(Customer.created_at.desc()).all()
    return page("""
    <h1>Customers</h1><div class="panel"><a class="btn" href="{{url_for('new_customer')}}">Add Customer</a>
    <table><tr><th>Name</th><th>Phone</th><th>National ID</th><th>Loan applied for</th><th>Registered</th><th></th></tr>
    {% for c in rows %}<tr><td>{{c.full_name}}</td><td>{{c.phone}}</td><td>{{c.national_id or '—'}}</td>
    <td>{{c.loan_applied_for or '—'}}</td><td>{{c.created_at.strftime('%d %b %Y') if c.created_at else '—'}}</td>
    <td><a href="{{url_for('customer_detail', customer_id=c.id)}}">Open</a></td></tr>{% endfor %}</table></div>
    """, rows=rows, title="Customers")


@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def new_customer():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        try:
            phone = normalize_phone(request.form.get("phone"))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("new_customer"))
        if not name:
            flash("Customer name is required.")
            return redirect(url_for("new_customer"))
        if Customer.query.filter_by(phone=phone).first() or Prospect.query.filter_by(phone=phone).first():
            flash("This phone number already exists as a customer or prospect. Open the existing record instead of adding it again.")
            return redirect(url_for("new_customer"))
        national_id = request.form.get("national_id", "").strip() or None
        if national_id and Customer.query.filter_by(national_id=national_id).first():
            flash("That National ID is already registered.")
            return redirect(url_for("new_customer"))
        # Older SQLite databases may still enforce NOT NULL on national_id.
        if not national_id and db.engine.dialect.name == "sqlite":
            national_id = "OPTIONAL-" + uuid.uuid4().hex
        customer = Customer(
            full_name=name, phone=phone, national_id=national_id,
            address=request.form.get("address", "").strip(),
            occupation=request.form.get("occupation", "").strip(),
            loan_applied_for=request.form.get("loan_applied_for", "").strip()
        )
        db.session.add(customer)
        db.session.flush()
        for field in ("national_id_file", "loan_form", "passport_photo", "business_photo", "other_document"):
            uploaded = request.files.get(field)
            if uploaded and uploaded.filename:
                if not allowed_file(uploaded.filename):
                    flash("A document was skipped because its file type is not allowed.")
                    continue
                original = secure_filename(uploaded.filename)
                stored = uuid.uuid4().hex + "_" + original
                uploaded.save(os.path.join(app.config["UPLOAD_FOLDER"], stored))
                doc_type = {
                    "national_id_file": "National ID", "loan_form": "Loan Form",
                    "passport_photo": "Passport Photo", "business_photo": "Business Photo",
                    "other_document": "Other Document"
                }[field]
                db.session.add(CustomerDocument(
                    customer_id=customer.id, document_type=doc_type,
                    original_name=original, stored_name=stored,
                    uploaded_by=current_user().username
                ))
        send_sms(phone, acknowledgment_message("customer", name), "Customer registration")
        log_action(f"Registered customer {name} ({phone})")
        db.session.commit()
        flash("Customer registered successfully. SMS status is recorded in SMS Logs.")
        return redirect(url_for("customer_detail", customer_id=customer.id))
    return page("""
    <h1>Register Customer</h1><div class="panel"><form method="post" enctype="multipart/form-data">
    <label>Full name *</label><input name="full_name" required>
    <label>Phone number (Kenyan number) *</label><input name="phone" placeholder="0712345678 or +254712345678" required>
    <label>National ID (optional)</label><input name="national_id">
    <label>Location / Address</label><input name="address">
    <label>Business / Occupation</label><input name="occupation">
    <label>Loan applied for</label><input name="loan_applied_for" placeholder="e.g. KES 20,000">
    <h2>Customer documents</h2><label>National ID</label><input type="file" name="national_id_file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx">
    <label>Loan Form</label><input type="file" name="loan_form" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx">
    <label>Passport Photo</label><input type="file" name="passport_photo" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx">
    <label>Business Photo</label><input type="file" name="business_photo" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx">
    <label>Other Document</label><input type="file" name="other_document" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx">
    <button type="submit">Save Customer</button></form></div>
    """, title="Add Customer")


@app.route("/customers/<int:customer_id>")
@login_required
def customer_detail(customer_id):
    customer = db.get_or_404(Customer, customer_id)
    return page("""
    <h1>{{customer.full_name}}</h1><div class="panel"><p><b>Phone:</b> {{customer.phone}}</p>
    <p><b>National ID:</b> {{customer.national_id if customer.national_id and not customer.national_id.startswith('OPTIONAL-') else 'Not provided'}}</p>
    <p><b>Location:</b> {{customer.address or '—'}} · <b>Business:</b> {{customer.occupation or '—'}}</p>
    <p><b>Loan applied for:</b> {{customer.loan_applied_for or '—'}}</p>
    <a class="btn" href="{{url_for('new_loan', customer_id=customer.id)}}">Create Loan</a>
    </div>
    <div class="panel"><h2>Documents</h2>{% for d in customer.documents %}
    <p>{{d.document_type}} — {{d.original_name}} · <a href="{{url_for('download_document', document_id=d.id)}}">View / Download</a></p>
    {% else %}<p class="muted">No documents uploaded.</p>{% endfor %}</div>
    <div class="panel"><h2>Record an interaction</h2><form method="post" action="{{url_for('add_communication', customer_id=customer.id)}}">
    <label>Channel</label><select name="channel">{% for ch in channels %}<option>{{ch}}</option>{% endfor %}</select>
    <label>Notes / Message</label><textarea name="notes" required></textarea><label>Outcome</label><input name="outcome">
    <label>Next follow-up date</label><input type="date" name="next_followup"><button>Save Interaction</button></form></div>
    <div class="panel"><h2>Communication history</h2>{% for item in customer.communications %}
    <p><b>{{item.channel}}</b> · {{item.created_at.strftime('%d %b %Y %H:%M') if item.created_at else ''}} · {{item.employee or ''}}
    <br>{{item.notes}}<br><span class="muted">Outcome: {{item.outcome or '—'}} · Follow-up: {{item.next_followup or '—'}}</span></p><hr>
    {% else %}<p class="muted">No interactions recorded yet.</p>{% endfor %}</div>
    <div class="panel"><h2>Loans</h2>{% for loan in customer.loans %}<p><a href="{{url_for('loan_detail', loan_id=loan.id)}}">Loan #{{loan.id}}</a> · KES {{loan.principal}} · {{loan.status}}</p>{% else %}<p>No loans yet.</p>{% endfor %}</div>
    """, customer=customer, channels=CHANNELS, title=customer.full_name)


@app.route("/customers/<int:customer_id>/communication", methods=["POST"])
@login_required
def add_communication(customer_id):
    customer = db.get_or_404(Customer, customer_id)
    channel = request.form.get("channel", "")
    if channel not in CHANNELS:
        abort(400)
    followup = request.form.get("next_followup") or None
    db.session.add(Communication(
        customer_id=customer.id, channel=channel,
        notes=request.form.get("notes", "").strip(),
        outcome=request.form.get("outcome", "").strip(),
        next_followup=date.fromisoformat(followup) if followup else None,
        employee=current_user().username
    ))
    log_action(f"Added {channel} communication for customer #{customer.id}")
    db.session.commit()
    flash("Interaction saved.")
    return redirect(url_for("customer_detail", customer_id=customer.id))


@app.route("/documents/<int:document_id>")
@login_required
def download_document(document_id):
    doc = db.get_or_404(CustomerDocument, document_id)
    return send_from_directory(app.config["UPLOAD_FOLDER"], doc.stored_name,
                               as_attachment=False, download_name=doc.original_name)


@app.route("/prospects")
@login_required
def prospects():
    rows = Prospect.query.order_by(Prospect.created_at.desc()).all()
    return page("""
    <h1>Prospects</h1><div class="panel"><a class="btn" href="{{url_for('new_prospect')}}">Add Prospect</a>
    <table><tr><th>Name</th><th>Phone</th><th>Business</th><th>Location</th><th>Feedback</th><th>Status</th><th></th></tr>
    {% for p in rows %}<tr><td>{{p.full_name}}</td><td>{{p.phone}}</td><td>{{p.business_type or '—'}}</td>
    <td>{{p.location or '—'}}</td><td>{{p.feedback or '—'}}</td><td>{{p.status}}</td>
    <td><a href="{{url_for('prospect_detail', prospect_id=p.id)}}">Open</a></td></tr>{% endfor %}</table></div>
    """, rows=rows, title="Prospects")


@app.route("/prospects/new", methods=["GET", "POST"])
@login_required
def new_prospect():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        try:
            phone = normalize_phone(request.form.get("phone"))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("new_prospect"))
        if not name:
            flash("Prospect name is required.")
            return redirect(url_for("new_prospect"))
        if Customer.query.filter_by(phone=phone).first() or Prospect.query.filter_by(phone=phone).first():
            flash("This phone number already exists as a customer or prospect. The record was not duplicated.")
            return redirect(url_for("new_prospect"))
        prospect = Prospect(
            full_name=name, phone=phone,
            business_type=request.form.get("business_type", "").strip(),
            location=request.form.get("location", "").strip(),
            feedback=request.form.get("feedback", "").strip()
        )
        db.session.add(prospect)
        send_sms(phone, acknowledgment_message("prospect", name), "Prospect registration")
        log_action(f"Added prospect {name} ({phone})")
        db.session.commit()
        flash("Prospect saved. SMS status is recorded in SMS Logs.")
        return redirect(url_for("prospect_detail", prospect_id=prospect.id))
    return page("""
    <h1>Add Prospect</h1><div class="panel"><form method="post">
    <label>Name *</label><input name="full_name" required>
    <label>Phone number *</label><input name="phone" placeholder="0712345678 or +254712345678" required>
    <label>Type of business</label><input name="business_type">
    <label>Location</label><input name="location">
    <label>Feedback</label><textarea name="feedback"></textarea>
    <button>Save Prospect</button></form></div>
    """, title="Add Prospect")


@app.route("/prospects/<int:prospect_id>")
@login_required
def prospect_detail(prospect_id):
    prospect = db.get_or_404(Prospect, prospect_id)
    return page("""
    <h1>{{prospect.full_name}}</h1><div class="panel"><p><b>Phone:</b> {{prospect.phone}}</p>
    <p><b>Business:</b> {{prospect.business_type or '—'}}</p><p><b>Location:</b> {{prospect.location or '—'}}</p>
    <p><b>Feedback:</b> {{prospect.feedback or '—'}}</p><p><b>Status:</b> {{prospect.status}}</p>
    {% if prospect.converted_customer_id %}<p>Converted customer: <a href="{{url_for('customer_detail', customer_id=prospect.converted_customer_id)}}">Open customer</a></p>
    {% else %}<form method="post" action="{{url_for('convert_prospect', prospect_id=prospect.id)}}"><button>Convert to Customer</button></form>{% endif %}
    <form method="post" action="{{url_for('update_prospect', prospect_id=prospect.id)}}"><label>Update status</label>
    <select name="status">{% for s in ['New','Contacted','Interested','Not Interested','Converted'] %}<option {% if prospect.status==s %}selected{% endif %}>{{s}}</option>{% endfor %}</select>
    <label>Follow-up date</label><input type="date" name="next_followup" value="{{prospect.next_followup or ''}}"><button>Update Prospect</button></form></div>
    """, prospect=prospect, title="Prospect")

@app.route("/prospects/<int:prospect_id>/update", methods=["POST"])
@login_required
def update_prospect(prospect_id):
    prospect = db.get_or_404(Prospect, prospect_id)
    prospect.status = request.form.get("status", prospect.status)
    followup = request.form.get("next_followup") or None
    prospect.next_followup = date.fromisoformat(followup) if followup else None
    log_action(f"Updated prospect #{prospect.id}")
    db.session.commit()
    flash("Prospect updated.")
    return redirect(url_for("prospect_detail", prospect_id=prospect.id))


@app.route("/prospects/<int:prospect_id>/convert", methods=["POST"])
@login_required
def convert_prospect(prospect_id):
    prospect = db.get_or_404(Prospect, prospect_id)
    if prospect.converted_customer_id:
        return redirect(url_for("customer_detail", customer_id=prospect.converted_customer_id))
    customer = Customer.query.filter_by(phone=prospect.phone).first()
    if customer:
        flash("A customer with this phone number already exists.")
        return redirect(url_for("customer_detail", customer_id=customer.id))
    customer = Customer(
        full_name=prospect.full_name, phone=prospect.phone,
        address=prospect.location, occupation=prospect.business_type,
        national_id=("OPTIONAL-" + uuid.uuid4().hex if db.engine.dialect.name == "sqlite" else None)
    )
    db.session.add(customer)
    db.session.flush()
    prospect.converted_customer_id = customer.id
    prospect.status = "Converted"
    log_action(f"Converted prospect #{prospect.id} to customer #{customer.id}")
    db.session.commit()
    flash("Prospect converted to customer.")
    return redirect(url_for("customer_detail", customer_id=customer.id))


@app.route("/loans")
@login_required
def loans():
    rows = Loan.query.order_by(Loan.created_at.desc()).all()
    return page("""
    <h1>Loans</h1><div class="panel"><a class="btn" href="{{url_for('new_loan')}}">New Loan</a>
    <table><tr><th>Loan</th><th>Customer</th><th>Principal</th><th>Total Due</th><th>Paid</th><th>Status</th><th></th></tr>
    {% for l in rows %}<tr><td>#{{l.id}}</td><td>{{l.customer.full_name}}</td><td>KES {{l.principal}}</td>
    <td>KES {{l.total_due}}</td><td>KES {{l.amount_paid}}</td><td>{{l.status}}</td>
    <td><a href="{{url_for('loan_detail', loan_id=l.id)}}">Open</a></td></tr>{% endfor %}</table></div>
    """, rows=rows, title="Loans")


@app.route("/loans/new", methods=["GET", "POST"])
@login_required
def new_loan():
    selected = request.args.get("customer_id", type=int)
    if request.method == "POST":
        customer = db.get_or_404(Customer, request.form.get("customer_id", type=int))
        try:
            principal = money(request.form.get("principal"))
            rate = money(request.form.get("rate_percent", "0"))
            months = int(request.form.get("term_months", "1"))
            if principal <= 0 or months < 1 or rate < 0:
                raise ValueError("Principal and term must be positive; rate cannot be negative.")
        except (ValueError, InvalidOperation) as exc:
            flash(str(exc) or "Check the loan figures.")
            return redirect(url_for("new_loan"))
        total = (principal * (Decimal("1") + (rate / Decimal("100")))).quantize(Decimal("0.01"))
        loan = Loan(
            customer_id=customer.id, loan_type=request.form.get("loan_type", "Business Loans"),
            principal=principal, rate_percent=rate, term_months=months,
            total_due=total, amount_paid=Decimal("0.00"),
            purpose=request.form.get("purpose", "").strip(), status="Pending"
        )
        db.session.add(loan)
        send_sms(customer.phone, acknowledgment_message("application", customer.full_name), "Loan application")
        log_action(f"Created loan application #{loan.id or 'new'} for customer #{customer.id}")
        db.session.commit()
        flash("Loan application created and acknowledgment SMS status logged.")
        return redirect(url_for("loan_detail", loan_id=loan.id))
    all_customers = Customer.query.order_by(Customer.full_name).all()
    return page("""
    <h1>Create Loan Application</h1><div class="panel"><form method="post">
    <label>Customer *</label><select name="customer_id" required><option value="">Choose customer</option>
    {% for c in all_customers %}<option value="{{c.id}}" {% if selected==c.id %}selected{% endif %}>{{c.full_name}} — {{c.phone}}</option>{% endfor %}</select>
    <label>Loan type</label><select name="loan_type">{% for t in loan_types %}<option>{{t}}</option>{% endfor %}</select>
    <label>Principal (KES) *</label><input type="number" name="principal" min="1" step="0.01" required>
    <label>Interest rate (%)</label><input type="number" name="rate_percent" min="0" step="0.01" value="0">
    <label>Term (months)</label><input type="number" name="term_months" min="1" value="1" required>
    <label>Purpose</label><textarea name="purpose"></textarea><button>Create Application</button></form>
    <p class="muted">The total due is calculated as principal plus the entered flat interest percentage.</p></div>
    """, all_customers=all_customers, selected=selected, loan_types=LOAN_TYPES, title="New Loan")


@app.route("/loans/<int:loan_id>")
@login_required
def loan_detail(loan_id):
    loan = db.get_or_404(Loan, loan_id)
    payments = Payment.query.filter_by(loan_id=loan.id).order_by(Payment.paid_at.desc()).all()
    return page("""
    <h1>Loan #{{loan.id}}</h1><div class="panel"><p><b>Customer:</b> {{loan.customer.full_name}}</p>
    <p><b>Principal:</b> KES {{loan.principal}} · <b>Total due:</b> KES {{loan.total_due}}</p>
    <p><b>Paid:</b> KES {{loan.amount_paid}} · <b>Balance:</b> KES {{(loan.total_due|float - loan.amount_paid|float)|round(2)}}</p>
    <p><b>Status:</b> {{loan.status}} · <b>Purpose:</b> {{loan.purpose or '—'}}</p>
    {% if loan.status == 'Pending' %}<form method="post" action="{{url_for('approve_loan', loan_id=loan.id)}}"><button>Approve Loan</button></form>
    <form method="post" action="{{url_for('reject_loan', loan_id=loan.id)}}"><button class="danger">Reject Loan</button></form>{% endif %}</div>
    {% if loan.status == 'Approved' or loan.status == 'Active' %}<div class="panel"><h2>Record Payment</h2>
    <form method="post" action="{{url_for('add_payment', loan_id=loan.id)}}"><label>Amount (KES)</label><input type="number" name="amount" min="0.01" step="0.01" required>
    <label>Payment reference</label><input name="reference"><button>Record Payment</button></form></div>{% endif %}
    <div class="panel"><h2>Payment history</h2><table><tr><th>Date</th><th>Amount</th><th>Reference</th><th>Status</th><th>Action</th></tr>
    {% for p in payments %}<tr><td>{{p.paid_at.strftime('%d %b %Y %H:%M') if p.paid_at else ''}}</td><td>KES {{p.amount}}</td>
    <td>{{p.reference or '—'}}</td><td>{{p.status}}</td><td>{% if is_admin and p.status=='Posted' %}
    <form method="post" action="{{url_for('void_payment', payment_id=p.id)}}"><input name="reason" placeholder="Reason for reversal" required><button class="danger">Void</button></form>{% endif %}</td></tr>{% endfor %}</table></div>
    """, loan=loan, payments=payments, is_admin=is_admin(), title=f"Loan {loan.id}")


@app.route("/loans/<int:loan_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_loan(loan_id):
    loan = db.get_or_404(Loan, loan_id)
    loan.status = "Approved"
    loan.approved_by = current_user().username
    log_action(f"Approved loan #{loan.id}")
    db.session.commit()
    flash("Loan approved.")
    return redirect(url_for("loan_detail", loan_id=loan.id))


@app.route("/loans/<int:loan_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_loan(loan_id):
    loan = db.get_or_404(Loan, loan_id)
    loan.status = "Rejected"
    log_action(f"Rejected loan #{loan.id}")
    db.session.commit()
    flash("Loan rejected.")
    return redirect(url_for("loan_detail", loan_id=loan.id))


@app.route("/loans/<int:loan_id>/payment", methods=["POST"])
@login_required
def add_payment(loan_id):
    loan = db.get_or_404(Loan, loan_id)
    if loan.status not in ("Approved", "Active"):
        flash("Payments can only be recorded for approved loans.")
        return redirect(url_for("loan_detail", loan_id=loan.id))
    try:
        amount = money(request.form.get("amount"))
        if amount <= 0:
            raise ValueError("Payment must be greater than zero.")
        balance = Decimal(str(loan.total_due)) - Decimal(str(loan.amount_paid or 0))
        if amount > balance:
            raise ValueError("Payment cannot exceed the outstanding balance.")
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("loan_detail", loan_id=loan.id))
    payment = Payment(
        loan_id=loan.id, amount=amount, reference=request.form.get("reference", "").strip(),
        received_by=current_user().username, status="Posted"
    )
    loan.amount_paid = Decimal(str(loan.amount_paid or 0)) + amount
    if loan.amount_paid >= loan.total_due:
        loan.status = "Completed"
    db.session.add(payment)
    log_action(f"Recorded payment KES {amount} for loan #{loan.id}")
    db.session.commit()
    flash("Payment recorded.")
    return redirect(url_for("loan_detail", loan_id=loan.id))


@app.route("/payments/<int:payment_id>/void", methods=["POST"])
@login_required
@admin_required
def void_payment(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("A reason is required to void a payment.")
        return redirect(url_for("loan_detail", loan_id=payment.loan_id))
    if payment.status == "Posted":
        payment.status = "Voided"
        payment.void_reason = reason
        loan = payment.loan
        loan.amount_paid = max(Decimal("0.00"), Decimal(str(loan.amount_paid or 0)) - Decimal(str(payment.amount)))
        if loan.status == "Completed":
            loan.status = "Approved"
        log_action(f"Voided payment #{payment.id} for loan #{loan.id}: {reason}")
        db.session.commit()
        flash("Payment voided. The original transaction remains in the audit history.")
    return redirect(url_for("loan_detail", loan_id=payment.loan_id))


@app.route("/reports")
@login_required
def reports():
    total_customers = Customer.query.count()
    total_prospects = Prospect.query.count()
    total_loans = Loan.query.count()
    posted = Payment.query.filter_by(status="Posted").all()
    total_collected = sum((Decimal(str(p.amount)) for p in posted), Decimal("0"))
    total_outstanding = sum((Decimal(str(l.total_due)) - Decimal(str(l.amount_paid or 0)) for l in Loan.query.filter(Loan.status.notin_(["Rejected"])).all()), Decimal("0"))
    return page("""
    <h1>Reports</h1><div class="panel"><div class="grid">
    <div class="stat">Customers<b>{{total_customers}}</b></div><div class="stat">Prospects<b>{{total_prospects}}</b></div>
    <div class="stat">Loan applications<b>{{total_loans}}</b></div><div class="stat">Collections<b>KES {{'%.2f'|format(total_collected|float)}}</b></div>
    <div class="stat">Outstanding<b>KES {{'%.2f'|format(total_outstanding|float)}}</b></div></div></div>
    """, total_customers=total_customers, total_prospects=total_prospects,
    total_loans=total_loans, total_collected=total_collected,
    total_outstanding=total_outstanding, title="Reports")


@app.route("/employees")
@login_required
@admin_required
def employees():
    rows = User.query.order_by(User.created_at.desc()).all()
    return page("""
    <h1>Employees</h1><div class="panel"><h2>Create employee account</h2><form method="post" action="{{url_for('create_employee')}}">
    <label>Username</label><input name="username" required><label>Temporary password</label><input type="password" name="password" required minlength="8">
    <button>Create Employee</button></form></div><div class="panel"><h2>Accounts</h2><table><tr><th>Username</th><th>Role</th><th>Active</th><th>Action</th></tr>
    {% for e in rows %}<tr><td>{{e.username}}</td><td>{{e.role}}</td><td>{{'Yes' if e.active else 'No'}}</td><td>
    {% if e.id != user.id %}<form method="post" action="{{url_for('toggle_employee', user_id=e.id)}}"><button>{{'Deactivate' if e.active else 'Activate'}}</button></form>{% endif %}</td></tr>{% endfor %}</table></div>
    """, rows=rows, title="Employees")


@app.route("/employees/create", methods=["POST"])
@login_required
@admin_required
def create_employee():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or len(password) < 8:
        flash("Username is required and password must have at least 8 characters.")
    elif User.query.filter_by(username=username).first():
        flash("That username already exists.")
    else:
        db.session.add(User(username=username, password_hash=generate_password_hash(password), role="employee", active=True))
        log_action(f"Created employee account {username}")
        db.session.commit()
        flash("Employee account created.")
    return redirect(url_for("employees"))


@app.route("/employees/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_employee(user_id):
    employee = db.get_or_404(User, user_id)
    if employee.id == current_user().id:
        flash("You cannot deactivate your own account.")
    elif employee.role == "admin":
        flash("Administrator accounts cannot be deactivated here.")
    else:
        employee.active = not employee.active
        log_action(f"{'Activated' if employee.active else 'Deactivated'} employee {employee.username}")
        db.session.commit()
        flash("Employee account updated.")
    return redirect(url_for("employees"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        try:
            number = normalize_phone(request.form.get("customer_care_number"))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("settings"))
        set_setting("customer_care_number", number)
        log_action("Updated customer care number")
        db.session.commit()
        flash("Customer care number updated.")
    return page("""
    <h1>System Settings</h1><div class="panel"><form method="post">
    <label>Customer care number (Kenyan format)</label><input name="customer_care_number" value="{{number}}" required>
    <button>Save Settings</button></form><p class="muted">This number is included in customer and prospect acknowledgment messages.</p></div>
    """, number=care_number(), title="Settings")


@app.route("/sms-logs")
@login_required
@admin_required
def sms_logs():
    rows = SMSLog.query.order_by(SMSLog.created_at.desc()).limit(300).all()
    return page("""
    <h1>SMS Logs</h1><div class="panel"><table><tr><th>Date</th><th>Recipient</th><th>Category</th><th>Status</th><th>Message</th><th>Provider response</th></tr>
    {% for s in rows %}<tr><td>{{s.created_at.strftime('%d %b %Y %H:%M') if s.created_at else ''}}</td><td>{{s.recipient}}</td>
    <td>{{s.category}}</td><td>{{s.status}}</td><td>{{s.message}}</td><td>{{s.provider_response or '—'}}</td></tr>{% endfor %}</table></div>
    """, rows=rows, title="SMS Logs")


@app.route("/audit")
@login_required
@admin_required
def audit_logs():
    rows = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(500).all()
    return page("""
    <h1>Audit Log</h1><div class="panel"><table><tr><th>Date</th><th>User</th><th>Action</th></tr>
    {% for a in rows %}<tr><td>{{a.created_at.strftime('%d %b %Y %H:%M') if a.created_at else ''}}</td><td>{{a.username}}</td><td>{{a.action}}</td></tr>{% endfor %}</table></div>
    """, rows=rows, title="Audit Log")


@app.errorhandler(403)
def forbidden(_error):
    return page('<div class="panel"><h1>Access denied</h1><p>You do not have permission to access this page.</p></div>'), 403


@app.errorhandler(404)
def not_found(_error):
    return page('<div class="panel"><h1>Not found</h1><p>The requested record or page could not be found.</p></div>'), 404


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))