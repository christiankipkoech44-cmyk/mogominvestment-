

import os
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from functools import wraps

import requests
from flask import (
    Flask, request, redirect, url_for, session, flash,
    render_template_string, abort
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

# ------------------------------------------------------------
# MOGOM INVESTMENT - Flask loan management system
# ------------------------------------------------------------

app = Flask(__name__)

@app.route("/health")
def health():
    return {"status": "healthy"}, 200
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "CHANGE-ME-BEFORE-PRODUCTION"
)

database_url = os.environ.get("DATABASE_URL", "sqlite:///mogom.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
logging.basicConfig(level=logging.INFO)

LOAN_TYPES = ("Business Loans", "Financial Support")


# ----------------------------- MODELS -----------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default="employee", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    national_id = db.Column(db.String(80), unique=True, nullable=False)
    address = db.Column(db.String(255))
    occupation = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    loans = db.relationship("Loan", backref="customer", lazy=True)
    communications = db.relationship(
        "Communication",
        backref="customer",
        lazy=True,
        order_by="Communication.created_at.desc()"
    )


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customer.id"), nullable=False
    )
    loan_type = db.Column(db.String(80), default="Business Loans")
    principal = db.Column(db.Numeric(12, 2), nullable=False)
    rate_percent = db.Column(db.Numeric(7, 2), default=0)
    term_months = db.Column(db.Integer, default=1)
    total_due = db.Column(db.Numeric(12, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(30), default="Pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.String(80))


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(
        db.Integer, db.ForeignKey("loan.id"), nullable=False
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reference = db.Column(db.String(120))
    received_by = db.Column(db.String(80))
    paid_at = db.Column(db.DateTime, default=datetime.utcnow)

    loan = db.relationship("Loan", backref="payments")


class Communication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customer.id"), nullable=False
    )
    channel = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=False)
    outcome = db.Column(db.String(255))
    next_followup = db.Column(db.Date)
    employee = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80))
    action = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Prospect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    interest = db.Column(db.String(120))
    notes = db.Column(db.Text)
    status = db.Column(db.String(30), default="New")
    next_followup = db.Column(db.Date)
    sms_consent = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    converted_customer_id = db.Column(
        db.Integer, db.ForeignKey("customer.id")
    )
    converted_customer = db.relationship("Customer")


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)


class SMSLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(40), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40))
    status = db.Column(db.String(30), default="Pending")
    provider_response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_by = db.Column(db.String(80))


# ----------------------------- HELPERS -----------------------------

def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def log_action(action):
    user = current_user()
    db.session.add(AuditLog(
        username=user.username if user else "system",
        action=action
    ))


def setting_value(key, default=""):
    item = Setting.query.filter_by(key=key).first()
    return item.value if item and item.value is not None else default


def set_setting(key, value):
    item = Setting.query.filter_by(key=key).first()
    if not item:
        item = Setting(key=key, value=str(value))
        db.session.add(item)
    else:
        item.value = str(value)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user() or not current_user().active:
            session.clear()
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user().role.lower() != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def send_sms(phone, message, category="General"):
    """Send through Africa's Talking when configured; otherwise log."""
    sms = SMSLog(
        recipient=phone,
        message=message,
        category=category,
        status="Pending",
        sent_by=current_user().username if current_user() else "system"
    )
    db.session.add(sms)
    db.session.flush()

    username = os.environ.get("AT_USERNAME")
    api_key = os.environ.get("AT_API_KEY")

    if not username or not api_key:
        sms.status = "Not configured"
        sms.provider_response = (
            "Africa's Talking credentials are not configured."
        )
        return sms

    try:
        response = requests.post(
            "https://api.africastalking.com/version1/messaging",
            data={
                "username": username,
                "to": phone,
                "message": message
            },
            headers={
                "apiKey": api_key,
                "Accept": "application/json"
            },
            timeout=20
        )

        sms.provider_response = response.text[:4000]

        if response.ok and '"status":"Success"' in response.text:
            sms.status = "Sent"
        else:
            sms.status = "Failed"

    except requests.RequestException as exc:
        sms.status = "Failed"
        sms.provider_response = str(exc)[:1000]

    return sms


def care_number():
    return setting_value("customer_care_number", "0721780503")


def acknowledgment_message(kind, name):
    number = care_number()

    if kind == "prospect":
        return (
            f"Hello {name}, your details have been registered "
            "with MOGOM INVESTMENT. "
            f"Thank you for your interest. For assistance call {number}. "
            "Your Financial Partner."
        )

    if kind == "application":
        return (
            f"Hello {name}, we have received your loan application details. "
            f"Our team will contact you. For assistance call {number}. "
            "MOGOM INVESTMENT - Your Financial Partner."
        )

    return (
        f"Hello {name}, thank you for your continued partnership with "
        f"MOGOM INVESTMENT. For assistance call {number}. "
        "Your Financial Partner."
    )


# ----------------------------- WEBSITE DESIGN -----------------------------

BASE = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MOGOM INVESTMENT</title>

<style>
body {
    font-family: Arial, sans-serif;
    background: #f4f6f4;
    margin: 0;
    color: #243329;
}

header {
    background: #123c2b;
    color: #e7c76b;
    padding: 18px;
}

header b {
    font-size: 22px;
}

header small {
    display: block;
    color: #fff;
}

nav {
    background: #e9eee9;
    padding: 12px;
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
}

a {
    color: #17613e;
    text-decoration: none;
}

main {
    padding: 18px;
    max-width: 1100px;
    margin: auto;
}

.card {
    background: white;
    padding: 16px;
    margin: 12px 0;
    border-radius: 8px;
    box-shadow: 0 1px 5px #ccd4cc;
}

input, select, textarea {
    box-sizing: border-box;
    width: 100%;
    padding: 10px;
    margin: 5px 0 12px;
    border: 1px solid #b9c5bb;
    border-radius: 5px;
}

button {
    background: #174b34;
    color: white;
    border: 0;
    padding: 10px 16px;
    border-radius: 5px;
}

table {
    width: 100%;
    border-collapse: collapse;
    background: white;
}

td, th {
    padding: 9px;
    border-bottom: 1px solid #ddd;
    text-align: left;
}

.muted {
    color: #65736a;
    font-size: 13px;
}

.flash {
    background: #fff2cc;
    padding: 10px;
    margin: 8px 0;
}

.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
}
</style>
</head>

<body>

<header>
    <b>MOGOM INVESTMENT</b>
    <small>Your Financial Partner</small>
</header>

{% if user %}
<nav>
    <a href="{{url_for('dashboard')}}">Dashboard</a>
    <a href="{{url_for('customers')}}">Customers</a>
    <a href="{{url_for('new_customer')}}">Add customer</a>
    <a href="{{url_for('prospects')}}">Prospects</a>
    <a href="{{url_for('new_prospect')}}">Add prospect</a>
    <a href="{{url_for('loans')}}">Loans</a>
    <a href="{{url_for('new_loan')}}">New loan</a>
    <a href="{{url_for('reports')}}">Reports</a>

    {% if user.role == 'admin' %}
        <a href="{{url_for('employees')}}">Employees</a>
        <a href="{{url_for('settings')}}">Settings</a>
        <a href="{{url_for('sms_logs')}}">SMS logs</a>
        <a href="{{url_for('audit')}}">Audit log</a>
    {% endif %}

    <a href="{{url_for('logout')}}">Logout</a>
</nav>
{% endif %}

<main>
    {% with messages=get_flashed_messages() %}
        {% for m in messages %}
            <div class="flash">{{m}}</div>
        {% endfor %}
    {% endwith %}

    {{content|safe}}
</main>

</body>
</html>
"""


def page(body, **context):
    return render_template_string(
        BASE,
        content=render_template_string(body, **context),
        user=current_user()
    )


# ----------------------------- AUTHENTICATION -----------------------------

@app.route("/")
def home():
    return redirect(
        url_for("dashboard") if current_user()
        else url_for("login")
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(
            username=request.form.get("username", "").strip()
        ).first()

        if (
            user
            and user.active
            and check_password_hash(
                user.password_hash,
                request.form.get("password", "")
            )
        ):
            session.clear()
            session["user_id"] = user.id
            log_action("Logged in")
            db.session.commit()
            return redirect(url_for("dashboard"))

        flash("Login failed. Check your details or account status.")

    return page("""
    <div class="card">
        <h2>Staff login</h2>
        <form method="post">
            Username
            <input name="username" required>

            Password
            <input name="password" type="password" required>

            <button>Sign in</button>
        </form>
    </div>
    """)


@app.route("/logout")
@login_required
def logout():
    log_action("Logged out")
    db.session.commit()
    session.clear()
    return redirect(url_for("login"))


# ----------------------------- DASHBOARD -----------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    customers = Customer.query.count()
    loans = Loan.query.count()

    active = Loan.query.filter_by(status="Active").count()

    paid = (
        db.session.query(db.func.sum(Payment.amount)).scalar() or 0
    )

    outstanding = sum(
        money(x.total_due) - money(x.amount_paid)
        for x in Loan.query.filter(Loan.status != "Voided").all()
    )

    return page("""
    <h2>Dashboard</h2>

    <div class="grid">

        <div class="card">
            Customers
            <h2>{{customers}}</h2>
        </div>

        <div class="card">
            All loans
            <h2>{{loans}}</h2>
        </div>

        <div class="card">
            Active loans
            <h2>{{active}}</h2>
        </div>

        <div class="card">
            Payments
            <h2>KES {{'%.2f'|format(paid)}}</h2>
        </div>

        <div class="card">
            Outstanding
            <h2>KES {{'%.2f'|format(outstanding)}}</h2>
        </div>

    </div>
    """,
    customers=customers,
    loans=loans,
    active=active,
    paid=float(paid),
    outstanding=float(outstanding)
    )

# ----------------------------- CUSTOMERS -----------------------------

@app.route("/customers")
@login_required
def customers():
    rows = Customer.query.order_by(
        Customer.created_at.desc()
    ).all()

    return page("""
    <h2>Customers</h2>

    <div class="card">
        <a href="{{url_for('new_customer')}}">+ Add customer</a>
    </div>

    <div class="card">
        <table>
            <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>National ID</th>
                <th></th>
            </tr>

            {% for c in rows %}
            <tr>
                <td>{{c.full_name}}</td>
                <td>{{c.phone}}</td>
                <td>{{c.national_id}}</td>
                <td>
                    <a href="{{url_for('customer_detail', cid=c.id)}}">
                        Open
                    </a>
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    """, rows=rows)


@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def new_customer():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        national_id = request.form.get("national_id", "").strip()

        if not name or not phone or not national_id:
            flash("Name, phone and national ID are required.")

        elif Customer.query.filter_by(
            national_id=national_id
        ).first():
            flash("A customer with that national ID already exists.")

        else:
            c = Customer(
                full_name=name,
                phone=phone,
                national_id=national_id,
                address=request.form.get("address", "").strip(),
                occupation=request.form.get("occupation", "").strip()
            )

            db.session.add(c)
            db.session.flush()

            send_sms(
                phone,
                acknowledgment_message("customer", name),
                "Customer acknowledgement"
            )

            log_action(
                f"Registered customer #{c.id}: {name}"
            )

            db.session.commit()

            flash(
                "Customer registered. SMS status is available in SMS logs."
            )

            return redirect(
                url_for("customer_detail", cid=c.id)
            )

    return page("""
    <div class="card">
        <h2>Add customer</h2>

        <form method="post">

            Full name
            <input name="full_name" required>

            Phone number
            <input name="phone" required>

            National ID
            <input name="national_id" required>

            Address
            <input name="address">

            Occupation
            <input name="occupation">

            <button>Save customer</button>

        </form>
    </div>
    """)


@app.route("/customers/<int:cid>")
@login_required
def customer_detail(cid):
    c = db.get_or_404(Customer, cid)

    return page("""
    <h2>{{c.full_name}}</h2>

    <div class="card">
        Phone: {{c.phone}}<br>
        National ID: {{c.national_id}}<br>
        Address: {{c.address or '-'}}
    </div>

    <div class="card">
        <h3>Loans</h3>

        {% for l in c.loans %}
            <p>
                <a href="{{url_for('loan_detail', lid=l.id)}}">
                    Loan #{{l.id}}
                </a>
                - {{l.status}}
                - KES {{l.total_due}}
            </p>
        {% else %}
            <p>No loans yet.</p>
        {% endfor %}
    </div>

    <div class="card">
        <h3>Record customer communication</h3>

        <form method="post"
              action="{{url_for('add_communication', cid=c.id)}}">

            <select name="channel">
                {% for x in ['Call','SMS','WhatsApp','Email','In-person'] %}
                    <option>{{x}}</option>
                {% endfor %}
            </select>

            Notes
            <textarea name="notes" required></textarea>

            Outcome
            <input name="outcome">

            Next follow-up
            <input type="date" name="next_followup">

            <button>Save interaction</button>
        </form>
    </div>

    <div class="card">
        <h3>Communication history</h3>

        {% for x in c.communications %}
            <p>
                <b>{{x.channel}}</b> —
                {{x.created_at.strftime('%d %b %Y %H:%M')}}<br>

                {{x.notes}}<br>

                Outcome: {{x.outcome or '-'}}
                |
                Follow-up: {{x.next_followup or '-'}}
                |
                By: {{x.employee or '-'}}
            </p>
            <hr>
        {% else %}
            <p>No interactions recorded.</p>
        {% endfor %}
    </div>
    """, c=c)


@app.route(
    "/customers/<int:cid>/communication",
    methods=["POST"]
)
@login_required
def add_communication(cid):
    c = db.get_or_404(Customer, cid)

    follow = request.form.get("next_followup") or None

    item = Communication(
        customer_id=c.id,
        channel=request.form.get("channel", "Call"),
        notes=request.form.get("notes", "").strip(),
        outcome=request.form.get("outcome", "").strip(),
        next_followup=(
            date.fromisoformat(follow) if follow else None
        ),
        employee=current_user().username
    )

    db.session.add(item)

    log_action(
        f"Added {item.channel} communication for customer #{c.id}"
    )

    db.session.commit()

    flash("Communication saved.")

    return redirect(
        url_for("customer_detail", cid=c.id)
    )

# ----------------------------- PROSPECTS -----------------------------

@app.route("/prospects")
@login_required
def prospects():
    rows = Prospect.query.order_by(
        Prospect.created_at.desc()
    ).all()

    return page("""
    <h2>Prospects</h2>

    <div class="card">
        <a href="{{url_for('new_prospect')}}">+ Add prospect</a>
    </div>

    <div class="card">
        <table>
            <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Status</th>
                <th>Follow-up</th>
                <th></th>
            </tr>

            {% for p in rows %}
            <tr>
                <td>{{p.full_name}}</td>
                <td>{{p.phone}}</td>
                <td>{{p.status}}</td>
                <td>{{p.next_followup or '-'}}</td>
                <td>
                    <a href="{{url_for('prospect_detail', pid=p.id)}}">
                        Open
                    </a>
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    """, rows=rows)


@app.route("/prospects/new", methods=["GET", "POST"])
@login_required
def new_prospect():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()

        consent = request.form.get("sms_consent") == "yes"

        if not name or not phone:
            flash("Name and phone are required.")

        else:
            p = Prospect(
                full_name=name,
                phone=phone,
                interest=request.form.get("interest", "").strip(),
                notes=request.form.get("notes", "").strip(),
                sms_consent=consent
            )

            db.session.add(p)
            db.session.flush()

            if consent:
                send_sms(
                    phone,
                    acknowledgment_message("prospect", name),
                    "Prospect acknowledgement"
                )

            log_action(
                f"Registered prospect #{p.id}: {name}"
            )

            db.session.commit()

            flash("Prospect registered.")

            return redirect(
                url_for("prospect_detail", pid=p.id)
            )

    return page("""
    <div class="card">
        <h2>Register prospect</h2>

        <form method="post">

            Full name
            <input name="full_name" required>

            Phone
            <input name="phone" required>

            Interest
            <input name="interest">

            Notes
            <textarea name="notes"></textarea>

            <label>
                <input
                    style="width:auto"
                    type="checkbox"
                    name="sms_consent"
                    value="yes"
                >
                I have permission to send this registration
                acknowledgement by SMS.
            </label>

            <br>

            <button>Save prospect</button>

        </form>
    </div>
    """)


@app.route("/prospects/<int:pid>")
@login_required
def prospect_detail(pid):
    p = db.get_or_404(Prospect, pid)

    return page("""
    <h2>{{p.full_name}}</h2>

    <div class="card">
        Phone: {{p.phone}}<br>
        Interest: {{p.interest or '-'}}<br>
        Status: {{p.status}}<br>
        Notes: {{p.notes or '-'}}
    </div>

    <div class="card">
        <h3>Update prospect</h3>

        <form method="post"
              action="{{url_for('update_prospect', pid=p.id)}}">

            Status

            <select name="status">
                {% for s in [
                    'New',
                    'Contacted',
                    'Interested',
                    'Not Interested',
                    'Converted'
                ] %}
                    <option
                        {% if p.status == s %}selected{% endif %}
                    >
                        {{s}}
                    </option>
                {% endfor %}
            </select>

            Next follow-up
            <input
                type="date"
                name="next_followup"
                value="{{p.next_followup or ''}}"
            >

            Notes
            <textarea name="notes">{{p.notes or ''}}</textarea>

            <button>Update</button>
        </form>
    </div>

    {% if not p.converted_customer_id %}
    <div class="card">
        <h3>Convert to customer</h3>

        <form method="post"
              action="{{url_for('convert_prospect', pid=p.id)}}">

            National ID
            <input name="national_id" required>

            Address
            <input name="address">

            Occupation
            <input name="occupation">

            <button>Convert prospect</button>
        </form>
    </div>
    {% endif %}
    """, p=p)


@app.route("/prospects/<int:pid>/update", methods=["POST"])
@login_required
def update_prospect(pid):
    p = db.get_or_404(Prospect, pid)

    p.status = request.form.get("status", p.status)
    p.notes = request.form.get("notes", p.notes)

    follow = request.form.get("next_followup") or None

    p.next_followup = (
        date.fromisoformat(follow) if follow else None
    )

    log_action(f"Updated prospect #{p.id}")

    db.session.commit()

    flash("Prospect updated.")

    return redirect(
        url_for("prospect_detail", pid=p.id)
    )


@app.route("/prospects/<int:pid>/convert", methods=["POST"])
@login_required
def convert_prospect(pid):
    p = db.get_or_404(Prospect, pid)

    if p.converted_customer_id:
        flash("This prospect has already been converted.")
        return redirect(
            url_for("prospect_detail", pid=p.id)
        )

    national_id = request.form.get("national_id", "").strip()

    if not national_id:
        flash("National ID is required.")
        return redirect(
            url_for("prospect_detail", pid=p.id)
        )

    if Customer.query.filter_by(
        national_id=national_id
    ).first():
        flash("That national ID is already registered.")
        return redirect(
            url_for("prospect_detail", pid=p.id)
        )

    c = Customer(
        full_name=p.full_name,
        phone=p.phone,
        national_id=national_id,
        address=request.form.get("address", "").strip(),
        occupation=request.form.get("occupation", "").strip()
    )

    db.session.add(c)
    db.session.flush()

    p.converted_customer_id = c.id
    p.status = "Converted"

    log_action(
        f"Converted prospect #{p.id} to customer #{c.id}"
    )

    db.session.commit()

    flash("Prospect successfully converted to customer.")

    return redirect(
        url_for("customer_detail", cid=c.id)
    )

# ----------------------------- LOANS -----------------------------

@app.route("/loans")
@login_required
def loans():
    rows = Loan.query.order_by(Loan.created_at.desc()).all()

    return page("""
    <h2>Loans</h2>

    <div class="card">
        <a href="{{url_for('new_loan')}}">+ Create new loan</a>
    </div>

    <div class="card">
        <table>
            <tr>
                <th>Loan</th>
                <th>Customer</th>
                <th>Principal</th>
                <th>Total due</th>
                <th>Status</th>
                <th></th>
            </tr>

            {% for l in rows %}
            <tr>
                <td>#{{l.id}}</td>
                <td>{{l.customer.full_name}}</td>
                <td>KES {{l.principal}}</td>
                <td>KES {{l.total_due}}</td>
                <td>{{l.status}}</td>
                <td>
                    <a href="{{url_for('loan_detail', lid=l.id)}}">Open</a>
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    """, rows=rows)


@app.route("/loans/new", methods=["GET", "POST"])
@login_required
def new_loan():
    customers_list = Customer.query.order_by(
        Customer.full_name
    ).all()

    if request.method == "POST":
        try:
            customer_id = int(request.form.get("customer_id", ""))
            principal = money(request.form.get("principal", "0"))
            rate = money(request.form.get("rate_percent", "0"))
            term = int(request.form.get("term_months", "1"))

            customer = db.session.get(Customer, customer_id)

            if not customer:
                raise ValueError("Select a valid customer.")

            if principal <= 0 or rate < 0 or term < 1:
                raise ValueError("Enter valid loan amounts and term.")

            total_due = principal + (
                principal * rate * term / Decimal("100")
            )

            loan = Loan(
                customer_id=customer.id,
                loan_type=request.form.get(
                    "loan_type", "Business Loans"
                ),
                principal=principal,
                rate_percent=rate,
                term_months=term,
                total_due=money(total_due),
                amount_paid=Decimal("0.00"),
                status="Pending"
            )

            db.session.add(loan)
            db.session.flush()

            send_sms(
                customer.phone,
                acknowledgment_message(
                    "application", customer.full_name
                ),
                "Loan application acknowledgement"
            )

            log_action(
                f"Created loan application #{loan.id} "
                f"for customer #{customer.id}"
            )

            db.session.commit()

            flash("Loan application recorded.")

            return redirect(
                url_for("loan_detail", lid=loan.id)
            )

        except (ValueError, InvalidOperation, TypeError):
            db.session.rollback()
            flash("Please enter valid loan details.")

    return page("""
    <div class="card">
        <h2>New loan application</h2>

        {% if not customers_list %}
            <p>Register a customer before creating a loan.</p>
        {% else %}
        <form method="post">

            Customer
            <select name="customer_id" required>
                {% for c in customers_list %}
                    <option value="{{c.id}}">
                        {{c.full_name}} — {{c.phone}}
                    </option>
                {% endfor %}
            </select>

            Loan type
            <select name="loan_type">
                {% for t in loan_types %}
                    <option>{{t}}</option>
                {% endfor %}
            </select>

            Principal amount (KES)
            <input name="principal" type="number"
                   min="1" step="0.01" required>

            Interest rate (% per month)
            <input name="rate_percent" type="number"
                   min="0" step="0.01" value="0" required>

            Term (months)
            <input name="term_months" type="number"
                   min="1" value="1" required>

            <button>Submit application</button>
        </form>
        {% endif %}
    </div>
    """, customers_list=customers_list, loan_types=LOAN_TYPES)


@app.route("/loans/<int:lid>")
@login_required
def loan_detail(lid):
    loan = db.get_or_404(Loan, lid)

    return page("""
    <h2>Loan #{{loan.id}}</h2>

    <div class="card">
        Customer:
        <a href="{{url_for('customer_detail', cid=loan.customer.id)}}">
            {{loan.customer.full_name}}
        </a>
        <br>
        Loan type: {{loan.loan_type}}<br>
        Principal: KES {{loan.principal}}<br>
        Interest rate: {{loan.rate_percent}}%<br>
        Term: {{loan.term_months}} months<br>
        Total due: KES {{loan.total_due}}<br>
        Amount paid: KES {{loan.amount_paid}}<br>
        Balance: KES {{balance}}<br>
        Status: {{loan.status}}<br>
        Approved by: {{loan.approved_by or '-'}}
    </div>

    {% if loan.status == 'Pending' %}
    <div class="card">
        <h3>Approve loan</h3>
        <form method="post"
              action="{{url_for('approve_loan', lid=loan.id)}}">
            <button>Approve loan</button>
        </form>
    </div>
    {% endif %}

    {% if loan.status == 'Active' %}
    <div class="card">
        <h3>Record payment</h3>
        <form method="post"
              action="{{url_for('add_payment', lid=loan.id)}}">

            Amount received (KES)
            <input name="amount" type="number"
                   min="0.01" step="0.01" required>

            Payment reference
            <input name="reference">

            <button>Save payment</button>
        </form>
    </div>
    {% endif %}

    <div class="card">
        <h3>Payment history</h3>

        <table>
            <tr>
                <th>Date</th>
                <th>Amount</th>
                <th>Reference</th>
                <th>Received by</th>
            </tr>

            {% for p in loan.payments %}
            <tr>
                <td>{{p.paid_at.strftime('%d %b %Y %H:%M')}}</td>
                <td>KES {{p.amount}}</td>
                <td>{{p.reference or '-'}}</td>
                <td>{{p.received_by or '-'}}</td>
            </tr>
            {% else %}
            <tr><td colspan="4">No payments recorded.</td></tr>
            {% endfor %}
        </table>
    </div>
    """, loan=loan,
    balance=money(loan.total_due) - money(loan.amount_paid))


@app.route("/loans/<int:lid>/approve", methods=["POST"])
@login_required
def approve_loan(lid):
    loan = db.get_or_404(Loan, lid)

    if loan.status != "Pending":
        flash("Only pending loans can be approved.")
    else:
        loan.status = "Active"
        loan.approved_by = current_user().username

        log_action(f"Approved loan #{loan.id}")
        db.session.commit()

        flash("Loan approved.")

    return redirect(url_for("loan_detail", lid=lid))


@app.route("/loans/<int:lid>/payment", methods=["POST"])
@login_required
def add_payment(lid):
    loan = db.get_or_404(Loan, lid)

    if loan.status != "Active":
        flash("Payments can only be recorded for active loans.")
        return redirect(url_for("loan_detail", lid=lid))

    try:
        amount = money(request.form.get("amount", "0"))

        balance = money(loan.total_due) - money(loan.amount_paid)

        if amount <= 0 or amount > balance:
            raise ValueError("Invalid payment amount.")

        payment = Payment(
            loan_id=loan.id,
            amount=amount,
            reference=request.form.get("reference", "").strip(),
            received_by=current_user().username
        )

        db.session.add(payment)
        loan.amount_paid = money(loan.amount_paid) + amount

        if loan.amount_paid >= loan.total_due:
            loan.status = "Completed"

        log_action(
            f"Recorded payment of KES {amount} "
            f"for loan #{loan.id}"
        )

        db.session.commit()
        flash("Payment recorded successfully.")

    except (ValueError, InvalidOperation, TypeError):
        db.session.rollback()
        flash("Invalid payment. Please check the amount.")

    return redirect(url_for("loan_detail", lid=lid))


# ----------------------------- REPORTS -----------------------------

@app.route("/reports")
@login_required
def reports():
    total_customers = Customer.query.count()
    total_loans = Loan.query.count()

    total_disbursed = (
        db.session.query(db.func.sum(Loan.principal))
        .filter(Loan.status.in_(["Active", "Completed"]))
        .scalar() or 0
    )

    total_collected = (
        db.session.query(db.func.sum(Payment.amount)).scalar() or 0
    )

    outstanding = sum(
        money(l.total_due) - money(l.amount_paid)
        for l in Loan.query.filter(
            Loan.status.in_(["Active", "Pending"])
        ).all()
    )

    return page("""
    <h2>Business Reports</h2>

    <div class="grid">
        <div class="card">
            Total customers
            <h2>{{customers}}</h2>
        </div>

        <div class="card">
            Total loan applications
            <h2>{{loans}}</h2>
        </div>

        <div class="card">
            Principal disbursed
            <h2>KES {{'%.2f'|format(disbursed)}}</h2>
        </div>

        <div class="card">
            Total collected
            <h2>KES {{'%.2f'|format(collected)}}</h2>
        </div>

        <div class="card">
            Outstanding
            <h2>KES {{'%.2f'|format(outstanding)}}</h2>
        </div>
    </div>
    """,
    customers=total_customers,
    loans=total_loans,
    disbursed=float(total_disbursed),
    collected=float(total_collected),
    outstanding=float(outstanding))


# ----------------------------- EMPLOYEES -----------------------------

@app.route("/employees", methods=["GET", "POST"])
@admin_required
def employees():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "employee")

        if not username or len(password) < 8:
            flash("Enter a username and a password of at least 8 characters.")

        elif role not in ("admin", "employee"):
            flash("Invalid employee role.")

        elif User.query.filter_by(username=username).first():
            flash("That username already exists.")

        else:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                role=role,
                active=True
            )

            db.session.add(user)
            log_action(f"Created employee account: {username}")
            db.session.commit()

            flash("Employee account created.")
            return redirect(url_for("employees"))

    rows = User.query.order_by(User.username).all()

    return page("""
    <h2>Employee management</h2>

    <div class="card">
        <h3>Create employee account</h3>

        <form method="post">
            Username
            <input name="username" required>

            Password (at least 8 characters)
            <input name="password" type="password"
                   minlength="8" required>

            Role
            <select name="role">
                <option value="employee">Employee</option>
                <option value="admin">Administrator</option>
            </select>

            <button>Create account</button>
        </form>
    </div>

    <div class="card">
        <h3>Existing accounts</h3>

        <table>
            <tr>
                <th>Username</th>
                <th>Role</th>
                <th>Status</th>
                <th>Action</th>
            </tr>

            {% for u in rows %}
            <tr>
                <td>{{u.username}}</td>
                <td>{{u.role}}</td>
                <td>{{'Active' if u.active else 'Disabled'}}</td>
                <td>
                    {% if u.id != current_id %}
                    <form method="post"
                          action="{{url_for('toggle_employee', uid=u.id)}}">
                        <button>
                            {{'Disable' if u.active else 'Enable'}}
                        </button>
                    </form>
                    {% else %}
                    Current account
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    """, rows=rows, current_id=current_user().id)


@app.route("/employees/<int:uid>/toggle", methods=["POST"])
@admin_required
def toggle_employee(uid):
    user = db.get_or_404(User, uid)

    if user.id == current_user().id:
        flash("You cannot disable your own account.")
    else:
        user.active = not user.active
        log_action(
            f"{'Enabled' if user.active else 'Disabled'} "
            f"employee account {user.username}"
        )
        db.session.commit()
        flash("Employee account updated.")

    return redirect(url_for("employees"))


# ----------------------------- SETTINGS -----------------------------

@app.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        number = request.form.get("customer_care_number", "").strip()

        if not number:
            flash("Customer care number cannot be empty.")
        else:
            set_setting("customer_care_number", number)
            log_action("Updated customer care number")
            db.session.commit()
            flash("Settings saved.")

    number = care_number()

    return page("""
    <div class="card">
        <h2>Business settings</h2>

        <form method="post">
            Customer care phone number
            <input name="customer_care_number"
                   value="{{number}}" required>

            <button>Save settings</button>
        </form>
    </div>
    """, number=number)


# ----------------------------- SMS LOGS -----------------------------

@app.route("/sms-logs")
@admin_required
def sms_logs():
    rows = SMSLog.query.order_by(
        SMSLog.created_at.desc()
    ).limit(300).all()

    return page("""
    <h2>SMS communication logs</h2>

    <div class="card">
        <table>
            <tr>
                <th>Date</th>
                <th>Recipient</th>
                <th>Category</th>
                <th>Status</th>
                <th>Message</th>
                <th>Action</th>
            </tr>

            {% for s in rows %}
            <tr>
                <td>{{s.created_at.strftime('%d %b %Y %H:%M')}}</td>
                <td>{{s.recipient}}</td>
                <td>{{s.category or '-'}}</td>
                <td>{{s.status}}</td>
                <td>{{s.message}}</td>
                <td>
                    {% if s.status in ['Failed', 'Not configured'] %}
                    <form method="post"
                          action="{{url_for('retry_sms', sid=s.id)}}">
                        <button>Retry</button>
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    """, rows=rows)


@app.route("/sms-logs/<int:sid>/retry", methods=["POST"])
@admin_required
def retry_sms(sid):
    old_sms = db.get_or_404(SMSLog, sid)

    if old_sms.status not in ("Failed", "Not configured"):
        flash("Only failed or unconfigured messages can be retried.")
    else:
        send_sms(
            old_sms.recipient,
            old_sms.message,
            old_sms.category or "Retry"
        )

        log_action(f"Retried SMS log #{old_sms.id}")
        db.session.commit()
        flash("SMS retry recorded. Check the new SMS log entry.")

    return redirect(url_for("sms_logs"))


# ----------------------------- AUDIT LOG -----------------------------

@app.route("/audit")
@admin_required
def audit():
    rows = AuditLog.query.order_by(
        AuditLog.created_at.desc()
    ).limit(500).all()

    return page("""
    <h2>Audit log</h2>

    <div class="card">
        <table>
            <tr>
                <th>Date</th>
                <th>User</th>
                <th>Action</th>
            </tr>

            {% for a in rows %}
            <tr>
                <td>{{a.created_at.strftime('%d %b %Y %H:%M')}}</td>
                <td>{{a.username or '-'}}</td>
                <td>{{a.action}}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    """, rows=rows)


# ----------------------------- DATABASE STARTUP -----------------------------

with app.app_context():
    db.create_all()


# ----------------------------- RUN APPLICATION -----------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )

