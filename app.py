import os
import uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from functools import wraps

import requests
from flask import (
    Flask, request, redirect, url_for, session, flash,
    render_template_string, abort, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ------------------------------------------------------------
# MOGOM INVESTMENT - single-file Flask loan management system
# ------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")

db_url = os.environ.get("DATABASE_URL", "sqlite:///mogom.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

# ----------------------------- Models -----------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="employee", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    national_id = db.Column(db.String(50), index=True)
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    sms_consent = db.Column(db.Boolean, default=True, nullable=False)
    welcome_sms_sent = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    loans = db.relationship("Loan", backref="customer", lazy=True)


class Prospect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    interest = db.Column(db.String(100))
    notes = db.Column(db.Text)
    status = db.Column(db.String(40), default="New", nullable=False)
    follow_up_date = db.Column(db.Date)
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"))
    sms_consent = db.Column(db.Boolean, default=True, nullable=False)
    welcome_sms_sent = db.Column(db.Boolean, default=False, nullable=False)
    converted_customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    loan_type = db.Column(db.String(80), nullable=False)
    principal = db.Column(db.Numeric(14, 2), nullable=False)
    interest_rate = db.Column(db.Numeric(7, 2), default=0)
    term_months = db.Column(db.Integer, default=1)
    purpose = db.Column(db.Text)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    payments = db.relationship("Payment", backref="loan", lazy=True)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loan.id"), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    method = db.Column(db.String(50), default="Cash")
    reference = db.Column(db.String(100))
    received_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(30), default="Completed", nullable=False)
    void_reason = db.Column(db.Text)
    voided_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    voided_at = db.Column(db.DateTime)


class Communication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    prospect_id = db.Column(db.Integer, db.ForeignKey("prospect.id"))
    channel = db.Column(db.String(30), nullable=False)
    message = db.Column(db.Text, nullable=False)
    outcome = db.Column(db.String(160))
    next_follow_up = db.Column(db.Date)
    employee_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SMSLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(30), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Pending")
    provider_response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80))
    action = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ----------------------------- Helpers -----------------------------

def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = db.session.get(User, user_id)
    if not user or not user.active:
        session.clear()
        return None

    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user.role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def log_action(action):
    user = current_user()
    db.session.add(
        AuditLog(
            username=user.username if user else "system",
            action=action
        )
    )


def normalize_phone(value):
    value = (value or "").strip().replace(" ", "").replace("-", "")

    if value.startswith("+"):
        digits = value[1:]
    elif value.startswith("0"):
        digits = "254" + value[1:]
    elif value.startswith("254"):
        digits = value
    else:
        raise ValueError(
            "Enter a valid Kenyan phone number, for example 07XXXXXXXX."
        )

    if not digits.isdigit() or len(digits) != 12 or not digits.startswith("254"):
        raise ValueError(
            "Enter a valid Kenyan phone number, for example 07XXXXXXXX."
        )

    return "+" + digits