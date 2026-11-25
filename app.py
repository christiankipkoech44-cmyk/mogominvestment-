
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
            flash("A customer with this phone number