           import os import re import logging from datetime import datetime, date from decimal import Decimal, InvalidOperation from functools import wraps import requests from flask import ( Flask, request, redirect, url_for, session, flash, render_template_string, abort, send_from_directory ) from flask_sqlalchemy import SQLAlchemy from werkzeug.security import check_password_hash, generate_password_hash from werkzeug.utils import secure_filename from sqlalchemy import inspect # ============================================================ # MOGOM INVESTMENT - Loan Management System # Owner/admin: Christian # ============================================================ app = Flask(__name__) app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "CHANGE-ME-IN-RAILWAY") app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024 # 12 MB per request app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", "uploads") app.config["SESSION_COOKIE_HTTPONLY"] = True app.config["SESSION_COOKIE_SAMESITE"] = "Lax" app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "true").lower() == "true" database_url = os.environ.get("DATABASE_URL", "sqlite:///mogom.db") if database_url.startswith("postgres://"): database_url = database_url.replace("postgres://", "postgresql://", 1) app.config["SQLALCHEMY_DATABASE_URI"] = database_url db = SQLAlchemy(app) logging.basicConfig(level=logging.INFO) os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True) LOAN_TYPES = ("Business Loans", "Financial Support") COMMUNICATION_CHANNELS = ("Call", "SMS", "WhatsApp", "Email", "In-person") ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx"} # ----------------------------- MODELS ----------------------------- class User(db.Model): id = db.Column(db.Integer, primary_key=True) username = db.Column(db.String(80), unique=True, nullable=False) password_hash = db.Column(db.String(255), nullable=False) role = db.Column(db.String(30), default="employee", nullable=False) active = db.Column(db.Boolean, default=True, nullable=False) created_at = db.Column(db.DateTime, default=datetime.utcnow) class Customer(db.Model): id = db.Column(db.Integer, primary_key=True) full_name = db.Column(db.String(160), nullable=False) phone = db.Column(db.String(40), nullable=False, index=True) national_id = db.Column(db.String(80), unique=True, nullable=False) address = db.Column(db.String(255)) occupation = db.Column(db.String(120)) created_at = db.Column(db.DateTime, default=datetime.utcnow) loans = db.relationship("Loan", backref="customer", lazy=True) communications = db.relationship( "Communication", backref="customer", lazy=True, order_by="Communication.created_at.desc()" ) documents = db.relationship( "CustomerDocument", backref="customer", lazy=True, order_by="CustomerDocument.uploaded_at.desc()" ) class CustomerDocument(db.Model): id = db.Column(db.Integer, primary_key=True) customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False) document_type = db.Column(db.String(80), nullable=False) original_name = db.Column(db.String(255), nullable=False) stored_name = db.Column(db.String(255), nullable=False) uploaded_by = db.Column(db.String(80)) uploaded_at = db.Column(db.DateTime, default=datetime.utcnow) class Loan(db.Model): id = db.Column(db.Integer, primary_key=True) customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False) loan_type = db.Column(db.String(80), default="Business Loans") principal = db.Column(db.Numeric(12, 2), nullable=False) rate_percent = db.Column(db.Numeric(7, 2), default=0) term_months = db.Column(db.Integer, default=1) total_due = db.Column(db.Numeric(12, 2), nullable=False) amount_paid = db.Column(db.Numeric(12, 2), default=0) status = db.Column(db.String(30), default="Pending") purpose = db.Column(db.Text) created_at = db.Column(db.DateTime, default=datetime.utcnow) approved_by = db.Column(db.String(80)) payments = db.relationship("Payment", backref="loan", lazy=True) class Payment(db.Model): id = db.Column(db.Integer, primary_key=True) loan_id = db.Column(db.Integer, db.ForeignKey("loan.id"), nullable=False) amount = db.Column(db.Numeric(12, 2), nullable=False) reference = db.Column(db.String(120)) received_by = db.Column(db.String(80)) paid_at = db.Column(db.DateTime, default=datetime.utcnow) status = db.Column(db.String(30), default="Posted") void_reason = db.Column(db.String(255)) class Communication(db.Model): id = db.Column(db.Integer, primary_key=True) customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False) channel = db.Column(db.String(30), nullable=False) notes = db.Column(db.Text, nullable=False) outcome = db.Column(db.String(255)) next_followup = db.Column(db.Date) employee = db.Column(db.String(80)) created_at = db.Column(db.DateTime, default=datetime.utcnow) class AuditLog(db.Model): id = db.Column(db.Integer, primary_key=True) username = db.Column(db.String(80)) action = db.Column(db.Text, nullable=False) created_at = db.Column(db.DateTime, default=datetime.utcnow) class Prospect(db.Model): id = db.Column(db.Integer, primary_key=True) full_name = db.Column(db.String(160), nullable=False) phone = db.Column(db.String(40), nullable=False, index=True) business_type = db.Column(db.String(120)) location = db.Column(db.String(255)) feedback = db.Column(db.Text) interest = db.Column(db.String(120)) notes = db.Column(db.Text) status = db.Column(db.String(30), default="New") next_followup = db.Column(db.Date) sms_consent = db.Column(db.Boolean, default=True) created_at = db.Column(db.DateTime, default=datetime.utcnow) converted_customer_id = db.Column(db.Integer, db.ForeignKey("customer.id")) converted_customer = db.relationship("Customer") class Setting(db.Model): id = db.Column(db.Integer, primary_key=True) key = db.Column(db.String(100), unique=True, nullable=False) value = db.Column(db.Text) class SMSLog(db.Model): id = db.Column(db.Integer, primary_key=True) recipient = db.Column(db.String(40), nullable=False) message = db.Column(db.Text, nullable=False) category = db.Column(db.String(40)) status = db.Column(db.String(30), default="Pending") provider_response = db.Column(db.Text) created_at = db.Column(db.DateTime, default=datetime.utcnow) sent_by = db.Column(db.String(80)) # ----------------------------- HELPERS ----------------------------- def current_user(): uid = session.get("user_id") return db.session.get(User, uid) if uid else None def log_action(action): user = current_user() db.session.add(AuditLog( username=user.username if user else "system", action=str(action)[:2000] )) def setting_value(key, default=""): item = Setting.query.filter_by(key=key).first() return item.value if item and item.value is not None else default def set_setting(key, value): item = Setting.query.filter_by(key=key).first() if item is None: db.session.add(Setting(key=key, value=str(value))) else: item.value = str(value) def login_required(fn): @wraps(fn) def wrapped(*args, **kwargs): user = current_user() if not user or not user.active: session.clear() return redirect(url_for("login")) return fn(*args, **kwargs) return wrapped def admin_required(fn): @wraps(fn) @login_required def wrapped(*args, **kwargs): user = current_user() if not user or user.role.lower() != "admin": abort(403) return fn(*args, **kwargs) return wrapped def money(value): return Decimal(str(value or 0)).quantize(Decimal("0.01")) def normalize_phone(value): """Return Kenyan numbers in +254 format; reject malformed numbers.""" phone = re.sub(r"[\s\-()]", "", (value or "").strip()) if phone.startswith("0") and len(phone) == 10: phone = "+254" + phone[1:] elif phone.startswith("254") and len(phone) == 12: phone = "+" + phone elif phone.startswith("7") and len(phone) == 9: phone = "+254" + phone elif phone.startswith("1") and len(phone) == 9: phone = "+254" + phone if not re.fullmatch(r"\+254[17]\d{8}", phone): raise ValueError("Enter a valid Kenyan mobile number, e.g. 0712345678 or +254712345678.") return phone def allowed_file(filename): return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS def parse_decimal(value, label): try: amount = Decimal((value or "").strip()) if not amount.is_finite() or amount < 0: raise InvalidOperation return amount.quantize(Decimal("0.01")) except (InvalidOperation, ValueError): raise ValueError(f"Enter a valid {label}.") def care_number(): return setting_value("customer_care_number", "0721780503") def acknowledgment_message(kind, name): number = care_number() if kind == "prospect": return ( f"Hello {name}, your details have been registered with " f"MOGOM INVESTMENT. Thank you for your interest. " f"For assistance call {number}. Your Financial Partner." ) if kind == "application": return ( f"Hello {name}, we have received your loan application details. " f"Our team will contact you. For assistance call {number}. " "MOGOM INVESTMENT - Your Financial Partner." ) return ( f"Hello {name}, thank you for your continued partnership with " f"MOGOM INVESTMENT. For assistance call {number}. Your Financial Partner." ) def send_sms(phone, message, category="General"): """Log and send an SMS using Africa's Talking.""" sms = SMSLog( recipient=phone, message=message, category=category, status="Pending", sent_by=current_user().username if current_user() else "system" ) db.session.add(sms) db.session.flush() username = os.environ.get("AT_USERNAME") api_key = os.environ.get("AT_API_KEY") if not username or not api_key: sms.status = "Not configured" sms.provider_response = "Set AT_USERNAME and AT_API_KEY in hosting environment variables." return sms environment = os.environ.get("AT_ENVIRONMENT", "sandbox").lower() endpoint = ( "https://api.africastalking.com/version1/messaging" if environment == "production" else "https://api.sandbox.africastalking.com/version1/messaging" ) try: response = requests.post( endpoint, data={"username": username, "to": phone, "message": message}, headers={"apiKey": api_key, "Accept": "application/json"}, timeout=20 ) sms.provider_response = response.text[:4000] if response.ok: payload = response.json() recipients = payload.get("SMSMessageData", {}).get("Recipients", []) success = any( str(r.get("status", "")).lower() == "success" or str(r.get("statusCode", "")) == "101" for r in recipients ) sms.status = "Sent" if success else "Failed" else: sms.status = "Failed" except (requests.RequestException, ValueError) as exc: sms.status = "Failed" sms.provider_response = str(exc)[:1000] return sms def migrate_existing_database(): """Add columns introduced by this version to an existing PostgreSQL/SQLite database.""" additions = { "users": { "created_at": "TIMESTAMP" }, "loans": { "purpose": "TEXT" }, "payments": { "status": "VARCHAR(30) DEFAULT 'Posted'", "void_reason": "VARCHAR(255)" }, "prospects": { "business_type": "VARCHAR(120)", "location": "VARCHAR(255)", "feedback": "TEXT" } } inspector = inspect(db.engine) existing_tables = set(inspector.get_table_names()) with db.engine.begin() as connection: for table_name, columns in additions.items(): if table_name not in existing_tables: continue existing_columns = { column["name"] for column in inspect(db.engine).get_columns(table_name) } for column_name, sql_type in columns.items(): if column_name not in existing_columns: connection.exec_driver_sql( f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}' ) def bootstrap(): """Create tables, safely extend the existing schema, and initialize the owner account.""" db.create_all() migrate_existing_database() owner_name = os.environ.get("ADMIN_USERNAME", "Christian").strip() or "Christian" owner_password = os.environ.get("ADMIN_PASSWORD") owner = User.query.filter_by(username=owner_name).first() if owner is None and owner_password: owner = User( username=owner_name, password_hash=generate_password_hash(owner_password), role="admin", active=True ) db.session.add(owner) log_action("Initial administrator account created") elif owner is not None and owner.role.lower() != "admin": # Preserve the existing account and password; restore owner role. owner.role = "admin" owner.active = True db.session.add(AuditLog( username="system", action=f"Promoted configured owner account {owner_name} to admin" )) if Setting.query.filter_by(key="customer_care_number").first() is None: set_setting("customer_care_number", "0721780503") db.session.commit() with app.app_context(): try: bootstrap() except Exception: logging.exception("Database initialization failed") # ----------------------------- BASE DESIGN ----------------------------- BASE = """ <!doctype html> <html> <head> <meta name="viewport" content="width=device-width, initial-scale=1"> <title>MOGOM INVESTMENT</title> <style> *{box-sizing:border-box} body{font-family:Arial,sans-serif;background:#f4f6f4;margin:0;color:#243329} header{background:#123c2b;color:#e7c76b;padding:18px} header b{font-size:22px} header small{display:block;color:#fff;margin-top:4px} nav{background:#e9eee9;padding:12px;display:flex;gap:12px;flex-wrap:wrap} a{color:#17613e;text-decoration:none} main{padding:18px;max-width:1200px;margin:auto} .card{background:white;padding:16px;margin:12px 0;border-radius:8px;box-shadow:0 1px 5px #ccd4cc;overflow-x:auto} input,select,textarea{box-sizing:border-box;width:100%;padding:10px;margin:5px 0 12px;border:1px solid #b9c5bb;border-radius:5px} textarea{min-height:90px} button,.button{display:inline-block;background:#174b34;color:white;border:0;padding:10px 16px;border-radius:5px;cursor:pointer} button.danger,.danger{background:#8b2525;color:white} table{width:100%;border-collapse:collapse;background:white;min-width:560px} td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top} th{background:#edf2ed} .muted{color:#65736a;font-size:13px} .flash{background:#fff2cc;padding:10px;margin:8px 0;border-radius:5px} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px} .inline{display:inline-block;margin-right:8px} .badge{display:inline-block;padding:4px 8px;background:#e9eee9;border-radius:12px;font-size:12px} h2{margin-top:8px} </style> </head> <body> <header><b>MOGOM INVESTMENT</b><small>Your Financial Partner</small></header> {% if user %} <nav> <a href="{{url_for('dashboard')}}">Dashboard</a> <a href="{{url_for('customers')}}">Customers</a> <a href="{{url_for('new_customer')}}">Add customer</a> <a href="{{url_for('prospects')}}">Prospects</a> <a href="{{url_for('new_prospect')}}">Add prospect</a> <a href="{{url_for('loans')}}">Loans</a> <a href="{{url_for('new_loan')}}">New loan</a> <a href="{{url_for('reports')}}">Reports</a> {% if user.role == 'admin' %} <a href="{{url_for('admin_panel')}}">System Administration</a> <a href="{{url_for('employees')}}">Employees</a> <a href="{{url_for('settings')}}">Settings</a> <a href="{{url_for('sms_logs')}}">SMS logs</a> <a href="{{url_for('audit')}}">Audit log</a> {% endif %} <a href="{{url_for('logout')}}">Logout</a> </nav> {% endif %} <main> {% with messages=get_flashed_messages() %} {% for m in messages %}<div class="flash">{{m}}</div>{% endfor %} {% endwith %} {{content|safe}} </main> </body> </html> """ def page(body, **context): return render_template_string( BASE, content=render_template_string(body, **context), user=current_user() ) # ----------------------------- AUTHENTICATION ----------------------------- @app.route("/") def home(): return redirect(url_for("dashboard") if current_user() else url_for("login")) @app.route("/health") def health(): try: db.session.execute(db.text("SELECT 1")) return {"status": "healthy", "database": "connected"}, 200 except Exception: return {"status": "degraded", "database": "unavailable"}, 503 @app.route("/login", methods=["GET", "POST"]) def login(): if request.method == "POST": username = request.form.get("username", "").strip() user = User.query.filter_by(username=username).first() if user and user.active and check_password_hash( user.password_hash, request.form.get("password", "") ): session.clear() session["user_id"] = user.id log_action("Logged in") db.session.commit() return redirect(url_for("dashboard")) flash("Login failed. Check your username, password or account status.") return page(""" <div class="card"><h2>Staff login</h2> <form method="post"> Username<input name="username" autocomplete="username" required> Password<input name="password" type="password" autocomplete="current-password" required> <button>Sign in</button></form></div> """) @app.route("/logout") @login_required def logout(): log_action("Logged out") db.session.commit() session.clear() return redirect(url_for("login")) # ----------------------------- DASHBOARD ----------------------------- @app.route("/dashboard") @login_required def dashboard(): customers_count = Customer.query.count() prospects_count = Prospect.query.count() loans_count = Loan.query.count() active_count = Loan.query.filter_by(status="Active").count() pending_count = Loan.query.filter_by(status="Pending").count() paid = db.session.query(db.func.sum(Payment.amount)).filter_by(status="Posted").scalar() or 0 outstanding = sum( max(Decimal("0"), money(x.total_due) - money(x.amount_paid)) for x in Loan.query.filter(Loan.status != "Voided").all() ) return page(""" <h2>Dashboard</h2> <div class="grid"> <div class="card">Customers<h2>{{customers}}</h2></div> <div class="card">Prospects<h2>{{prospects}}</h2></div> <div class="card">All loans<h2>{{loans}}</h2></div> <div class="card">Active loans<h2>{{active}}</h2></div> <div class="card">Pending approval<h2>{{pending}}</h2></div> <div class="card">Payments received<h2>KES {{'%.2f'|format(paid)}}</h2></div> <div class="card">Outstanding<h2>KES {{'%.2f'|format(outstanding)}}</h2></div> </div> """, customers=customers_count, prospects=prospects_count, loans=loans_count, active=active_count, pending=pending_count, paid=float(paid), outstanding=float(outstanding)) # ----------------------------- CUSTOMERS ----------------------------- @app.route("/customers") @login_required def customers(): rows = Customer.query.order_by(Customer.created_at.desc()).all() return page(""" <h2>Customers</h2><div class="card"><a class="button" href="{{url_for('new_customer')}}">+ Add customer</a></div> <div class="card"><table><tr><th>Name</th><th>Phone</th><th>National ID</th><th>Created</th><th></th></tr> {% for c in rows %}<tr><td>{{c.full_name}}</td><td>{{c.phone}}</td><td>{{c.national_id}}</td> <td>{{c.created_at.strftime('%d %b %Y %H:%M')}}</td><td><a href="{{url_for('customer_detail',cid=c.id)}}">Open</a></td></tr>{% else %} <tr><td colspan="5">No customers registered.</td></tr>{% endfor %}</table></div> """, rows=rows) @app.route("/customers/new", methods=["GET", "POST"]) @login_required def new_customer(): if request.method == "POST": name = request.form.get("full_name", "").strip() raw_phone = request.form.get("phone", "") national_id = request.form.get("national_id", "").strip() try: phone = normalize_phone(raw_phone) if not name or not national_id: raise ValueError("Name and national ID are required for customer registration.") if Customer.query.filter_by(national_id=national_id).first(): raise ValueError("A customer with that national ID already exists.") if Customer.query.filter_by(phone=phone).first(): raise ValueError("A customer with that phone number already exists.") c = Customer( full_name=name, phone=phone, national_id=national_id, address=request.form.get("address", "").strip(), occupation=request.form.get("occupation", "").strip() ) db.session.add(c) db.session.flush() send_sms(phone, acknowledgment_message("customer", name), "Customer acknowledgement") log_action(f"Registered customer #{c.id}: {name}") db.session.commit() flash("Customer registered. SMS result is available in SMS logs.") return redirect(url_for("customer_detail", cid=c.id)) except ValueError as exc: db.session.rollback() flash(str(exc)) return page(""" <div class="card"><h2>Add customer</h2><form method="post"> Full name<input name="full_name" requi # ============================================================
# PART 2: IMPORTS, APPLICATION SETUP AND DATABASE MODELS
# ============================================================

import os
import re
import uuid
import logging

from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from functools import wraps

import requests

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    flash,
    render_template_string,
    abort,
    send_from_directory
)

from flask_sqlalchemy import SQLAlchemy

from sqlalchemy import inspect, text, func

from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)

from werkzeug.utils import secure_filename


# ---------------- APPLICATION SETUP ----------------

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-in-railway"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

app.config["UPLOAD_FOLDER"] = os.environ.get(
    "UPLOAD_FOLDER",
    "uploads"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "false").lower() == "true"
)

database_url = os.environ.get(
    "DATABASE_URL",
    "sqlite:///mogom_investment.db"
)

if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = database_url

db = SQLAlchemy(app)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("mogom_investment")


# ---------------- SYSTEM CONSTANTS ----------------

LOAN_TYPES = (
    "Business Loans",
    "Financial Support"
)

COMMUNICATION_CHANNELS = (
    "Call",
    "SMS",
    "WhatsApp",
    "Email",
    "In-person"
)

ALLOWED_EXTENSIONS = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "doc",
    "docx"
}


# ---------------- USER MODEL ----------------

class User(db.Model):

    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(30),
        default="employee",
        nullable=False
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# ---------------- CUSTOMER MODEL ----------------

class Customer(db.Model):

    __tablename__ = "customer"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(
        db.String(160),
        nullable=False
    )

    phone = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )

    national_id = db.Column(
        db.String(50),
        unique=True,
        nullable=True
    )

    address = db.Column(db.String(255))

    occupation = db.Column(db.String(160))

    loan_applied_for = db.Column(db.String(160))

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    loans = db.relationship(
        "Loan",
        backref="customer",
        lazy=True
    )

    communications = db.relationship(
        "Communication",
        backref="customer",
        lazy=True,
        order_by="Communication.created_at.desc()"
    )

    documents = db.relationship(
        "CustomerDocument",
        backref="customer",
        lazy=True
    )


# ---------------- CUSTOMER DOCUMENT MODEL ----------------

class CustomerDocument(db.Model):

    __tablename__ = "customer_document"

    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=False
    )

    document_type = db.Column(
        db.String(100),
        nullable=False
    )

    original_name = db.Column(db.String(255))

    stored_name = db.Column(
        db.String(255),
        nullable=False
    )

    uploaded_by = db.Column(db.String(80))

    uploaded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# ---------------- LOAN MODEL ----------------

class Loan(db.Model):

    __tablename__ = "loan"

    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=False
    )

    loan_type = db.Column(
        db.String(100),
        default="Business Loans"
    )

    principal = db.Column(
        db.Numeric(14, 2),
        nullable=False
    )

    rate_percent = db.Column(
        db.Numeric(8, 2),
        default=0
    )

    term_months = db.Column(db.Integer)

    total_due = db.Column(
        db.Numeric(14, 2),
        nullable=False
    )

    amount_paid = db.Column(
        db.Numeric(14, 2),
        default=0
    )

    status = db.Column(
        db.String(30),
        default="Pending"
    )

    purpose = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    approved_by = db.Column(db.String(80))

    payments = db.relationship(
        "Payment",
        backref="loan",
        lazy=True
    )


# ---------------- PAYMENT MODEL ----------------

class Payment(db.Model):

    __tablename__ = "payment"

    id = db.Column(db.Integer, primary_key=True)

    loan_id = db.Column(
        db.Integer,
        db.ForeignKey("loan.id"),
        nullable=False
    )

    amount = db.Column(
        db.Numeric(14, 2),
        nullable=False
    )

    reference = db.Column(db.String(120))

    received_by = db.Column(db.String(80))

    paid_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    status = db.Column(
        db.String(20),
        default="Posted"
    )

    void_reason = db.Column(db.Text)


# ---------------- CUSTOMER COMMUNICATION MODEL ----------------

class Communication(db.Model):

    __tablename__ = "communication"

    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=False
    )

    channel = db.Column(
        db.String(40),
        nullable=False
    )

    notes = db.Column(db.Text)

    outcome = db.Column(db.Text)

    next_followup = db.Column(db.Date)

    employee = db.Column(db.String(80))

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# ---------------- AUDIT LOG MODEL ----------------

class AuditLog(db.Model):

    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(80))

    action = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# ---------------- PROSPECT MODEL ----------------

class Prospect(db.Model):

    __tablename__ = "prospect"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(
        db.String(160),
        nullable=False
    )

    phone = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )

    business_type = db.Column(db.String(160))

    location = db.Column(db.String(255))

    feedback = db.Column(db.Text)

    interest = db.Column(db.String(100))

    notes = db.Column(db.Text)

    status = db.Column(
        db.String(30),
        default="New"
    )

    next_followup = db.Column(db.Date)

    sms_consent = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    converted_customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id")
    )

    converted_customer = db.relationship(
        "Customer",
        foreign_keys=[converted_customer_id]
    )


# ---------------- SETTINGS MODEL ----------------

class Setting(db.Model):

    __tablename__ = "setting"

    id = db.Column(db.Integer, primary_key=True)

    key = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    value = db.Column(db.Text)


# ---------------- SMS LOG MODEL ----------------

class SMSLog(db.Model):

    __tablename__ = "sms_log"

    id = db.Column(db.Integer, primary_key=True)

    recipient = db.Column(
        db.String(30),
        nullable=False
    )

    message = db.Column(db.Text)

    category = db.Column(db.String(80))

    status = db.Column(
        db.String(40),
        default="Pending"
    )

    provider_response = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    sent_by = db.Column(db.String(80))


# ---------------- LOGIN AND ADMIN HELPERS ----------------

def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    return db.session.get(User, user_id)


def is_admin():

    user = current_user()

    return bool(
        user and user.role == "admin"
    )


def log_action(action):

    user = current_user()

    entry = AuditLog(
        username=user.username if user else "system",
        action=str(action)
    )

    db.session.add(entry)


def setting_value(key, default=None):

    setting = Setting.query.filter_by(
        key=key
    ).first()

    if setting:
        return setting.value

    return default


def set_setting(key, value):

    setting = Setting.query.filter_by(
        key=key
    ).first()

    if not setting:
        setting = Setting(key=key)
        db.session.add(setting)

    setting.value = str(value)


def login_required(fn):

    @wraps(fn)
    def wrapped(*args, **kwargs):

        if not current_user():
            return redirect(url_for("login"))

        return fn(*args, **kwargs)

    return wrapped


# END OF PART 2# ============================================================
# PART 3: LOGIN, DASHBOARD AND CUSTOMER MANAGEMENT
# ============================================================


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():

    if current_user():
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# ---------------- HEALTH CHECK ----------------

@app.route("/health")
def health():

    try:
        db.session.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "application": "MOGOM INVESTMENT"
        }, 200

    except Exception:
        logger.exception("Health check failed")

        return {
            "status": "database error"
        }, 500


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        username = request.form.get(
            "username", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        user = User.query.filter_by(
            username=username
        ).first()

        if (
            user
            and user.active
            and check_password_hash(
                user.password_hash,
                password
            )
        ):

            session.clear()

            session["user_id"] = user.id

            log_action("Logged into the system")

            db.session.commit()

            flash("Welcome to MOGOM INVESTMENT.")

            return redirect(url_for("dashboard"))

        flash("Invalid username or password.")

    body = """
    <div class="panel" style="max-width:420px;margin:40px auto;">
        <h1>MOGOM INVESTMENT</h1>

        <p class="muted">Secure employee and administrator login.</p>

        <form method="POST">

            <label>Username</label>
            <input name="username" required autocomplete="username">

            <label>Password</label>
            <input
                type="password"
                name="password"
                required
                autocomplete="current-password"
            >

            <button type="submit">Login</button>

        </form>
    </div>
    """

    return page(body, title="Login")


# ---------------- LOGOUT ----------------

@app.route("/logout")
@login_required
def logout():

    log_action("Logged out")

    db.session.commit()

    session.clear()

    flash("You have logged out.")

    return redirect(url_for("login"))


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
@login_required
def dashboard():

    customer_count = Customer.query.count()

    prospect_count = Prospect.query.count()

    loan_count = Loan.query.count()

    active_loans = Loan.query.filter(
        Loan.status == "Approved"
    ).count()

    pending_loans = Loan.query.filter(
        Loan.status == "Pending"
    ).count()

    total_collections = (
        db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)
        )
        .filter(Payment.status == "Posted")
        .scalar()
    )

    outstanding = (
        db.session.query(
            func.coalesce(
                func.sum(Loan.total_due - Loan.amount_paid),
                0
            )
        )
        .filter(
            Loan.status == "Approved"
        )
        .scalar()
    )

    body = """
    <h1>Dashboard</h1>

    <div class="grid">

        <div class="panel stat">
            Total Customers
            <b>{{customer_count}}</b>
        </div>

        <div class="panel stat">
            Total Prospects
            <b>{{prospect_count}}</b>
        </div>

        <div class="panel stat">
            Total Loans
            <b>{{loan_count}}</b>
        </div>

        <div class="panel stat">
            Approved Loans
            <b>{{active_loans}}</b>
        </div>

        <div class="panel stat">
            Pending Loans
            <b>{{pending_loans}}</b>
        </div>

        <div class="panel stat">
            Total Collections
            <b>KSh {{total_collections}}</b>
        </div>

        <div class="panel stat">
            Outstanding Balance
            <b>KSh {{outstanding}}</b>
        </div>

    </div>

    <div class="panel">
        <h2>Quick Actions</h2>

        <a class="btn" href="{{url_for('new_customer')}}">
            Register Customer
        </a>

        <a class="btn" href="{{url_for('new_prospect')}}">
            Register Prospect
        </a>

        <a class="btn" href="{{url_for('new_loan')}}">
            Create Loan
        </a>
    </div>
    """

    return page(
        body,
        title="Dashboard",
        customer_count=customer_count,
        prospect_count=prospect_count,
        loan_count=loan_count,
        active_loans=active_loans,
        pending_loans=pending_loans,
        total_collections=money(total_collections),
        outstanding=money(outstanding)
    )


# ---------------- CUSTOMER LIST ----------------

@app.route("/customers")
@login_required
def customers():

    search = request.args.get(
        "search", ""
    ).strip()

    query = Customer.query

    if search:

        query = query.filter(
            db.or_(
                Customer.full_name.ilike(
                    f"%{search}%"
                ),
                Customer.phone.ilike(
                    f"%{search}%"
                ),
                Customer.national_id.ilike(
                    f"%{search}%"
                )
            )
        )

    records = query.order_by(
        Customer.created_at.desc()
    ).all()

    body = """
    <div class="panel">

        <h1>Customers</h1>

        <form method="GET">

            <input
                name="search"
                placeholder="Search name, phone or ID"
                value="{{search}}"
            >

            <button type="submit">Search</button>

            <a class="btn" href="{{url_for('new_customer')}}">
                Add Customer
            </a>

        </form>

        <table>

            <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>National ID</th>
                <th>Date Registered</th>
                <th>Action</th>
            </tr>

            {% for customer in records %}

            <tr>

                <td>{{customer.full_name}}</td>

                <td>{{customer.phone}}</td>

                <td>{{customer.national_id or '-'}}</td>

                <td>
                    {{customer.created_at.strftime('%d-%m-%Y') if customer.created_at else '-'}}
                </td>

                <td>
                    <a href="{{url_for('customer_detail', customer_id=customer.id)}}">
                        Open
                    </a>
                </td>

            </tr>

            {% else %}

            <tr>
                <td colspan="5">No customers found.</td>
            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="Customers",
        records=records,
        search=search
    )


# ---------------- ADD CUSTOMER ----------------

@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def new_customer():

    if request.method == "POST":

        name = request.form.get(
            "full_name", ""
        ).strip()

        raw_phone = request.form.get(
            "phone", ""
        ).strip()

        national_id = request.form.get(
            "national_id", ""
        ).strip()

        address = request.form.get(
            "address", ""
        ).strip()

        occupation = request.form.get(
            "occupation", ""
        ).strip()

        loan_applied_for = request.form.get(
            "loan_applied_for", ""
        ).strip()

        try:

            if not name:
                raise ValueError("Customer name is required.")

            phone = normalize_phone(raw_phone)

            if Customer.query.filter_by(
                phone=phone
            ).first():

                raise ValueError(
                    "This phone number already belongs to a customer."
                )

            if Prospect.query.filter_by(
                phone=phone
            ).first():

                raise ValueError(
                    "This phone number already exists as a prospect. "
                    "Please check the prospect record first."
                )

            if national_id and Customer.query.filter_by(
                national_id=national_id
            ).first():

                raise ValueError(
                    "This National ID is already registered."
                )

            customer = Customer(
                full_name=name,
                phone=phone,
                national_id=national_id or None,
                address=address,
                occupation=occupation,
                loan_applied_for=loan_applied_for
            )

            db.session.add(customer)

            db.session.flush()

            log_action(
                f"Registered customer {customer.full_name}, "
                f"customer ID {customer.id}"
            )

            send_sms(
                phone,
                acknowledgment_message(
                    "customer",
                    name
                ),
                "Customer Registration"
            )

            db.session.commit()

            flash("Customer registered successfully.")

            return redirect(
                url_for(
                    "customer_detail",
                    customer_id=customer.id
                )
            )

        except ValueError as exc:

            db.session.rollback()

            flash(str(exc))

        except Exception:

            db.session.rollback()

            logger.exception("Customer registration failed")

            flash(
                "Customer registration failed. Please check the details."
            )

    body = """
    <div class="panel">

        <h1>Register New Customer</h1>

        <form method="POST">

            <label>Full Name</label>
            <input
                name="full_name"
                required
                value="{{request.form.get('full_name', '')}}"
            >

            <label>Phone Number</label>
            <input
                name="phone"
                placeholder="0712345678"
                required
                value="{{request.form.get('phone', '')}}"
            >

            <label>National ID (Optional)</label>
            <input
                name="national_id"
                value="{{request.form.get('national_id', '')}}"
            >

            <label>Address / Location</label>
            <input
                name="address"
                value="{{request.form.get('address', '')}}"
            >

            <label>Occupation / Business</label>
            <input
                name="occupation"
                value="{{request.form.get('occupation', '')}}"
            >

            <label>Loan Applied For</label>
            <input
                name="loan_applied_for"
                placeholder="Business loan or financial support"
                value="{{request.form.get('loan_applied_for', '')}}"
            >

            <button type="submit">Register Customer</button>

        </form>

    </div>
    """

    return page(
        body,
        title="Register Customer",
        request=request
    )


# ---------------- CUSTOMER PROFILE ----------------

@app.route("/customers/<int:customer_id>")
@login_required
def customer_detail(customer_id):

    customer = db.session.get(
        Customer,
        customer_id
    )

    if not customer:
        abort(404)

    body = """
    <div class="panel">

        <h1>{{customer.full_name}}</h1>

        <p><b>Phone:</b> {{customer.phone}}</p>

        <p><b>National ID:</b> {{customer.national_id or '-'}}</p>

        <p><b>Address:</b> {{customer.address or '-'}}</p>

        <p><b>Occupation:</b> {{customer.occupation or '-'}}</p>

        <p><b>Loan Applied For:</b> {{customer.loan_applied_for or '-'}}</p>

        <p><b>Registered:</b>
            {{customer.created_at.strftime('%d-%m-%Y %H:%M') if customer.created_at else '-'}}
        </p>

        <a class="btn"
           href="{{url_for('new_loan', customer_id=customer.id)}}">
            Create Loan
        </a>

        <a class="btn"
           href="{{url_for('add_communication', customer_id=customer.id)}}">
            Record Communication
        </a>

        <a class="btn"
           href="{{url_for('upload_document', customer_id=customer.id)}}">
            Upload Document
        </a>

    </div>

    <div class="panel">

        <h2>Customer Loans</h2>

        <table>

            <tr>
                <th>Loan ID</th>
                <th>Principal</th>
                <th>Total Due</th>
                <th>Paid</th>
                <th>Status</th>
            </tr>

            {% for loan in customer.loans %}

            <tr>
                <td>
                    <a href="{{url_for('loan_detail', loan_id=loan.id)}}">
                        {{loan.id}}
                    </a>
                </td>

                <td>KSh {{loan.principal}}</td>

                <td>KSh {{loan.total_due}}</td>

                <td>KSh {{loan.amount_paid}}</td>

                <td>{{loan.status}}</td>
            </tr>

            {% else %}

            <tr>
                <td colspan="5">No loans registered.</td>
            </tr>

            {% endfor %}

        </table>

    </div>

    <div class="panel">

        <h2>Customer Documents</h2>

        <table>

            <tr>
                <th>Document</th>
                <th>Original File</th>
                <th>Date Uploaded</th>
                <th>Action</th>
            </tr>

            {% for document in customer.documents %}

            <tr>

                <td>{{document.document_type}}</td>

                <td>{{document.original_name}}</td>

                <td>
                    {{document.uploaded_at.strftime('%d-%m-%Y') if document.uploaded_at else '-'}}
                </td>

                <td>
                    <a href="{{url_for('download_document', document_id=document.id)}}">
                        Download
                    </a>
                </td>

            </tr>

            {% else %}

            <tr>
                <td colspan="4">No documents uploaded.</td>
            </tr>

            {% endfor %}

        </table>

    </div>

    <div class="panel">

        <h2>Communication History</h2>

        <table>

            <tr>
                <th>Date</th>
                <th>Channel</th>
                <th>Employee</th>
                <th>Notes</th>
                <th>Outcome</th>
                <th>Follow-up</th>
            </tr>

            {% for item in customer.communications %}

            <tr>

                <td>
                    {{item.created_at.strftime('%d-%m-%Y %H:%M') if item.created_at else '-'}}
                </td>

                <td>{{item.channel}}</td>

                <td>{{item.employee}}</td>

                <td>{{item.notes}}</td>

                <td>{{item.outcome}}</td>

                <td>{{item.next_followup or '-'}}</td>

            </tr>

            {% else %}

            <tr>
                <td colspan="6">No communication recorded.</td>
            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="Customer Profile",
        customer=customer
    )


# END OF PART 3# ============================================================
# PART 4: DOCUMENTS, COMMUNICATIONS, PROSPECTS AND LOANS
# ============================================================


# ---------------- UPLOAD CUSTOMER DOCUMENT ----------------

@app.route(
    "/customers/<int:customer_id>/documents/upload",
    methods=["GET", "POST"]
)
@login_required
def upload_document(customer_id):

    customer = db.session.get(Customer, customer_id)

    if not customer:
        abort(404)

    if request.method == "POST":

        uploaded = request.files.get("document")

        document_type = request.form.get(
            "document_type", "Other Document"
        ).strip()

        if not uploaded or not uploaded.filename:
            flash("Please select a document.")
            return redirect(
                url_for(
                    "upload_document",
                    customer_id=customer_id
                )
            )

        if not allowed_file(uploaded.filename):
            flash("Unsupported file type.")
            return redirect(
                url_for(
                    "upload_document",
                    customer_id=customer_id
                )
            )

        original_name = secure_filename(uploaded.filename)

        stored_name = (
            str(uuid.uuid4())
            + "."
            + original_name.rsplit(".", 1)[1].lower()
        )

        upload_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            stored_name
        )

        try:

            uploaded.save(upload_path)

            record = CustomerDocument(
                customer_id=customer.id,
                document_type=document_type,
                original_name=original_name,
                stored_name=stored_name,
                uploaded_by=current_user().username
            )

            db.session.add(record)

            log_action(
                f"Uploaded {document_type} for customer {customer.id}"
            )

            db.session.commit()

            flash("Document uploaded successfully.")

            return redirect(
                url_for(
                    "customer_detail",
                    customer_id=customer.id
                )
            )

        except Exception:

            db.session.rollback()

            if os.path.exists(upload_path):
                os.remove(upload_path)

            logger.exception("Document upload failed")

            flash("Document upload failed.")

    body = """
    <div class="panel">

        <h1>Upload Customer Document</h1>

        <p>Customer: <b>{{customer.full_name}}</b></p>

        <form method="POST" enctype="multipart/form-data">

            <label>Document Type</label>

            <select name="document_type" required>

                <option>National ID</option>
                <option>Loan Application Form</option>
                <option>Passport Photo</option>
                <option>Business Photo</option>
                <option>Other Document</option>

            </select>

            <label>Select File</label>

            <input
                type="file"
                name="document"
                accept=".pdf,.png,.jpg,.jpeg,.doc,.docx"
                required
            >

            <button type="submit">Upload Document</button>

        </form>

    </div>
    """

    return page(
        body,
        title="Upload Document",
        customer=customer
    )


# ---------------- DOWNLOAD DOCUMENT ----------------

@app.route("/documents/<int:document_id>/download")
@login_required
def download_document(document_id):

    document = db.session.get(
        CustomerDocument,
        document_id
    )

    if not document:
        abort(404)

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        document.stored_name,
        as_attachment=True,
        download_name=document.original_name
    )


# ---------------- RECORD COMMUNICATION ----------------

@app.route(
    "/customers/<int:customer_id>/communications/new",
    methods=["GET", "POST"]
)
@login_required
def add_communication(customer_id):

    customer = db.session.get(
        Customer,
        customer_id
    )

    if not customer:
        abort(404)

    if request.method == "POST":

        channel = request.form.get("channel", "").strip()

        notes = request.form.get("notes", "").strip()

        outcome = request.form.get("outcome", "").strip()

        followup_value = request.form.get(
            "next_followup", ""
        ).strip()

        try:

            if channel not in COMMUNICATION_CHANNELS:
                raise ValueError("Select a valid communication channel.")

            followup = (
                date.fromisoformat(followup_value)
                if followup_value
                else None
            )

            record = Communication(
                customer_id=customer.id,
                channel=channel,
                notes=notes,
                outcome=outcome,
                next_followup=followup,
                employee=current_user().username
            )

            db.session.add(record)

            log_action(
                f"Recorded {channel} communication for customer {customer.id}"
            )

            db.session.commit()

            flash("Communication recorded successfully.")

            return redirect(
                url_for(
                    "customer_detail",
                    customer_id=customer.id
                )
            )

        except ValueError as exc:

            db.session.rollback()

            flash(str(exc))

    body = """
    <div class="panel">

        <h1>Record Customer Communication</h1>

        <p>Customer: <b>{{customer.full_name}}</b></p>

        <form method="POST">

            <label>Communication Channel</label>

            <select name="channel" required>

                {% for channel in channels %}
                <option value="{{channel}}">{{channel}}</option>
                {% endfor %}

            </select>

            <label>Notes / Message</label>

            <textarea name="notes" required></textarea>

            <label>Outcome</label>

            <textarea name="outcome"></textarea>

            <label>Next Follow-up Date</label>

            <input type="date" name="next_followup">

            <button type="submit">Save Communication</button>

        </form>

    </div>
    """

    return page(
        body,
        title="Customer Communication",
        customer=customer,
        channels=COMMUNICATION_CHANNELS
    )


# ---------------- PROSPECT LIST ----------------

@app.route("/prospects")
@login_required
def prospects():

    search = request.args.get("search", "").strip()

    query = Prospect.query

    if search:

        query = query.filter(
            db.or_(
                Prospect.full_name.ilike(f"%{search}%"),
                Prospect.phone.ilike(f"%{search}%"),
                Prospect.location.ilike(f"%{search}%")
            )
        )

    records = query.order_by(
        Prospect.created_at.desc()
    ).all()

    body = """
    <div class="panel">

        <h1>Prospects</h1>

        <form method="GET">

            <input
                name="search"
                placeholder="Search name, phone or location"
                value="{{search}}"
            >

            <button type="submit">Search</button>

            <a class="btn" href="{{url_for('new_prospect')}}">
                Add Prospect
            </a>

        </form>

        <table>

            <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Business</th>
                <th>Location</th>
                <th>Feedback</th>
                <th>Status</th>
            </tr>

            {% for prospect in records %}

            <tr>

                <td>{{prospect.full_name}}</td>
                <td>{{prospect.phone}}</td>
                <td>{{prospect.business_type or '-'}}</td>
                <td>{{prospect.location or '-'}}</td>
                <td>{{prospect.feedback or '-'}}</td>
                <td>{{prospect.status}}</td>

            </tr>

            {% else %}

            <tr>
                <td colspan="6">No prospects found.</td>
            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="Prospects",
        records=records,
        search=search
    )


# ---------------- ADD PROSPECT ----------------

@app.route("/prospects/new", methods=["GET", "POST"])
@login_required
def new_prospect():

    if request.method == "POST":

        name = request.form.get(
            "full_name", ""
        ).strip()

        raw_phone = request.form.get(
            "phone", ""
        ).strip()

        business_type = request.form.get(
            "business_type", ""
        ).strip()

        location = request.form.get(
            "location", ""
        ).strip()

        feedback = request.form.get(
            "feedback", ""
        ).strip()

        try:

            if not name:
                raise ValueError("Prospect name is required.")

            if not business_type:
                raise ValueError("Type of business is required.")

            if not location:
                raise ValueError("Location is required.")

            phone = normalize_phone(raw_phone)

            if Customer.query.filter_by(
                phone=phone
            ).first():

                raise ValueError(
                    "This phone number already belongs to a registered customer."
                )

            if Prospect.query.filter_by(
                phone=phone
            ).first():

                raise ValueError(
                    "This phone number is already registered as a prospect."
                )

            prospect = Prospect(
                full_name=name,
                phone=phone,
                business_type=business_type,
                location=location,
                feedback=feedback,
                status="New"
            )

            db.session.add(prospect)

            log_action(
                f"Registered prospect {name}"
            )

            send_sms(
                phone,
                acknowledgment_message(
                    "prospect",
                    name
                ),
                "Prospect Registration"
            )

            db.session.commit()

            flash("Prospect registered successfully.")

            return redirect(url_for("prospects"))

        except ValueError as exc:

            db.session.rollback()

            flash(str(exc))

        except Exception:

            db.session.rollback()

            logger.exception("Prospect registration failed")

            flash("Prospect registration failed.")

    body = """
    <div class="panel">

        <h1>Register New Prospect</h1>

        <form method="POST">

            <label>Full Name</label>

            <input
                name="full_name"
                required
                value="{{request.form.get('full_name', '')}}"
            >

            <label>Phone Number</label>

            <input
                name="phone"
                placeholder="0712345678"
                required
                value="{{request.form.get('phone', '')}}"
            >

            <label>Type of Business</label>

            <input
                name="business_type"
                required
                value="{{request.form.get('business_type', '')}}"
            >

            <label>Location</label>

            <input
                name="location"
                required
                value="{{request.form.get('location', '')}}"
            >

            <label>Feedback</label>

            <textarea name="feedback">{{request.form.get('feedback', '')}}</textarea>

            <button type="submit">Register Prospect</button>

        </form>

    </div>
    """

    return page(
        body,
        title="Register Prospect",
        request=request
    )


# ---------------- LOAN LIST ----------------

@app.route("/loans")
@login_required
def loans():

    records = Loan.query.order_by(
        Loan.created_at.desc()
    ).all()

    body = """
    <div class="panel">

        <h1>Loan Management</h1>

        <a class="btn" href="{{url_for('new_loan')}}">
            Create New Loan
        </a>

        <table>

            <tr>
                <th>Loan ID</th>
                <th>Customer</th>
                <th>Loan Type</th>
                <th>Principal</th>
                <th>Total Due</th>
                <th>Paid</th>
                <th>Status</th>
                <th>Action</th>
            </tr>

            {% for loan in records %}

            <tr>

                <td>{{loan.id}}</td>

                <td>{{loan.customer.full_name}}</td>

                <td>{{loan.loan_type}}</td>

                <td>KSh {{loan.principal}}</td>

                <td>KSh {{loan.total_due}}</td>

                <td>KSh {{loan.amount_paid}}</td>

                <td>{{loan.status}}</td>

                <td>
                    <a href="{{url_for('loan_detail', loan_id=loan.id)}}">
                        Open
                    </a>
                </td>

            </tr>

            {% else %}

            <tr>
                <td colspan="8">No loans found.</td>
            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="Loans",
        records=records
    )


# ---------------- CREATE LOAN ----------------

@app.route("/loans/new", methods=["GET", "POST"])
@login_required
def new_loan():

    customer_id = request.args.get(
        "customer_id",
        type=int
    )

    selected_customer = (
        db.session.get(Customer, customer_id)
        if customer_id
        else None
    )

    if request.method == "POST":

        try:

            selected_id = int(
                request.form.get("customer_id", "")
            )

            customer = db.session.get(
                Customer,
                selected_id
            )

            if not customer:
                raise ValueError("Select a valid customer.")

            loan_type = request.form.get(
                "loan_type", ""
            ).strip()

            if loan_type not in LOAN_TYPES:
                raise ValueError("Select a valid loan type.")

            principal = money(
                request.form.get("principal")
            )

            rate = money(
                request.form.get("rate_percent", "0")
            )

            months = int(
                request.form.get("term_months", "1")
            )

            if principal <= 0:
                raise ValueError("Loan amount must be greater than zero.")

            if rate < 0:
                raise ValueError("Interest rate cannot be negative.")

            if months <= 0:
                raise ValueError("Loan term must be greater than zero.")

            total_due = (
                principal
                + principal * rate / Decimal("100")
            ).quantize(Decimal("0.01"))

            purpose = request.form.get(
                "purpose", ""
            ).strip()

            loan = Loan(
                customer_id=customer.id,
                loan_type=loan_type,
                principal=principal,
                rate_percent=rate,
                term_months=months,
                total_due=total_due,
                amount_paid=Decimal("0.00"),
                status="Pending",
                purpose=purpose
            )

            db.session.add(loan)

            log_action(
                f"Created loan application for customer {customer.id}"
            )

            send_sms(
                customer.phone,
                acknowledgment_message(
                    "application",
                    customer.full_name
                ),
                "Loan Application"
            )

            db.session.commit()

            flash("Loan application created successfully.")

            return redirect(
                url_for(
                    "loan_detail",
                    loan_id=loan.id
                )
            )

        except (ValueError, InvalidOperation) as exc:

            db.session.rollback()

            flash(str(exc))

        except Exception:

            db.session.rollback()

            logger.exception("Loan creation failed")

            flash("Loan application could not be created.")

    customer_records = Customer.query.order_by(
        Customer.full_name.asc()
    ).all()

    body = """
    <div class="panel">

        <h1>New Loan Application</h1>

        <form method="POST">

            <label>Select Customer</label>

            <select name="customer_id" required>

                <option value="">Choose customer</option>

                {% for customer in customer_records %}

                <option
                    value="{{customer.id}}"
                    {% if selected_customer and selected_customer.id == customer.id %}
                    selected
                    {% endif %}
                >
                    {{customer.full_name}} - {{customer.phone}}
                </option>

                {% endfor %}

            </select>

            <label>Loan Type</label>

            <select name="loan_type" required>

                {% for item in loan_types %}
                <option value="{{item}}">{{item}}</option>
                {% endfor %}

            </select>

            <label>Principal Amount (KSh)</label>

            <input
                type="number"
                name="principal"
                min="1"
                step="0.01"
                required
            >

            <label>Interest Rate (%)</label>

            <input
                type="number"
                name="rate_percent"
                min="0"
                step="0.01"
                value="0"
                required
            >

            <label>Loan Term (Months)</label>

            <input
                type="number"
                name="term_months"
                min="1"
                value="1"
                required
            >

            <label>Loan Purpose</label>

            <textarea name="purpose"></textarea>

            <button type="submit">Submit Loan Application</button>

        </form>

    </div>
    """

    return page(
        body,
        title="New Loan",
        customer_records=customer_records,
        selected_customer=selected_customer,
        loan_types=LOAN_TYPES
    )


# END OF PART 4# ============================================================
# PART 5: PAYMENTS, ADMINISTRATION, REPORTS AND SYSTEM STARTUP
# ============================================================


# ---------------- LOAN DETAILS ----------------

@app.route("/loans/<int:loan_id>")
@login_required
def loan_detail(loan_id):

    loan = db.session.get(Loan, loan_id)

    if not loan:
        abort(404)

    payments = Payment.query.filter_by(
        loan_id=loan.id
    ).order_by(
        Payment.paid_at.desc()
    ).all()

    balance = (
        Decimal(str(loan.total_due or 0))
        - Decimal(str(loan.amount_paid or 0))
    )

    body = """
    <div class="panel">

        <h1>Loan Details #{{loan.id}}</h1>

        <p><b>Customer:</b> {{loan.customer.full_name}}</p>

        <p><b>Phone:</b> {{loan.customer.phone}}</p>

        <p><b>Loan Type:</b> {{loan.loan_type}}</p>

        <p><b>Principal:</b> KSh {{loan.principal}}</p>

        <p><b>Interest:</b> {{loan.rate_percent}}%</p>

        <p><b>Term:</b> {{loan.term_months}} months</p>

        <p><b>Total Due:</b> KSh {{loan.total_due}}</p>

        <p><b>Amount Paid:</b> KSh {{loan.amount_paid}}</p>

        <p><b>Outstanding:</b> KSh {{balance}}</p>

        <p><b>Status:</b> {{loan.status}}</p>

        <p><b>Purpose:</b> {{loan.purpose or '-'}}</p>

        {% if loan.status == 'Pending' and user.role == 'admin' %}

        <form method="POST"
              action="{{url_for('approve_loan', loan_id=loan.id)}}">

            <button type="submit">Approve Loan</button>

        </form>

        {% endif %}

        {% if loan.status == 'Approved' %}

        <a class="btn"
           href="{{url_for('record_payment', loan_id=loan.id)}}">
            Record Payment
        </a>

        {% endif %}

    </div>

    <div class="panel">

        <h2>Payment History</h2>

        <table>

            <tr>
                <th>Date</th>
                <th>Amount</th>
                <th>Reference</th>
                <th>Received By</th>
                <th>Status</th>
                {% if user.role == 'admin' %}
                <th>Action</th>
                {% endif %}
            </tr>

            {% for payment in payments %}

            <tr>

                <td>
                    {{payment.paid_at.strftime('%d-%m-%Y %H:%M') if payment.paid_at else '-'}}
                </td>

                <td>KSh {{payment.amount}}</td>

                <td>{{payment.reference or '-'}}</td>

                <td>{{payment.received_by or '-'}}</td>

                <td>{{payment.status}}</td>

                {% if user.role == 'admin' %}

                <td>

                    {% if payment.status == 'Posted' %}

                    <form method="POST"
                          action="{{url_for('void_payment', payment_id=payment.id)}}">

                        <input
                            name="reason"
                            placeholder="Reason for reversal"
                            required
                        >

                        <button class="danger" type="submit">
                            Reverse
                        </button>

                    </form>

                    {% endif %}

                </td>

                {% endif %}

            </tr>

            {% else %}

            <tr>
                <td colspan="6">No payments recorded.</td>
            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="Loan Details",
        loan=loan,
        payments=payments,
        balance=balance
    )


# ---------------- APPROVE LOAN ----------------

@app.route(
    "/loans/<int:loan_id>/approve",
    methods=["POST"]
)
@admin_required
def approve_loan(loan_id):

    loan = db.session.get(Loan, loan_id)

    if not loan:
        abort(404)

    if loan.status != "Pending":

        flash("Only pending loans can be approved.")

        return redirect(
            url_for("loan_detail", loan_id=loan.id)
        )

    loan.status = "Approved"

    loan.approved_by = current_user().username

    log_action(
        f"Approved loan {loan.id}"
    )

    db.session.commit()

    flash("Loan approved successfully.")

    return redirect(
        url_for("loan_detail", loan_id=loan.id)
    )


# ---------------- RECORD PAYMENT ----------------

@app.route(
    "/loans/<int:loan_id>/payments/new",
    methods=["GET", "POST"]
)
@login_required
def record_payment(loan_id):

    loan = db.session.get(Loan, loan_id)

    if not loan:
        abort(404)

    if loan.status != "Approved":

        flash("Payments can only be recorded for approved loans.")

        return redirect(
            url_for("loan_detail", loan_id=loan.id)
        )

    if request.method == "POST":

        try:

            amount = money(
                request.form.get("amount")
            )

            reference = request.form.get(
                "reference", ""
            ).strip()

            if amount <= 0:
                raise ValueError("Payment must be greater than zero.")

            balance = (
                Decimal(str(loan.total_due))
                - Decimal(str(loan.amount_paid or 0))
            )

            if amount > balance:
                raise ValueError(
                    "Payment cannot exceed the outstanding balance."
                )

            payment = Payment(
                loan_id=loan.id,
                amount=amount,
                reference=reference,
                received_by=current_user().username,
                status="Posted"
            )

            db.session.add(payment)

            loan.amount_paid = (
                Decimal(str(loan.amount_paid or 0))
                + amount
            )

            if loan.amount_paid >= loan.total_due:
                loan.status = "Completed"

            log_action(
                f"Recorded payment of KSh {amount} "
                f"for loan {loan.id}"
            )

            db.session.commit()

            flash("Payment recorded successfully.")

            return redirect(
                url_for("loan_detail", loan_id=loan.id)
            )

        except ValueError as exc:

            db.session.rollback()

            flash(str(exc))

        except Exception:

            db.session.rollback()

            logger.exception("Payment recording failed")

            flash("Payment could not be recorded.")

    body = """
    <div class="panel">

        <h1>Record Loan Payment</h1>

        <p><b>Customer:</b> {{loan.customer.full_name}}</p>

        <p><b>Loan:</b> #{{loan.id}}</p>

        <p><b>Total Due:</b> KSh {{loan.total_due}}</p>

        <p><b>Already Paid:</b> KSh {{loan.amount_paid}}</p>

        <p><b>Outstanding:</b> KSh {{balance}}</p>

        <form method="POST">

            <label>Payment Amount (KSh)</label>

            <input
                type="number"
                name="amount"
                min="0.01"
                step="0.01"
                required
            >

            <label>Payment Reference</label>

            <input
                name="reference"
                placeholder="M-PESA reference or receipt number"
            >

            <button type="submit">Save Payment</button>

        </form>

    </div>
    """

    balance = (
        Decimal(str(loan.total_due))
        - Decimal(str(loan.amount_paid or 0))
    )

    return page(
        body,
        title="Record Payment",
        loan=loan,
        balance=balance
    )


# ---------------- REVERSE PAYMENT ----------------

@app.route(
    "/payments/<int:payment_id>/void",
    methods=["POST"]
)
@admin_required
def void_payment(payment_id):

    payment = db.session.get(
        Payment,
        payment_id
    )

    if not payment:
        abort(404)

    if payment.status != "Posted":

        flash("This payment has already been reversed.")

        return redirect(
            url_for(
                "loan_detail",
                loan_id=payment.loan_id
            )
        )

    reason = request.form.get(
        "reason", ""
    ).strip()

    if not reason:

        flash("A reason is required.")

        return redirect(
            url_for(
                "loan_detail",
                loan_id=payment.loan_id
            )
        )

    loan = payment.loan

    loan.amount_paid = (
        Decimal(str(loan.amount_paid or 0))
        - Decimal(str(payment.amount))
    )

    if loan.amount_paid < 0:
        loan.amount_paid = Decimal("0.00")

    if loan.status == "Completed":
        loan.status = "Approved"

    payment.status = "Voided"

    payment.void_reason = reason

    log_action(
        f"Reversed payment {payment.id} "
        f"for loan {loan.id}. Reason: {reason}"
    )

    db.session.commit()

    flash("Payment reversed. The original record remains in the system.")

    return redirect(
        url_for(
            "loan_detail",
            loan_id=loan.id
        )
    )


# ---------------- EMPLOYEE MANAGEMENT ----------------

@app.route("/employees")
@admin_required
def employees():

    records = User.query.order_by(
        User.username.asc()
    ).all()

    body = """
    <div class="panel">

        <h1>Employee Management</h1>

        <a class="btn" href="{{url_for('new_employee')}}">
            Add Employee
        </a>

        <table>

            <tr>
                <th>Username</th>
                <th>Role</th>
                <th>Status</th>
                <th>Action</th>
            </tr>

            {% for employee in records %}

            <tr>

                <td>{{employee.username}}</td>

                <td>{{employee.role}}</td>

                <td>
                    {{'Active' if employee.active else 'Disabled'}}
                </td>

                <td>
                    <a href="{{url_for('edit_employee', user_id=employee.id)}}">
                        Edit
                    </a>
                </td>

            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="Employees",
        records=records
    )


# ---------------- ADD EMPLOYEE ----------------

@app.route(
    "/employees/new",
    methods=["GET", "POST"]
)
@admin_required
def new_employee():

    if request.method == "POST":

        username = request.form.get(
            "username", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        if not username or not password:

            flash("Username and password are required.")

        elif User.query.filter_by(
            username=username
        ).first():

            flash("That username already exists.")

        elif len(password) < 8:

            flash("Password must have at least 8 characters.")

        else:

            employee = User(
                username=username,
                password_hash=generate_password_hash(password),
                role="employee",
                active=True
            )

            db.session.add(employee)

            log_action(
                f"Created employee account {username}"
            )

            db.session.commit()

            flash("Employee account created.")

            return redirect(url_for("employees"))

    body = """
    <div class="panel">

        <h1>Add Employee</h1>

        <form method="POST">

            <label>Username</label>

            <input name="username" required>

            <label>Temporary Password</label>

            <input
                type="password"
                name="password"
                minlength="8"
                required
            >

            <button type="submit">Create Employee</button>

        </form>

    </div>
    """

    return page(
        body,
        title="Add Employee"
    )


# ---------------- EDIT EMPLOYEE ----------------

@app.route(
    "/employees/<int:user_id>/edit",
    methods=["GET", "POST"]
)
@admin_required
def edit_employee(user_id):

    employee = db.session.get(
        User,
        user_id
    )

    if not employee:
        abort(404)

    if request.method == "POST":

        password = request.form.get(
            "password", ""
        )

        active = request.form.get(
            "active"
        ) == "yes"

        if employee.username == "Christian":

            employee.role = "admin"
            employee.active = True

        else:

            employee.active = active

        if password:

            if len(password) < 8:

                flash("Password must have at least 8 characters.")

                return redirect(
                    url_for(
                        "edit_employee",
                        user_id=employee.id
                    )
                )

            employee.password_hash = generate_password_hash(
                password
            )

        log_action(
            f"Updated employee account {employee.username}"
        )

        db.session.commit()

        flash("Employee updated successfully.")

        return redirect(url_for("employees"))

    body = """
    <div class="panel">

        <h1>Edit Employee</h1>

        <p><b>Username:</b> {{employee.username}}</p>

        <form method="POST">

            <label>Change Password (Optional)</label>

            <input
                type="password"
                name="password"
                minlength="8"
            >

            {% if employee.username != 'Christian' %}

            <label>Account Status</label>

            <select name="active">

                <option
                    value="yes"
                    {% if employee.active %}selected{% endif %}
                >
                    Active
                </option>

                <option
                    value="no"
                    {% if not employee.active %}selected{% endif %}
                >
                    Disabled
                </option>

            </select>

            {% else %}

            <p class="muted">
                The main administrator account cannot be disabled here.
            </p>

            {% endif %}

            <button type="submit">Save Changes</button>

        </form>

    </div>
    """

    return page(
        body,
        title="Edit Employee",
        employee=employee
    )


# ---------------- SYSTEM SETTINGS ----------------

@app.route(
    "/settings",
    methods=["GET", "POST"]
)
@admin_required
def settings():

    if request.method == "POST":

        phone = request.form.get(
            "customer_care_number", ""
        ).strip()

        try:

            normalized = normalize_phone(phone)

            set_setting(
                "customer_care_number",
                normalized
            )

            log_action(
                "Updated customer care phone number"
            )

            db.session.commit()

            flash("Settings updated successfully.")

        except ValueError as exc:

            db.session.rollback()

            flash(str(exc))

    body = """
    <div class="panel">

        <h1>System Settings</h1>

        <form method="POST">

            <label>Customer Care Number</label>

            <input
                name="customer_care_number"
                value="{{care_number}}"
                required
            >

            <button type="submit">Save Settings</button>

        </form>

        <p class="muted">
            This number appears in customer and prospect SMS messages.
        </p>

    </div>
    """

    return page(
        body,
        title="Settings",
        care_number=care_number()
    )


# ---------------- SMS LOGS ----------------

@app.route("/sms-logs")
@admin_required
def sms_logs():

    records = SMSLog.query.order_by(
        SMSLog.created_at.desc()
    ).limit(500).all()

    body = """
    <div class="panel">

        <h1>SMS Communication Logs</h1>

        <table>

            <tr>
                <th>Date</th>
                <th>Recipient</th>
                <th>Category</th>
                <th>Message</th>
                <th>Status</th>
            </tr>

            {% for item in records %}

            <tr>

                <td>
                    {{item.created_at.strftime('%d-%m-%Y %H:%M') if item.created_at else '-'}}
                </td>

                <td>{{item.recipient}}</td>

                <td>{{item.category}}</td>

                <td>{{item.message}}</td>

                <td>{{item.status}}</td>

            </tr>

            {% else %}

            <tr>
                <td colspan="5">No SMS records found.</td>
            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="SMS Logs",
        records=records
    )


# ---------------- AUDIT LOGS ----------------

@app.route("/audit-logs")
@admin_required
def audit_logs():

    records = AuditLog.query.order_by(
        AuditLog.created_at.desc()
    ).limit(1000).all()

    body = """
    <div class="panel">

        <h1>System Audit Trail</h1>

        <table>

            <tr>
                <th>Date</th>
                <th>Employee</th>
                <th>Action</th>
            </tr>

            {% for item in records %}

            <tr>

                <td>
                    {{item.created_at.strftime('%d-%m-%Y %H:%M') if item.created_at else '-'}}
                </td>

                <td>{{item.username}}</td>

                <td>{{item.action}}</td>

            </tr>

            {% else %}

            <tr>
                <td colspan="3">No audit records found.</td>
            </tr>

            {% endfor %}

        </table>

    </div>
    """

    return page(
        body,
        title="Audit Logs",
        records=records
    )


# ---------------- REPORTS ----------------

@app.route("/reports")
@login_required
def reports():

    customer_count = Customer.query.count()

    prospect_count = Prospect.query.count()

    loan_count = Loan.query.count()

    approved_count = Loan.query.filter_by(
        status="Approved"
    ).count()

    completed_count = Loan.query.filter_by(
        status="Completed"
    ).count()

    pending_count = Loan.query.filter_by(
        status="Pending"
    ).count()

    collections = (
        db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)
        )
        .filter(Payment.status == "Posted")
        .scalar()
    )

    outstanding = (
        db.session.query(
            func.coalesce(
                func.sum(Loan.total_due - Loan.amount_paid),
                0
            )
        )
        .filter(
            Loan.status.in_(["Approved", "Completed"])
        )
        .scalar()
    )

    body = """
    <div class="panel">

        <h1>Business Reports</h1>

        <div class="grid">

            <div class="stat">
                Customers
                <b>{{customer_count}}</b>
            </div>

            <div class="stat">
                Prospects
                <b>{{prospect_count}}</b>
            </div>

            <div class="stat">
                Total Loans
                <b>{{loan_count}}</b>
            </div>

            <div class="stat">
                Approved Loans
                <b>{{approved_count}}</b>
            </div>

            <div class="stat">
                Completed Loans
                <b>{{completed_count}}</b>
            </div>

            <div class="stat">
                Pending Loans
                <b>{{pending_count}}</b>
            </div>

            <div class="stat">
                Total Collections
                <b>KSh {{collections}}</b>
            </div>

            <div class="stat">
                Outstanding
                <b>KSh {{outstanding}}</b>
            </div>

        </div>

        <h2>Loan Portfolio</h2>

        <a clas