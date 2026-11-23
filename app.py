

@app.route("/")
def home():
    return page("""
    <div style="text-align:center; padding:45px 18px; background:#102e27; color:white; border-radius:10px;">

        <div style="font-size:clamp(23px,6vw,40px); font-weight:bold; letter-spacing:2px; color:#d9b65c; white-space:nowrap;">
            MOGOM INVESTMENT
        </div>

        <div style="font-style:italic; color:#e3c77e; margin:12px 0 35px;">
            Your Financial Partner
        </div>

        <h1 style="color:#e3c77e;">Welcome to MOGOM INVESTMENT</h1>

        <p>Responsible lending. Reliable service. Clear records.</p>

        <h3 style="color:#d9b65c; margin-top:35px;">Our Financial Services</h3>

        <div style="display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:25px 0;">
            <div style="padding:22px 5px; border:1px solid #c9a44c; border-radius:8px; color:#e3c77e; background:#174b39;">
                Business Loans
            </div>
            <div style="padding:22px 5px; border:1px solid #c9a44c; border-radius:8px; color:#e3c77e; background:#174b39;">
                Financial Support
            </div>
        </div>

        <a href="{{url_for('login')}}" style="display:inline-block; background:#c9a44c; color:#102e27; padding:13px 30px; border-radius:5px; text-decoration:none; font-weight:bold;">
            Staff Login
        </a>
    </div>
    """)
