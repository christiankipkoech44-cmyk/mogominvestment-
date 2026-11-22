

import os
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "change-this-before-production"
)

@app.route("/")
def home():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MOGOM INVESTMENT</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f3f5f7;
                margin: 0;
                padding: 30px;
                text-align: center;
            }
            .container {
                background: white;
                max-width: 700px;
                margin: 50px auto;
                padding: 35px;
                border-radius: 12px;
                box-shadow: 0 3px 12px #ddd;
            }
            h1 { color: #174b35; }
            p { color: #555; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>MOGOM INVESTMENT</h1>
            <h3>Your Financial  Partner</h3>
            <p>Loan Management System</p>
            <p>Welcome to MOGOM INVESTMENT.</p>
            <p>Our digital platform is being prepared.</p>
        </div>
    </body>
    </html>
    """)

@app.route("/health")
def health():
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
  
