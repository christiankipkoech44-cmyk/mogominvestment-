

import os
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

@app.route("/")
def home():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>MOGOM INVESTMENT</title>
        <style>
            * { box-sizing: border-box; }
            body {
                margin: 0;
                font-family: Arial, sans-serif;
                background: #f5f5f0;
                color: #173c32;
            }
            header {
                background: #102e27;
                padding: 25px 15px;
                text-align: center;
                border-bottom: 3px solid #c8a44d;
            }
            .logo {
                color: #d9b65c;
                font-size: 34px;
                font-weight: bold;
                letter-spacing: 3px;
                margin: 0;
            }
            .investment {
                color: #fff;
                letter-spacing: 6px;
                margin: 5px 0;
            }
            .tagline {
                color: #e3c77e;
                font-style: italic;
                font-size: 15px;
                margin-top: 12px;
            }
            .hero {
                text-align: center;
                padding: 65px 20px;
                background: linear-gradient(135deg,#174b39,#102e27);
                color: white;
            }
            .hero h1 {
                font-size: 32px;
                margin-bottom: 15px;
            }
            .hero p {
                line-height: 1.7;
                color: #eee;
            }
            .btn {
                display: inline-block;
                margin-top: 20px;
                padding: 14px 25px;
                background: #d5b35c;
                color: #102e27;
                text-decoration: none;
                font-weight: bold;
                border-radius: 5px;
            }
            .services {
                padding: 35px 18px;
                text-align: center;
            }
            .cards {
                display: grid;
                grid-template-columns: repeat(auto-fit,minmax(140px,1fr));
                gap: 15px;
                max-width: 850px;
                margin: 25px auto;
            }
            .card {
                background: white;
                padding: 24px 12px;
                border-radius: 9px;
                border-bottom: 3px solid #c8a44d;
                box-shadow: 0 2px 8px #ddd;
            }
            footer {
                background: #102e27;
                color: white;
                text-align: center;
                padding: 20px;
            }
        </style>
    </head>
    <body>
        <header>
            <h1 class="logo">MOGOM</h1>
            <h3 class="investment">INVESTMENT</h3>
            <p class="tagline">Your Financial Partner</p>
        </header>

        <section class="hero">
            <h1>Welcome to MOGOM INVESTMENT</h1>
            <p>Your trusted partner in financial growth.<br>
            Simple, reliable and accessible financial solutions.</p>
            <a class="btn" href="#services">Explore Our Services</a>
        </section>

        <section class="services" id="services">
            <h2>Our Financial Services</h2>
            <div class="cards">
                <div class="card">💼<h3>Business Loans</h3></div>
                <div class="card">👤<h3>Personal Loans</h3></div>
                <div class="card">📚<h3>Education Loans</h3></div>
                <div class="card">📊<h3>Financial Support</h3></div>
            </div>
        </section>

        <footer>
            <p>MOGOM INVESTMENT</p>
            <p>Your Financial Partner</p>
            <small>© 2026 MOGOM INVESTMENT. All rights reserved.</small>
        </footer>
    </body>
    </html>
    """)

@app.route("/health")
def health():
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))

  
