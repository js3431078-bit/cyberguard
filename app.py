from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from langdetect import detect
import os, logging, re
from werkzeug.utils import secure_filename

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = "cybercrime_secret_2024"

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ADMIN_ID       = "admin"
ADMIN_PASSWORD = "admin123"

# ── DB — PostgreSQL (Supabase) with SQLite fallback ──────────────────────────
_raw_db_url = os.environ.get("DATABASE_URL", "")
# Railway sometimes injects postgres:// — psycopg2 needs postgresql://
DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql://", 1) if _raw_db_url else ""

def get_db():
    if DATABASE_URL:
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(DATABASE_URL, sslmode="require")
            conn.autocommit = False
            # Add execute() method to psycopg2 connection for compatibility
            def _pg_execute(sql, params=None):
                cur = conn.cursor()
                # Convert ? to %s for PostgreSQL
                sql = sql.replace("?", "%s")
                cur.execute(sql, params or ())
                cur.conn = conn
                return cur
            conn.execute = _pg_execute
            return conn
        except Exception as pg_err:
            logging.error(f"PostgreSQL failed, using SQLite: {pg_err}")
    import sqlite3
    conn = sqlite3.connect("cybercrime.db")
    conn.row_factory = sqlite3.Row
    return conn

def db_fetchall(cursor):
    """Convert rows to list of dicts — works for both psycopg2 and sqlite3."""
    try:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception:
        return []

def db_fetchone(cursor):
    """Convert row to dict — works for both psycopg2 and sqlite3."""
    try:
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    except Exception:
        return None

def _is_pg(conn):
    """Check if this connection is PostgreSQL."""
    try:
        import psycopg2
        return isinstance(conn, psycopg2.extensions.connection)
    except Exception:
        return False

def ph(n=1):
    """Return correct placeholder based on actual DB connection."""
    return "%s" if DATABASE_URL else "?"

def ph_for(conn):
    """Return correct placeholder for a specific connection object."""
    return "%s" if _is_pg(conn) else "?"

def phs(n):
    p = "%s" if DATABASE_URL else "?"
    return ",".join([p]*n)

def init_db():
    conn = get_db()
    cur  = conn.cursor()
    is_pg = _is_pg(conn)
    if is_pg:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id       SERIAL PRIMARY KEY,
            name     TEXT NOT NULL,
            email    TEXT UNIQUE NOT NULL,
            phone    TEXT,
            password TEXT NOT NULL,
            created  TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS otp_store(
            id        SERIAL PRIMARY KEY,
            token     TEXT UNIQUE NOT NULL,
            otp       TEXT NOT NULL,
            created   DOUBLE PRECISION NOT NULL,
            attempts  INTEGER DEFAULT 0,
            verified  INTEGER DEFAULT 0
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS complaints(
            id          SERIAL PRIMARY KEY,
            user_email  TEXT,
            name        TEXT,
            email       TEXT,
            phone       TEXT,
            address     TEXT,
            crime_type  TEXT,
            description TEXT,
            file        TEXT,
            date        TEXT,
            status      TEXT DEFAULT 'Pending',
            submitted   TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs(
            id         SERIAL PRIMARY KEY,
            user_email TEXT,
            action     TEXT NOT NULL,
            detail     TEXT,
            ip         TEXT,
            timestamp  TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_analysis_logs(
            id         SERIAL PRIMARY KEY,
            user_email TEXT,
            input_text TEXT,
            crime      TEXT,
            category   TEXT,
            threat     TEXT,
            confidence TEXT,
            language   TEXT,
            source     TEXT DEFAULT 'analyze',
            timestamp  TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback(
            id           SERIAL PRIMARY KEY,
            user_email   TEXT,
            complaint_id TEXT,
            rating       INTEGER NOT NULL,
            comment      TEXT,
            timestamp    TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
    else:
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            phone TEXT, password TEXT NOT NULL,
            created TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS otp_store(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL, otp TEXT NOT NULL,
            created REAL NOT NULL, attempts INTEGER DEFAULT 0, verified INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT, name TEXT, email TEXT, phone TEXT, address TEXT,
            crime_type TEXT, description TEXT, file TEXT, date TEXT,
            status TEXT DEFAULT 'Pending',
            submitted TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS activity_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT, action TEXT NOT NULL, detail TEXT, ip TEXT,
            timestamp TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ai_analysis_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT, input_text TEXT, crime TEXT, category TEXT,
            threat TEXT, confidence TEXT, language TEXT,
            source TEXT DEFAULT 'analyze',
            timestamp TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT, complaint_id TEXT,
            rating INTEGER NOT NULL, comment TEXT,
            timestamp TEXT DEFAULT (datetime('now','localtime'))
        );
        """)
    conn.commit()
    conn.close()

def log_activity(action, detail="", user_email=None):
    """Helper to insert a row into activity_logs."""
    try:
        email = user_email or session.get("email", "anonymous")
        ip    = request.remote_addr or "unknown"
        conn  = get_db()
        p     = ph_for(conn)
        cur   = conn.cursor()
        cur.execute(
            f"INSERT INTO activity_logs(user_email, action, detail, ip) VALUES({p},{p},{p},{p})",
            (email, action, detail, ip)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.warning(f"log_activity failed: {e}")

try:
    init_db()
    logging.info("Database initialized successfully.")
except Exception as _init_err:
    logging.error(f"init_db failed: {_init_err}")
    # Force create SQLite tables as emergency fallback
    try:
        import sqlite3 as _sq
        _ec = _sq.connect("cybercrime.db")
        _ec.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            phone TEXT, password TEXT NOT NULL,
            created TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS otp_store(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL, otp TEXT NOT NULL,
            created REAL NOT NULL, attempts INTEGER DEFAULT 0, verified INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT, name TEXT, email TEXT, phone TEXT, address TEXT,
            crime_type TEXT, description TEXT, file TEXT, date TEXT,
            status TEXT DEFAULT 'Pending',
            submitted TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS activity_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT, action TEXT NOT NULL, detail TEXT, ip TEXT,
            timestamp TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ai_analysis_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT, input_text TEXT, crime TEXT, category TEXT,
            threat TEXT, confidence TEXT, language TEXT,
            source TEXT DEFAULT 'analyze',
            timestamp TEXT DEFAULT (datetime('now','localtime'))
        );
        """)
        _ec.commit()
        _ec.close()
        logging.info("SQLite emergency tables created.")
    except Exception as _sq_err:
        logging.error(f"SQLite emergency init failed: {_sq_err}")

# ── AI ───────────────────────────────────────────────────────────────────────
CRIME_RULES = [
    {"keywords":["otp","bank","phish","credential","click link","verify account"],
     "crime":"Phishing","category":"Financial Cyber Crime","threat":"🔴 High","confidence":"92%",
     "action":"Block sender, report to bank & cybercrime.gov.in"},
    {"keywords":["upi","money","transfer","fraud","scam","payment","wallet","fake offer"],
     "crime":"Online Financial Fraud","category":"Financial Cyber Crime","threat":"🔴 High","confidence":"90%",
     "action":"Contact bank immediately, file at cybercrime.gov.in"},
    {"keywords":["hack","hacked","unauthorized","breach","data leak","server"],
     "crime":"Hacking / Unauthorized Access","category":"Network Crime","threat":"🔴 Critical","confidence":"88%",
     "action":"Change all passwords, report to CERT-In"},
    {"keywords":["bully","harass","abuse","stalk","blackmail","intimidate","troll"],
     "crime":"Cyberbullying / Harassment","category":"Social Media Crime","threat":"🟠 Medium","confidence":"85%",
     "action":"Block user, report on platform, file police complaint"},
    {"keywords":["porn","obscene","nude","explicit","sexual","morphed","intimate"],
     "crime":"Obscene Content","category":"Content Crime","threat":"🔴 Critical","confidence":"95%",
     "action":"Report immediately to cybercrime.gov.in"},
    {"keywords":["ransomware","virus","malware","trojan","spyware","infected","encrypt"],
     "crime":"Malware / Ransomware","category":"Network Crime","threat":"🔴 Critical","confidence":"91%",
     "action":"Disconnect internet, contact cybersecurity expert"},
    {"keywords":["identity","impersonate","fake profile","stolen identity"],
     "crime":"Identity Theft","category":"Identity Crime","threat":"🔴 High","confidence":"87%",
     "action":"Report to platform & police, secure accounts"},
    {"keywords":["fake news","misinformation","deepfake","propaganda"],
     "crime":"Misinformation / Fake News","category":"Social Media Crime","threat":"🟠 Medium","confidence":"80%",
     "action":"Report to platform, do not share further"},
]

def detect_crime_type(text):
    t = text.lower()
    for r in CRIME_RULES:
        if any(k in t for k in r["keywords"]): return r["crime"]
    return "Other Cyber Crime"

def analyze_text(text):
    t = text.lower()
    for r in CRIME_RULES:
        if any(k in t for k in r["keywords"]): return r
    return {"crime":"Other Cyber Crime","category":"General","threat":"🟡 Low","confidence":"60%",
            "action":"File a complaint at cybercrime.gov.in"}

# ── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/register")

@app.route("/register", methods=["GET"])
def register_page():
    return render_template("register.html")


# ── IMAGE CAPTCHA ─────────────────────────────────────────────────────────────
import random, time, string, io as _io
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def _gen_captcha_text(length=6):
    chars = string.ascii_uppercase + string.digits
    # Remove ambiguous chars
    chars = chars.replace("O","").replace("0","").replace("I","").replace("1","")
    return "".join(random.choices(chars, k=length))

@app.route("/captcha")
def captcha_image():
    text = _gen_captcha_text()
    session["captcha_text"] = text
    session["captcha_time"] = time.time()

    W, H = 200, 70
    img = Image.new("RGB", (W, H), color=(240, 244, 255))
    draw = ImageDraw.Draw(img)

    # Background noise lines
    for _ in range(5):
        x1,y1 = random.randint(0,W), random.randint(0,H)
        x2,y2 = random.randint(0,W), random.randint(0,H)
        draw.line([(x1,y1),(x2,y2)], fill=(random.randint(160,210), random.randint(160,210), random.randint(200,230)), width=1)

    # Noise dots
    for _ in range(60):
        x,y = random.randint(0,W), random.randint(0,H)
        draw.ellipse([x,y,x+2,y+2], fill=(random.randint(150,200),)*3)

    # Try to load a decent font, fall back gracefully
    font = None
    for fname in ["arial.ttf","Arial.ttf","DejaVuSans-Bold.ttf","LiberationSans-Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            font = ImageFont.truetype(fname, 36)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    # Draw each character with slight rotation & color variation
    x_offset = 8
    for ch in text:
        color = (random.randint(10,60), random.randint(10,80), random.randint(120,200))
        char_img = Image.new("RGBA", (36, 56), (0,0,0,0))
        char_draw = ImageDraw.Draw(char_img)
        char_draw.text((2, 4), ch, font=font, fill=color)
        angle = random.randint(-18, 18)
        char_img = char_img.rotate(angle, expand=True, resample=Image.BICUBIC)
        img.paste(char_img, (x_offset, random.randint(4, 14)), char_img)
        x_offset += 30

    img = img.filter(ImageFilter.SMOOTH)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    from flask import send_file
    response = send_file(buf, mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response

@app.route("/verify-captcha", methods=["POST"])
def verify_captcha():
    data = request.json
    user_ans = data.get("answer","").strip().upper()
    stored   = session.get("captcha_text","")
    ts       = session.get("captcha_time", 0)
    if not stored:
        return jsonify({"status":"error","message":"CAPTCHA expired. Refresh."})
    if time.time() - ts > 300:
        session.pop("captcha_text", None)
        return jsonify({"status":"error","message":"CAPTCHA expired. Refresh."})
    if user_ans != stored:
        # Regenerate on wrong attempt (handled client-side via /captcha reload)
        session.pop("captcha_text", None)
        return jsonify({"status":"error","message":"Incorrect CAPTCHA."})
    session["captcha_verified"] = True
    return jsonify({"status":"ok"})


# ── OTP SEND & VERIFY ─────────────────────────────────────────────────────────
import smtplib, requests as _requests
from email.mime.text import MIMEText

def _mask_email(email):
    try:
        at = email.index("@")
        return email[:min(3, at)] + "***" + email[at:]
    except Exception:
        return "***"

def _send_email_otp(to_email, otp):
    """Send OTP via Resend HTTP API — works on Railway (no SMTP ports needed)."""
    resend_key = os.environ.get("RESEND_KEY", "").strip()

    subject = "CyberGuard — Email Verification OTP"
    body = (
        f"Hello,\n\n"
        f"Your CyberGuard OTP is: {otp}\n\n"
        f"Valid for 5 minutes. Do not share it with anyone.\n\n"
        f"— CyberGuard Security Team"
    )

    # ── Resend HTTP API (primary — works on Railway) ──────────────────────
    if resend_key:
        try:
            smtp_user = os.environ.get("SMTP_USER", "").strip()
            # Use verified sender email if available, else use onboarding@resend.dev
            from_addr = f"CyberGuard <{smtp_user}>" if smtp_user else "CyberGuard <onboarding@resend.dev>"
            resp = _requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "from":    from_addr,
                    "to":      [to_email],
                    "subject": subject,
                    "text":    body
                },
                timeout=15
            )
            if resp.status_code in (200, 201):
                logging.info(f"OTP sent via Resend to {_mask_email(to_email)}")
                return
            # If 403 (unverified sender), try with onboarding@resend.dev
            if resp.status_code == 403:
                resp2 = _requests.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {resend_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "from":    "CyberGuard <onboarding@resend.dev>",
                        "to":      [to_email],
                        "subject": subject,
                        "text":    body
                    },
                    timeout=15
                )
                if resp2.status_code in (200, 201):
                    logging.info(f"OTP sent via Resend (onboarding) to {_mask_email(to_email)}")
                    return
                raise ValueError(f"Resend error {resp2.status_code}: {resp2.text[:200]}")
            raise ValueError(f"Resend error {resp.status_code}: {resp.text[:200]}")
        except ValueError:
            raise
        except Exception as e:
            logging.warning(f"Resend failed: {e}")

    # ── SMTP fallback (try both ports) ────────────────────────────────────
    import ssl as _ssl
    gmail_user = os.environ.get("SMTP_USER", "").strip()
    gmail_pass = os.environ.get("SMTP_PASS", "").strip()
    errors = []

    if gmail_user and gmail_pass:
        for port, use_ssl in [(587, False), (465, True)]:
            try:
                from email.mime.text import MIMEText as _MT
                msg = _MT(body, "plain")
                msg["Subject"] = subject
                msg["From"]    = f"CyberGuard <{gmail_user}>"
                msg["To"]      = to_email
                if use_ssl:
                    ctx = _ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = _ssl.CERT_NONE
                    with smtplib.SMTP_SSL("smtp.gmail.com", port, context=ctx, timeout=10) as s:
                        s.login(gmail_user, gmail_pass)
                        s.send_message(msg)
                else:
                    with smtplib.SMTP("smtp.gmail.com", port, timeout=10) as s:
                        s.ehlo(); s.starttls(); s.login(gmail_user, gmail_pass)
                        s.send_message(msg)
                logging.info(f"OTP sent via SMTP:{port} to {_mask_email(to_email)}")
                return
            except Exception as e:
                errors.append(f"{port}:{e}")

    raise ValueError(f"All email methods failed. Errors: {' | '.join(errors) if errors else 'No credentials configured'}")

def _send_sms_otp(phone, otp):
    api_key = os.environ.get("FAST2SMS_KEY", "").strip()
    if not api_key or api_key == "your_fast2sms_api_key":
        raise ValueError("Fast2SMS key not configured")
    resp = _requests.post(
        "https://www.fast2sms.com/dev/bulkV2",
        headers={"authorization": api_key, "Content-Type": "application/json"},
        json={"route": "q", "message": "CyberGuard OTP: " + otp + ". Valid 5 mins.",
              "language": "english", "flash": 0, "numbers": phone},
        timeout=8
    )
    data = resp.json()
    if not data.get("return"):
        m = data.get("message", "SMS failed")
        raise ValueError(" ".join(m) if isinstance(m, list) else str(m))

@app.route("/send-otp", methods=["POST"])
def send_otp():
    try:
        data  = request.json or {}
        email = data.get("email", "").strip()

        if not email or not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
            return jsonify({"status": "error", "message": "Valid email is required."})

        # Rate limiting via session
        sends = session.get("otp_sends", 0)
        last  = session.get("otp_last_send", 0.0)
        if time.time() - last > 600:
            sends = 0
        if sends >= 5:
            return jsonify({"status": "error", "message": "Too many requests. Wait 10 minutes."})

        otp = str(random.randint(100000, 999999))

        # Store OTP directly in session — no DB needed
        session["otp_code"]      = otp
        session["otp_email"]     = email
        session["otp_time"]      = time.time()
        session["otp_attempts"]  = 0
        session["otp_verified"]  = False
        session["otp_sends"]     = sends + 1
        session["otp_last_send"] = time.time()
        session.modified         = True

        # Send email
        try:
            _send_email_otp(email, otp)
            logging.info(f"OTP sent to {_mask_email(email)}")
            return jsonify({"status": "sent", "message": f"OTP sent to {_mask_email(email)}"})
        except Exception as e:
            logging.error(f"Email OTP failed: {e}")
            session.pop("otp_code", None)
            session.modified = True
            return jsonify({"status": "error", "message": f"Failed to send OTP: {str(e)}"})

    except Exception as ex:
        logging.error(f"send_otp crash: {ex}")
        return jsonify({"status": "error", "message": f"Server error: {str(ex)}"})


@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    try:
        data   = request.json or {}
        otp_in = data.get("otp", "").strip()

        stored_otp  = session.get("otp_code", "")
        stored_time = session.get("otp_time", 0)
        attempts    = session.get("otp_attempts", 0)

        if not stored_otp:
            return jsonify({"status": "error", "message": "No OTP found. Please request a new one."})
        if not otp_in or len(otp_in) != 6:
            return jsonify({"status": "error", "message": "Enter the 6-digit OTP."})
        if attempts >= 5:
            session.pop("otp_code", None)
            session.modified = True
            return jsonify({"status": "error", "message": "Too many wrong attempts. Request a new OTP."})
        if time.time() - stored_time > 300:
            session.pop("otp_code", None)
            session.modified = True
            return jsonify({"status": "error", "message": "OTP expired. Please request a new one."})
        if otp_in != stored_otp:
            session["otp_attempts"] = attempts + 1
            session.modified = True
            left = 4 - attempts
            return jsonify({"status": "error", "message": f"Incorrect OTP. {left} attempt(s) left."})

        # OTP correct
        session["otp_verified"] = True
        session.pop("otp_code", None)
        session.modified = True
        return jsonify({"status": "verified", "message": "OTP verified successfully."})

    except Exception as ex:
        logging.error(f"verify_otp error: {ex}")
        return jsonify({"status": "error", "message": f"Verification error: {str(ex)}"})

@app.route("/register", methods=["POST"])
def register_user():
    d = request.json or {}
    name     = d.get("name","").strip()
    email    = d.get("email","").strip()
    phone    = d.get("phone","").strip()
    password = d.get("password","")
    if not all([name, email, phone, password]):
        return jsonify({"status":"error","message":"All fields are required."})
    if not session.get("otp_verified"):
        return jsonify({"status":"error","message":"OTP not verified. Please verify your email first."})
    if not session.get("captcha_verified"):
        return jsonify({"status":"error","message":"CAPTCHA not verified."})
    session.pop("captcha_verified", None)
    session.pop("otp_verified", None)
    session.pop("otp_token", None)
    conn = get_db()
    p    = ph_for(conn)
    cur  = conn.cursor()
    try:
        cur.execute(
            f"INSERT INTO users(name,email,phone,password) VALUES({p},{p},{p},{p})",
            (name, email, phone, password)
        )
        conn.commit()
        conn.close()
    except Exception as ex:
        conn.close()
        err = str(ex).lower()
        if "unique" in err or "duplicate" in err:
            log_activity("register_failed", f"Duplicate email: {email}", user_email=email)
            return jsonify({"status":"duplicate","message":"This account is already registered. Redirecting to login..."})
        logging.error(f"register_user error: {ex}")
        return jsonify({"status":"error","message":f"Registration failed: {ex}"})
    log_activity("register", f"New user registered: {name}", user_email=email)
    return jsonify({"status":"success","message":"Account created successfully! Redirecting to login..."})

@app.route("/forgot-password")
def forgot_password_page():
    return render_template("forgot_password.html")

@app.route("/reset-password", methods=["POST"])
def reset_password():
    d        = request.json or {}
    email    = d.get("email","").strip()
    new_pass = d.get("new_password","")
    conn = get_db()
    p    = ph_for(conn)
    cur  = conn.cursor()
    cur.execute(f"SELECT id FROM users WHERE email={p}", (email,))
    user = db_fetchone(cur)
    if not user:
        conn.close()
        log_activity("password_reset_failed", f"Email not found: {email}", user_email=email)
        return jsonify({"success": False, "message": "Email not registered."})
    cur.execute(f"UPDATE users SET password={p} WHERE email={p}", (new_pass, email))
    conn.commit()
    conn.close()
    log_activity("password_reset", "Password reset successfully", user_email=email)
    return jsonify({"success": True, "message": "Password reset successful! Redirecting to login..."})

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        # Admin check
        if username == ADMIN_ID and password == ADMIN_PASSWORD:
            session["role"]  = "admin"
            session["email"] = "admin"
            session["name"]  = "Admin"
            log_activity("login", "Admin login", user_email="admin")
            return jsonify({"status":"success","role":"admin","message":"Welcome Admin! Redirecting to dashboard..."})
        # User check
        conn = get_db()
        p    = ph_for(conn)
        cur  = conn.cursor()
        cur.execute(f"SELECT * FROM users WHERE email={p} AND password={p}", (username, password))
        user = db_fetchone(cur)
        conn.close()
        if user:
            session["role"]  = "user"
            session["email"] = user["email"]
            session["name"]  = user["name"]
            log_activity("login", f"User login: {user['name']}", user_email=user["email"])
            return jsonify({"status":"success","role":"user","message":f"Welcome back, {user['name']}! Login successful."})
        log_activity("login_failed", f"Failed login attempt for: {username}", user_email=username)
        return jsonify({"status":"error","message":"Invalid credentials. Please try again."})
    return render_template("login.html")

@app.route("/home")
def home():
    if "email" not in session:
        return redirect("/login")
    return render_template("home.html")

@app.route("/safety-score")
def safety_score():
    if "email" not in session:
        return redirect("/login")
    return render_template("safety_score.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/test-email")
def test_email():
    """Debug route — shows env vars, Gmail test, DB test."""
    import smtplib, ssl as _ssl
    user   = os.environ.get("SMTP_USER","NOT_SET")
    pwd    = os.environ.get("SMTP_PASS","NOT_SET")
    db_url = "SET" if os.environ.get("DATABASE_URL","") else "NOT_SET"
    result = {
        "SMTP_USER": user,
        "SMTP_PASS_SET": "YES" if pwd != "NOT_SET" else "NO",
        "DATABASE_URL": db_url,
    }
    if user != "NOT_SET" and pwd != "NOT_SET":
        try:
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
                srv.login(user, pwd)
                result["smtp_test"] = "LOGIN OK"
        except Exception as e:
            result["smtp_test"] = f"FAILED: {e}"
    else:
        result["smtp_test"] = "SKIPPED — env vars missing"
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        result["db_test"] = "DB OK"
    except Exception as e:
        result["db_test"] = f"DB FAILED: {e}"
    return jsonify(result)

@app.route("/test-chat")
def test_chat():
    """Debug route — test Groq and Gemini AI directly."""
    result = {}
    groq_key = os.environ.get("GROQ_API_KEY","").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY","").strip()
    result["GROQ_KEY_SET"] = "YES" if groq_key else "NO"
    result["GEMINI_KEY_SET"] = "YES" if gemini_key else "NO"
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            r = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role":"user","content":"say hello in 5 words"}],
                max_tokens=20
            )
            result["groq_test"] = "OK: " + r.choices[0].message.content.strip()
        except Exception as e:
            result["groq_test"] = f"FAILED: {e}"
    if gemini_key:
        try:
            from google import genai as _gai
            gc = _gai.Client(api_key=gemini_key)
            resp = gc.models.generate_content(model="gemini-2.0-flash-lite", contents="say hello in 5 words")
            result["gemini_test"] = "OK: " + resp.text.strip()
        except Exception as e:
            result["gemini_test"] = f"FAILED: {e}"
    return jsonify(result)

@app.route("/alerts")
def alerts():
    if "email" not in session:
        return redirect("/login")
    return render_template("alerts.html")

@app.route("/complaint", methods=["GET"])
def complaint():
    if "email" not in session:
        return redirect("/login")
    return render_template("complaint.html")

@app.route("/submit_complaint", methods=["POST"])
def submit_complaint():
    if "email" not in session:
        return jsonify({"status":"error","message":"Session expired. Please login again."})
    try:
        name        = request.form.get("name","")
        email       = request.form.get("email","")
        phone       = request.form.get("phone","")
        address     = request.form.get("address","")
        description = request.form.get("description","")
        date        = request.form.get("date","")
        platform    = request.form.get("platform","")
        severity    = request.form.get("severity","")
        suspect_url = request.form.get("suspect_url","")
        if platform:    description += f"\n[Platform: {platform}]"
        if severity:    description += f"\n[Severity: {severity}]"
        if suspect_url: description += f"\n[Suspect URL: {suspect_url}]"
        crime_type = detect_crime_type(description)
        file_objs  = []
        for field in ["image","video"]:
            uf = request.files.get(field)
            if uf and uf.filename:
                fn = secure_filename(uf.filename)
                uf.save(os.path.join(app.config["UPLOAD_FOLDER"], fn))
                file_objs.append(fn)
        conn = get_db()
        p = ph_for(conn)
        cur = conn.cursor()
        is_pg = _is_pg(conn)

        if is_pg:
            cur.execute(
                f"INSERT INTO complaints(user_email,name,email,phone,address,crime_type,description,file,date,status) VALUES({p},{p},{p},{p},{p},{p},{p},{p},{p},{p}) RETURNING id",
                (session["email"],name,email,phone,address,crime_type,description,",".join(file_objs),date,"Pending")
            )
            complaint_id = cur.fetchone()[0]
        else:
            cur.execute(
                f"INSERT INTO complaints(user_email,name,email,phone,address,crime_type,description,file,date,status) VALUES({p},{p},{p},{p},{p},{p},{p},{p},{p},{p})",
                (session["email"],name,email,phone,address,crime_type,description,",".join(file_objs),date,"Pending")
            )
            complaint_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Format unique complaint ID: CG-YYYY-XXXXX
        from datetime import datetime as dt
        year = dt.now().year
        formatted_id = f"CG-{year}-{complaint_id:05d}"

        log_activity("complaint_submitted", f"ID: {formatted_id}, Crime: {crime_type}")

        # ── Forward to cybercrime.gov.in (deep link with pre-filled data) ──
        import urllib.parse
        gov_params = urllib.parse.urlencode({
            "complaint_type": crime_type,
            "name": name,
            "email": email,
            "phone": phone,
            "description": description[:500]
        })
        gov_link = f"https://cybercrime.gov.in/Webform/Accept.aspx"

        # ── Email notification to admin (if SMTP configured) ──
        _send_complaint_email(formatted_id, name, email, crime_type, description, date)

        return jsonify({
            "status": "success",
            "complaint_id": formatted_id,
            "raw_id": complaint_id,
            "gov_link": gov_link,
            "message": "Your complaint has been successfully submitted to Cyber Crime. You will be contacted shortly."
        })
    except Exception as ex:
        logging.error(f"submit_complaint error: {ex}")
        return jsonify({"status":"error","message":f"Submission failed: {str(ex)}"})

@app.route("/dashboard")
def dashboard():
    if "role" not in session:
        return redirect("/login")
    if session["role"] != "admin":
        return redirect("/home")
    conn = get_db()
    cur  = conn.cursor()
    is_pg = _is_pg(conn)

    cur.execute("SELECT * FROM complaints ORDER BY id DESC")
    complaints_raw = db_fetchall(cur)
    cur.execute("SELECT * FROM users ORDER BY id DESC")
    users_raw = db_fetchall(cur)
    cur.execute("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 50")
    activity_raw = db_fetchall(cur)
    cur.execute("SELECT * FROM ai_analysis_logs ORDER BY id DESC LIMIT 50")
    ai_logs_raw = db_fetchall(cur)

    # 7-day trend
    if is_pg:
        cur.execute("""
            SELECT date(submitted::timestamp) as day, COUNT(*) as cnt
            FROM complaints
            WHERE submitted::timestamp >= NOW() - INTERVAL '6 days'
            GROUP BY day ORDER BY day
        """)
    else:
        cur.execute("""
            SELECT date(submitted,'localtime') as day, COUNT(*) as cnt
            FROM complaints
            WHERE submitted >= date('now','localtime','-6 days')
            GROUP BY day ORDER BY day
        """)
    trend_raw = db_fetchall(cur)
    conn.close()

    from datetime import date, timedelta
    trend_map = {row["day"]: row["cnt"] for row in trend_raw}
    trend_labels, trend_data = [], []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i))
        trend_labels.append(d.strftime("%a %d"))
        trend_data.append(trend_map.get(d.isoformat(), 0))

    complaints = complaints_raw
    users      = users_raw
    activity   = activity_raw
    ai_logs    = ai_logs_raw
    total    = len(complaints)
    pending  = sum(1 for c in complaints if c.get("status") == "Pending")
    resolved = sum(1 for c in complaints if c.get("status") == "Resolved")
    return render_template("dashboard.html",
        complaints=complaints, users=users,
        activity=activity, ai_logs=ai_logs,
        total=total, pending=pending, resolved=resolved,
        trend_labels=trend_labels, trend_data=trend_data,
        role=session.get("role"), username=session.get("name"))

@app.route("/submit_feedback", methods=["POST"])
def submit_feedback():
    if "email" not in session:
        return jsonify({"status": "error", "message": "Not logged in."})
    try:
        d = request.json or {}
        rating       = int(d.get("rating", 0))
        comment      = d.get("comment", "").strip()
        complaint_id = d.get("complaint_id", "").strip()
        if not 1 <= rating <= 5:
            return jsonify({"status": "error", "message": "Rating must be 1-5."})
        conn = get_db()
        p    = ph_for(conn)
        cur  = conn.cursor()
        cur.execute(
            f"INSERT INTO feedback(user_email, complaint_id, rating, comment) VALUES({p},{p},{p},{p})",
            (session["email"], complaint_id, rating, comment)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Thank you for your feedback!"})
    except Exception as ex:
        logging.error(f"submit_feedback error: {ex}")
        return jsonify({"status": "error", "message": str(ex)})


@app.route("/update_status", methods=["POST"])
def update_status():
    if session.get("role") != "admin":
        return jsonify({"status":"error","message":"Unauthorized"})
    d = request.json
    conn = get_db()
    p = ph_for(conn)
    cur = conn.cursor()
    cur.execute(f"UPDATE complaints SET status={p} WHERE id={p}", (d["status"], d["id"]))
    conn.commit()
    conn.close()
    log_activity("status_update", f"Complaint #{d['id']} → {d['status']}")
    return jsonify({"status":"success"})

# ── CSV / DATA VIEWER EXPORT ─────────────────────────────────────────────────
from flask import Response
import csv, io

def _admin_required():
    return session.get("role") != "admin"

def _make_csv(headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") or "" for h in headers])
    return output.getvalue()

@app.route("/export/complaints.csv")
def export_complaints_csv():
    if _admin_required(): return redirect("/login")
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall()]
    conn.close()
    headers = ["id","user_email","name","email","phone","address","crime_type","description","file","date","status","submitted"]
    log_activity("export_csv", "Exported complaints.csv")
    return Response(_make_csv(headers, rows), mimetype="text/csv",
        headers={"Content-Disposition":"attachment;filename=complaints.csv"})

@app.route("/export/users.csv")
def export_users_csv():
    if _admin_required(): return redirect("/login")
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT id,name,email,phone,created FROM users ORDER BY id DESC").fetchall()]
    conn.close()
    headers = ["id","name","email","phone","created"]
    log_activity("export_csv", "Exported users.csv")
    return Response(_make_csv(headers, rows), mimetype="text/csv",
        headers={"Content-Disposition":"attachment;filename=users.csv"})

@app.route("/export/activity.csv")
def export_activity_csv():
    if _admin_required(): return redirect("/login")
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM activity_logs ORDER BY id DESC").fetchall()]
    conn.close()
    headers = ["id","user_email","action","detail","ip","timestamp"]
    log_activity("export_csv", "Exported activity.csv")
    return Response(_make_csv(headers, rows), mimetype="text/csv",
        headers={"Content-Disposition":"attachment;filename=activity_logs.csv"})

@app.route("/export/ai_logs.csv")
def export_ai_logs_csv():
    if _admin_required(): return redirect("/login")
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM ai_analysis_logs ORDER BY id DESC").fetchall()]
    conn.close()
    headers = ["id","user_email","input_text","crime","category","threat","confidence","language","source","timestamp"]
    log_activity("export_csv", "Exported ai_logs.csv")
    return Response(_make_csv(headers, rows), mimetype="text/csv",
        headers={"Content-Disposition":"attachment;filename=ai_analysis_logs.csv"})

@app.route("/data-viewer")
def data_viewer():
    if _admin_required(): return redirect("/login")
    table = request.args.get("table", "complaints")
    allowed = {"complaints","users","activity_logs","ai_analysis_logs"}
    if table not in allowed:
        table = "complaints"
    conn = get_db()
    rows_raw = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
    conn.close()
    rows = [dict(r) for r in rows_raw]
    headers = list(rows[0].keys()) if rows else []
    counts = {}
    conn = get_db()
    for t in allowed:
        counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    conn.close()
    log_activity("data_viewer", f"Viewed table: {table}")
    return render_template("data_viewer.html",
        table=table, rows=rows, headers=headers,
        counts=counts, username=session.get("name"))

@app.route("/logout")
def logout():
    log_activity("logout", "User logged out")
    session.clear()
    return redirect("/login")

# ── XML BACKUP ───────────────────────────────────────────────────────────────
import xml.etree.ElementTree as ET
from datetime import datetime

def _db_to_xml():
    """Generate a full XML backup of all tables with proper indentation."""
    root = ET.Element("cybercrime_portal_backup")
    root.set("generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    root.set("version", "1.0")

    conn = get_db()
    tables = {
        "users":            ["id","name","email","phone","created"],
        "complaints":       ["id","user_email","name","email","phone","address","crime_type","description","file","date","status","submitted"],
        "activity_logs":    ["id","user_email","action","detail","ip","timestamp"],
        "ai_analysis_logs": ["id","user_email","input_text","crime","category","threat","confidence","language","source","timestamp"],
    }
    for tname, fields in tables.items():
        tbl_el = ET.SubElement(root, tname)
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {tname} ORDER BY id DESC").fetchall()]
        tbl_el.set("count", str(len(rows)))
        for row in rows:
            item = ET.SubElement(tbl_el, "record")
            for f in fields:
                el = ET.SubElement(item, f)
                el.text = str(row.get(f) or "")
    conn.close()

    # Pretty-print with indentation (Python 3.9+)
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        # Fallback for Python < 3.9
        _indent_xml(root)

    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def _indent_xml(elem, level=0):
    """Add pretty-print indentation for Python < 3.9."""
    pad = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad

@app.route("/export/backup.xml")
def export_backup_xml():
    if _admin_required(): return redirect("/login")
    # Build structured data for the viewer
    conn = get_db()
    tables = {
        "complaints":       ["id","user_email","name","email","phone","address","crime_type","description","file","date","status","submitted"],
        "users":            ["id","name","email","phone","created"],
        "activity_logs":    ["id","user_email","action","detail","ip","timestamp"],
        "ai_analysis_logs": ["id","user_email","input_text","crime","category","threat","confidence","language","source","timestamp"],
    }
    data = {}
    for tname, fields in tables.items():
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {tname} ORDER BY id DESC").fetchall()]
        data[tname] = {"fields": fields, "rows": rows}
    conn.close()

    # Also generate the raw XML string for download option
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + _db_to_xml()
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_activity("view_xml_backup", "Viewed XML backup")

    download = request.args.get("download") == "1"
    if download:
        return Response(xml_str, mimetype="application/xml",
            headers={"Content-Disposition": f"attachment;filename=cybercrime_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"})

    return render_template("xml_viewer.html",
        data=data, generated=generated, username=session.get("name"))

@app.route("/export/complaints.xml")
def export_complaints_xml():
    if _admin_required(): return redirect("/login")
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall()]
    conn.close()
    root = ET.Element("complaints", count=str(len(rows)),
                      exported=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    fields = ["id","user_email","name","email","phone","address","crime_type","description","file","date","status","submitted"]
    for row in rows:
        item = ET.SubElement(root, "complaint")
        for f in fields:
            ET.SubElement(item, f).text = str(row.get(f) or "")
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    log_activity("export_xml", "Exported complaints.xml")
    return Response(xml_str, mimetype="application/xml",
        headers={"Content-Disposition":"attachment;filename=complaints.xml"})

# ── COMPLAINT STATUS TRACKER (public) ────────────────────────────────────────
@app.route("/track", methods=["GET","POST"])
def track_complaint():
    if "email" not in session:
        return redirect("/login")
    result = None
    error  = None
    if request.method == "POST":
        cid = request.form.get("complaint_id","").strip().upper()
        # Accept both "CG-2026-00042" and plain "42"
        raw_id = None
        if cid.startswith("CG-") and len(cid.split("-")) == 3:
            try:
                raw_id = int(cid.split("-")[2])
            except ValueError:
                error = "Invalid complaint ID format."
        elif cid.isdigit():
            raw_id = int(cid)
        else:
            error = "Please enter a valid Complaint ID (e.g. CG-2026-00042 or 42)."

        if raw_id is not None:
            conn = get_db()
            p = ph_for(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT id,name,crime_type,date,status,submitted FROM complaints WHERE id={p} AND user_email={p}",
                (raw_id, session["email"])
            )
            row = db_fetchone(cur)
            conn.close()
            if row:
                result = row
                from datetime import datetime as dt
                result["formatted_id"] = f"CG-{dt.now().year}-{result['id']:05d}"
            else:
                error = "No complaint found with that ID for your account."
        log_activity("track_complaint", f"Tracked: {cid}")
    return render_template("track.html", result=result, error=error,
                           username=session.get("name"))

# ── LIVE DASHBOARD STATS (JSON for auto-refresh) ─────────────────────────────
@app.route("/api/stats")
def api_stats():
    if session.get("role") != "admin":
        return jsonify({"error":"unauthorized"}), 403
    conn = get_db()
    is_pg = _is_pg(conn)
    today_sql = "date(submitted::timestamp)=CURRENT_DATE" if is_pg else "date(submitted)=date('now','localtime')"
    def count(sql):
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else 0
    stats = {
        "total":    count("SELECT COUNT(*) FROM complaints"),
        "pending":  count("SELECT COUNT(*) FROM complaints WHERE status='Pending'"),
        "resolved": count("SELECT COUNT(*) FROM complaints WHERE status='Resolved'"),
        "users":    count("SELECT COUNT(*) FROM users"),
        "today":    count(f"SELECT COUNT(*) FROM complaints WHERE {today_sql}"),
        "ai_logs":  count("SELECT COUNT(*) FROM ai_analysis_logs"),
    }
    conn.close()
    return jsonify(stats)

# ── SEARCH COMPLAINTS (admin) ─────────────────────────────────────────────────
@app.route("/api/search")
def search_complaints():
    if session.get("role") != "admin":
        return jsonify({"error":"unauthorized"}), 403
    q      = request.args.get("q","").strip()
    status = request.args.get("status","")
    conn   = get_db()
    sql    = "SELECT id,name,email,crime_type,date,status FROM complaints WHERE 1=1"
    params = []
    if q:
        sql += " AND (name LIKE ? OR email LIKE ? OR crime_type LIKE ? OR description LIKE ?)"
        params += [f"%{q}%"]*4
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT 100"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js",
        mimetype="application/javascript")

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json",
        mimetype="application/manifest+json")

@app.route("/offline")
def offline():
    return render_template("offline.html")

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/analyze", methods=["POST"])
def analyze():
    text = request.json.get("text","")
    r = analyze_text(text)
    try: lang = detect(text)
    except: lang = "unknown"
    # Save analysis to DB
    try:
        conn = get_db()
        p = ph_for(conn)
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO ai_analysis_logs(user_email,input_text,crime,category,threat,confidence,language,source) VALUES({p},{p},{p},{p},{p},{p},{p},{p})",
            (session.get("email","anonymous"), text[:500], r["crime"], r["category"], r["threat"], r["confidence"], lang, "analyze")
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.warning(f"analyze log failed: {e}")
    log_activity("ai_analyze", f"Crime detected: {r['crime']}")
    return jsonify({**r, "language":lang})


# ── CHATBOT (Bilingual: English + Hindi) ─────────────────────────────────────
# Each tuple: (english_keywords, hindi_keywords, english_reply, hindi_reply)
CHAT_KB = [
    (
        ["hello","hi","hey","help","start","good morning","good evening"],
        ["namaste","namaskar","helo","madad","help","shuru","kaise","kya","namskar"],
        "Hi! I'm CyberBot, your AI cybercrime assistant.\n\nYou can ask me about:\n- Phishing & bank fraud\n- Hacking & data breach\n- Cyberbullying & harassment\n- Malware & ransomware\n- Online scams & UPI fraud\n- How to file a complaint\n\nHow can I help you today?",
        "Namaste! Main CyberBot hoon, aapka AI cyber crime sahayak.\n\nAap mujhse pooch sakte hain:\n- Phishing aur bank fraud\n- Hacking aur data leak\n- Cyber bullying aur utpeedan\n- Malware aur ransomware\n- Online scam aur UPI fraud\n- Shikayat kaise darj karein\n\nMain aapki kaise madad kar sakta hoon?"
    ),
    (
        ["otp","phish","bank","credential","fake link","fake call","fake email","verify account","account blocked","password stolen"],
        ["otp","bank","khata","password","link","call","email","verify","block","fake","dhoka","thagi","paise","account"],
        "This sounds like a Phishing Attack!\n\nImmediate steps:\n- Do NOT share OTP with anyone\n- Block the sender/caller immediately\n- Contact your bank helpline right away\n- File complaint at cybercrime.gov.in\n- Call National Helpline: 1930\n\nRemember: No bank ever asks for OTP over call or SMS.",
        "Yeh Phishing Attack lagta hai!\n\nTurant karein:\n- Kisi ko bhi OTP share na karein\n- Bhejne wale ko turant block karein\n- Apne bank ki helpline par call karein\n- cybercrime.gov.in par shikayat darj karein\n- Rashtriya Helpline: 1930\n\nYaad rakhein: Koi bhi bank kabhi OTP nahi mangta."
    ),
    (
        ["upi","money","transfer","fraud","scam","payment","wallet","fake offer","lottery","prize","refund","cashback"],
        ["upi","paisa","paise","transfer","fraud","scam","payment","wallet","lottery","prize","refund","cashback","thagi","loot","online","nuksaan"],
        "This looks like Online Financial Fraud!\n\nImmediate steps:\n- Call your bank immediately to freeze the transaction\n- File complaint at cybercrime.gov.in within 24 hours\n- Call helpline: 1930\n- Keep all screenshots and transaction IDs as evidence\n- Do NOT transfer any more money",
        "Yeh Online Vittiya Dhokhadhadi lagti hai!\n\nTurant karein:\n- Apne bank ko turant call karein aur transaction rokein\n- 24 ghante ke andar cybercrime.gov.in par shikayat karein\n- Helpline: 1930\n- Sabhi screenshots aur transaction ID surakshit rakhein\n- Aur paise transfer na karein"
    ),
    (
        ["hack","hacked","unauthorized","breach","data leak","account taken","password changed"],
        ["hack","hacked","account","password","badal","kisi ne","data","leak","unauthorized","access","chori"],
        "This is Hacking / Unauthorized Access!\n\nImmediate steps:\n- Change all passwords immediately\n- Enable 2-Factor Authentication on all accounts\n- Check for unknown devices in account settings\n- Report to CERT-In: cert-in.org.in\n- File complaint at cybercrime.gov.in",
        "Yeh Hacking / Anadhikrit Pahunch hai!\n\nTurant karein:\n- Sabhi passwords turant badlein\n- Sabhi accounts par 2-Factor Authentication chaluu karein\n- Account settings mein anjaan device check karein\n- CERT-In ko report karein: cert-in.org.in\n- cybercrime.gov.in par shikayat darj karein"
    ),
    (
        ["bully","harass","abuse","stalk","blackmail","troll","insult","threat","intimidate","morphed","photo","video leak"],
        ["bully","pareshan","dhamki","blackmail","troll","gali","photo","video","leak","stalk","harassment","dara","dhamkana"],
        "This is Cyberbullying / Online Harassment!\n\nImmediate steps:\n- Block the person on all platforms immediately\n- Take screenshots of all messages as evidence\n- Report the profile on the platform\n- File a police complaint at your nearest station\n- Call helpline: 1930 | Women helpline: 1091",
        "Yeh Cyber Bullying / Online Utpeedan hai!\n\nTurant karein:\n- Us vyakti ko sabhi platforms par block karein\n- Sabhi messages ke screenshots lein\n- Platform par profile report karein\n- Najdeeki police station mein shikayat darj karein\n- Helpline: 1930 | Mahila Helpline: 1091"
    ),
    (
        ["virus","malware","ransomware","trojan","spyware","infected","encrypt","files locked","pay ransom"],
        ["virus","malware","ransomware","file","lock","encrypt","computer","phone","infected","slow","hack"],
        "This is a Malware / Ransomware Attack!\n\nImmediate steps:\n- Disconnect from internet immediately\n- Do NOT pay any ransom\n- Contact a cybersecurity expert\n- Report to CERT-In: cert-in.org.in\n- Restore from backup if available",
        "Yeh Malware / Ransomware Attack hai!\n\nTurant karein:\n- Internet se turant disconnect karein\n- Koi bhi fidya na dein\n- Cyber suraksha visheshagya se sampark karein\n- CERT-In ko report karein: cert-in.org.in\n- Backup se data restore karein"
    ),
    (
        ["fake profile","impersonate","identity","stolen","pretend","fake account","someone using my name"],
        ["fake","profile","identity","naam","account","koi","mera","use","impersonate","naqli"],
        "This is Identity Theft / Impersonation!\n\nImmediate steps:\n- Report the fake profile to the platform immediately\n- File complaint at cybercrime.gov.in\n- Inform your contacts about the fake account\n- File an FIR at your nearest police station\n- Call helpline: 1930",
        "Yeh Pahchan ki Chori / Naqli Profile hai!\n\nTurant karein:\n- Platform par naqli profile report karein\n- cybercrime.gov.in par shikayat darj karein\n- Apne contacts ko naqli account ke baare mein batayein\n- Najdeeki police station mein FIR darj karein\n- Helpline: 1930"
    ),
    (
        ["complaint","report","file","register","submit","how to"],
        ["shikayat","complaint","report","kaise","darz","karna","submit","file","register"],
        "How to file a complaint:\n\n1. Click Report Complaint in the navbar\n2. Fill in your details and describe the incident\n3. Upload evidence (screenshots/videos)\n4. Submit - you will get a complaint ID\n\nAlternatively:\n- Visit: cybercrime.gov.in\n- Call: 1930 (National Helpline)",
        "Shikayat kaise darj karein:\n\n1. Navbar mein Report Complaint par click karein\n2. Apni jaankari bharein aur ghatna ka vivaran dein\n3. Saboot upload karein (screenshots/video)\n4. Submit karein - aapko shikayat ID milegi\n\nVaikalpik roop se:\n- Website: cybercrime.gov.in\n- Call karein: 1930"
    ),
    (
        ["helpline","number","contact","call","police","emergency","1930"],
        ["helpline","number","contact","call","police","1930","madad","emergency","phone"],
        "Important Helplines:\n\n- Cyber Crime Helpline: 1930\n- Women Helpline: 1091\n- Child Helpline: 1098\n- Police: 100\n- Ambulance: 108\n- Online Portal: cybercrime.gov.in",
        "Mahatvapurn Helplines:\n\n- Cyber Crime Helpline: 1930\n- Mahila Helpline: 1091\n- Bal Helpline: 1098\n- Police: 100\n- Ambulance: 108\n- Online Portal: cybercrime.gov.in"
    ),
    (
        ["safe","protect","prevent","tips","advice","secure"],
        ["safe","suraksha","bachao","tips","advice","secure","protect","kaise","rahein"],
        "Cyber Safety Tips:\n\n- Never share OTP, PIN or password with anyone\n- Use strong, unique passwords for each account\n- Enable 2-Factor Authentication everywhere\n- Avoid clicking unknown links in SMS/email\n- Keep your software and apps updated",
        "Cyber Suraksha Tips:\n\n- Kisi ko bhi OTP, PIN ya password share na karein\n- Har account ke liye mazboot aur alag password rakhein\n- Har jagah 2-Factor Authentication chaluu karein\n- SMS/email mein anjaan links par click na karein\n- Apne software aur apps update rakhein"
    ),
    (
        ["thank","thanks","ok","okay","bye","goodbye","done","great"],
        ["shukriya","dhanyawad","theek","ok","bye","alvida","thanks","acha","accha"],
        "You are welcome! Stay safe online.\n\nIf you face any cybercrime:\n- Report at cybercrime.gov.in\n- Call helpline: 1930\n\nI am always here to help!",
        "Aapka swagat hai! Online surakshit rahein.\n\nKisi bhi cyber crime ke liye:\n- cybercrime.gov.in par report karein\n- Helpline: 1930\n\nMain hamesha aapki madad ke liye yahan hoon!"
    ),
]

@app.route("/chat", methods=["POST"])
def chat():
    try:
        msg = (request.json or {}).get("message", "").strip()
        if not msg:
            return jsonify({"reply": "Please type a message."})

        SYSTEM = (
            "You are CyberBot, a friendly and intelligent AI assistant for India's Student Cybercrime Portal. "
            "You can answer questions about cybercrime, cyber safety, online fraud, hacking, phishing, "
            "cyberbullying, identity theft, ransomware, UPI fraud, and related topics. "
            "If someone sends unclear, random, or gibberish text, ask them politely to clarify what they need help with. "
            "If someone greets you, respond warmly and ask how you can help. "
            "If the question is completely unrelated to cybercrime or safety, politely say you specialize in cybercrime "
            "and ask if they have a cyber safety question. "
            "For cybercrime questions: give a clear explanation, numbered action steps, and relevant Indian helplines "
            "(1930 for cyber crime, 1091 for women, 100 for police). Direct users to cybercrime.gov.in for complaints. "
            "Support both English and Hindi/Hinglish — respond in the same language the user writes in. "
            "Keep responses under 200 words. Be conversational, warm and helpful like a real assistant."
        )

        ai_errors = []

        # ── Try Groq ──────────────────────────────────────────────────────
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if groq_key:
            for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]:
                try:
                    from groq import Groq
                    client = Groq(api_key=groq_key)
                    completion = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": SYSTEM},
                            {"role": "user",   "content": msg}
                        ],
                        max_tokens=350, temperature=0.8,
                    )
                    reply = completion.choices[0].message.content.strip()
                    logging.info(f"CyberBot replied via Groq {model}")
                    return jsonify({"reply": reply})
                except Exception as e:
                    ai_errors.append(f"Groq/{model}: {e}")
                    logging.warning(f"Groq {model} error: {e}")
                    continue

        # ── Try Gemini ────────────────────────────────────────────────────
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if gemini_key:
            for gmodel in ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"]:
                try:
                    from google import genai as google_genai
                    gclient = google_genai.Client(api_key=gemini_key)
                    response = gclient.models.generate_content(
                        model=gmodel,
                        contents=f"{SYSTEM}\n\nUser: {msg}"
                    )
                    reply = response.text.strip()
                    logging.info(f"CyberBot replied via Gemini {gmodel}")
                    return jsonify({"reply": reply})
                except Exception as e:
                    ai_errors.append(f"Gemini/{gmodel}: {e}")
                    logging.warning(f"Gemini {gmodel} error: {e}")
                    continue

        # ── All AI failed — log and use smart fallback ────────────────────
        logging.error(f"All AI providers failed for chat: {' | '.join(ai_errors)}")
        return _smart_reply(msg, False)

    except Exception as ex:
        logging.error(f"chat route error: {ex}")
        return jsonify({"reply": "Sorry, I'm having trouble right now. Please try again in a moment."})


def _send_complaint_email(complaint_id, name, email, crime_type, description, date):
    """Send complaint confirmation via Resend HTTP API — non-blocking."""
    try:
        resend_key = os.environ.get("RESEND_KEY", "").strip()
        if not resend_key:
            return  # Skip silently if not configured

        smtp_user = os.environ.get("SMTP_USER", "").strip()
        from_addr = f"CyberGuard <{smtp_user}>" if smtp_user else "CyberGuard <onboarding@resend.dev>"

        confirm_body = (
            f"Dear {name},\n\n"
            f"Your complaint has been registered on CyberGuard Portal.\n\n"
            f"Complaint ID : {complaint_id}\n"
            f"Crime Type   : {crime_type}\n"
            f"Status       : Pending Review\n\n"
            f"Track your complaint on the portal.\n"
            f"For urgent help, call: 1930\n\n"
            f"Stay safe,\nCyberGuard Team"
        )

        import requests as _req
        _req.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={"from": from_addr, "to": [email], "subject": f"Complaint Registered — {complaint_id} | CyberGuard", "text": confirm_body},
            timeout=8
        )
        logging.info(f"Complaint confirmation sent for {complaint_id}")
    except Exception as e:
        logging.warning(f"Complaint email failed (non-critical): {e}")


def _log_ai(msg, reply, hindi=False):
    """Log chatbot AI interaction to ai_analysis_logs."""
    try:
        r = analyze_text(msg.lower())
        conn = get_db()
        p = ph_for(conn)
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO ai_analysis_logs(user_email,input_text,crime,category,threat,confidence,language,source) VALUES({p},{p},{p},{p},{p},{p},{p},{p})",
            (session.get("email","anonymous"), msg[:500], r["crime"], r["category"],
             r["threat"], r["confidence"], "hi" if hindi else "en", "chatbot")
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _smart_reply(msg, hindi):
    t = msg.lower()

    rules = [
        (["hello","hi","hey","start","help","good morning","good evening"],
         "👋 Hello! I'm CyberBot — your AI cybercrime assistant.\n\nTell me what happened and I'll guide you step by step. I can help with:\n• Phishing & bank fraud\n• Hacking & account takeover\n• Cyberbullying & harassment\n• UPI / payment fraud\n• Ransomware & malware\n• Identity theft\n• How to file a complaint\n\n📞 Emergency Helpline: 1930"),

        (["phish","otp","bank","fake link","fake call","fake email","verify account","account blocked","suspicious link","fake sms"],
         "🎣 This sounds like a Phishing Attack!\n\nCriminals impersonate banks or companies to steal your credentials.\n\n✅ Do this NOW:\n1. Do NOT share OTP, PIN or password with anyone\n2. Block the sender/caller immediately\n3. Call your bank to freeze the account\n4. Change passwords from a safe device\n5. File complaint: cybercrime.gov.in\n\n⚠️ No bank ever asks for OTP over call or SMS.\n\n📞 Bank Fraud: 14440 | Cyber Crime: 1930"),

        (["upi","gpay","phonepe","paytm","money","transfer","fraud","scam","payment","lottery","prize","refund","cashback","investment","crypto","bitcoin","₹"],
         "💸 This looks like Online Financial Fraud!\n\n✅ Do this NOW:\n1. Call your bank immediately to freeze the transaction\n2. File complaint at cybercrime.gov.in within 24 hours\n3. Call 1930 right away\n4. Save all screenshots and transaction IDs as evidence\n5. Do NOT send more money — even if threatened\n\n💡 Report within 1 hour — banks can often reverse the transaction!\n\n📞 Cyber Crime: 1930 | Bank Fraud: 14440"),

        (["hack","hacked","unauthorized","breach","data leak","account taken","password changed","unknown device","login alert"],
         "🔓 This is Hacking / Unauthorized Account Access!\n\n✅ Do this NOW:\n1. Change your password immediately from a different device\n2. Enable 2-Factor Authentication (2FA) on all accounts\n3. Log out all unknown devices from account settings\n4. Check data breach: haveibeenpwned.com\n5. Report to CERT-In: cert-in.org.in\n6. File complaint: cybercrime.gov.in\n\n📞 Cyber Crime: 1930 | CERT-In: 1800-11-4949"),

        (["bully","harass","abuse","stalk","blackmail","troll","threat","morphed","photo leak","video leak","sextortion","nude","intimate","defame"],
         "😡 This is Cyberbullying / Online Harassment!\n\nThis is a serious crime under IT Act & IPC.\n\n✅ Do this NOW:\n1. Do NOT respond to the bully\n2. Screenshot all messages as evidence\n3. Block the person on all platforms\n4. Report the profile to the platform\n5. File police complaint at nearest station\n6. For morphed images/sextortion: cybercrime.gov.in immediately\n\n💙 You are not alone.\n\n📞 Cyber Crime: 1930 | Women: 1091 | iCall: 9152987821"),

        (["virus","malware","ransomware","trojan","spyware","infected","encrypt","files locked","ransom","slow computer","popup"],
         "🦠 This is a Malware / Ransomware Attack!\n\n✅ Do this NOW:\n1. Disconnect from internet immediately\n2. Do NOT pay any ransom\n3. Do NOT restart the computer\n4. Contact your college IT department\n5. Report to CERT-In: cert-in.org.in\n6. Restore from backup if available\n\n📞 CERT-In: 1800-11-4949 | Cyber Crime: 1930"),

        (["identity","impersonate","fake profile","fake account","my photo","my name","pretend to be me"],
         "🪪 This is Identity Theft / Impersonation!\n\n✅ Do this NOW:\n1. Report the fake profile to the platform immediately\n2. Inform your contacts about the fake account\n3. File complaint: cybercrime.gov.in\n4. File FIR at nearest police station\n5. Change passwords on all linked accounts\n\n📞 Cyber Crime: 1930 | Police: 100"),

        (["complaint","report","file","register","submit","how to"],
         "📋 How to File a Cybercrime Complaint:\n\n🌐 Online: cybercrime.gov.in\n1. Click 'Report Cyber Crime'\n2. Select crime category\n3. Fill your details & describe the incident\n4. Upload evidence (screenshots/videos)\n5. Submit — you'll get a complaint ID\n\n🏛️ On this Portal: Click '📋 Report Incident' in the navbar\n\n📞 Cyber Crime: 1930 | Women: 1091 | Police: 100"),

        (["safe","protect","tips","advice","secure","password","2fa","privacy"],
         "🛡️ Cyber Safety Tips for Students:\n\n🔐 Passwords: Use unique passwords (12+ chars). Use Bitwarden (free).\n📱 2FA: Enable on all accounts — especially email & banking.\n🌐 Links: Never click unknown SMS/email links.\n💻 Updates: Keep OS & apps updated. Use antivirus.\n📵 Public WiFi: Avoid for banking or sensitive logins.\n🔒 Social Media: Keep profiles private.\n\n📞 If attacked: Call 1930 immediately"),

        (["helpline","number","contact","call","police","emergency","1930","where","whom"],
         "📞 Cybercrime Helplines (India):\n\n🚨 Cyber Crime: 1930\n👩 Women: 1091\n👶 Child: 1098\n🚔 Police: 100\n🚑 Ambulance: 108\n📱 iCall Student: 9152987821\n🌐 cybercrime.gov.in\n🔒 CERT-In: 1800-11-4949\n\n💡 Call 1930 immediately after fraud — faster reporting = better recovery chance."),

        (["thank","thanks","ok","okay","bye","goodbye","done","great"],
         "You're welcome! Stay safe online. 🛡️\n\nRemember:\n• Cyber Crime Helpline: 1930\n• Portal: cybercrime.gov.in\n\nI'm always here if you need help. Take care! 👋"),
    ]

    for keywords, reply in rules:
        if any(w in t for w in keywords):
            return jsonify({"reply": reply})

    # Crime analyzer fallback
    r = analyze_text(t)
    if r["crime"] != "Other Cyber Crime":
        return jsonify({"reply":
            f"🔍 Based on your message:\n\n🚨 Crime: {r['crime']}\n📂 Category: {r['category']}\n⚠️ Threat: {r['threat']}\n\n📌 Action: {r['action']}\n\n📞 Cyber Crime: 1930 | cybercrime.gov.in"
        })

    return jsonify({"reply":
        "🤖 I'm CyberBot — I specialize in cybercrime help.\n\nDescribe your issue and I'll guide you. I handle:\n• Phishing & bank fraud\n• Hacking & account security\n• Cyberbullying & harassment\n• UPI & payment fraud\n• Malware & ransomware\n• Identity theft\n• Filing complaints\n\n📞 Emergency: 1930"
    })

    # ── Intelligent fallback AI engine ──────────────────────────────────────
    t = msg.lower()

    def h(en, hi): return hi if hindi else en

    # Greetings
    if any(w in t for w in ["hello","hi","hey","namaste","namaskar","helo","start","help me","good morning","good evening","kaise","madad"]):
        return jsonify({"reply": h(
            "👋 Hello! I'm CyberBot — your AI cybercrime assistant.\n\nI can help you with:\n🔴 Phishing & bank fraud\n🔴 Hacking & account takeover\n🟠 Cyberbullying & harassment\n🔴 UPI / online payment fraud\n🔴 Ransomware & malware\n🔴 Identity theft & fake profiles\n\nDescribe your problem and I'll guide you step by step.\n\n📞 Emergency: Call 1930",
            "👋 Namaste! Main CyberBot hoon — aapka AI cyber crime sahayak.\n\nMain in vishyon mein madad kar sakta hoon:\n🔴 Phishing aur bank fraud\n🔴 Hacking aur account takeover\n🟠 Cyber bullying aur utpeedan\n🔴 UPI / online payment fraud\n🔴 Ransomware aur malware\n🔴 Identity theft\n\nApni samasya batayein, main step-by-step guide karunga.\n\n📞 Emergency: 1930 par call karein"
        )})

    # Phishing
    if any(w in t for w in ["phish","otp","bank","credential","fake link","fake email","fake call","verify account","account blocked","password stolen","click link","suspicious link","fake sms","fake message"]):
        return jsonify({"reply": h(
            "🎣 This sounds like a Phishing Attack!\n\nPhishing is when criminals impersonate banks, companies or government agencies to steal your credentials.\n\n✅ Immediate steps:\n1. Do NOT share OTP, PIN or password with anyone\n2. Block the sender/caller immediately\n3. Contact your bank helpline to freeze your account\n4. Change your passwords from a safe device\n5. File a complaint at cybercrime.gov.in\n\n⚠️ Remember: No bank, government or company ever asks for OTP over call or SMS.\n\n📞 Bank Fraud Helpline: 14440\n📞 Cyber Crime: 1930",
            "🎣 Yeh Phishing Attack lagta hai!\n\nPhishing mein criminals bank, company ya sarkar ka roop dharan karke aapki jaankari churate hain.\n\n✅ Turant karein:\n1. Kisi ko bhi OTP, PIN ya password share na karein\n2. Bhejne wale ko turant block karein\n3. Bank helpline par call karke account freeze karein\n4. Surakshit device se password badlein\n5. cybercrime.gov.in par shikayat darj karein\n\n⚠️ Yaad rakhein: Koi bhi bank kabhi OTP nahi mangta.\n\n📞 Bank Fraud: 14440\n📞 Cyber Crime: 1930"
        )})

    # UPI / Financial fraud
    if any(w in t for w in ["upi","paytm","gpay","phonepe","money","transfer","fraud","scam","payment","wallet","lottery","prize","refund","cashback","fake offer","investment","trading","crypto","bitcoin","paise","thagi","loot","nuksaan","rupee","rs ","₹"]):
        return jsonify({"reply": h(
            "💸 This looks like Online Financial Fraud!\n\nCommon types: UPI scams, fake lottery, investment fraud, fake cashback offers.\n\n✅ Immediate steps:\n1. Call your bank immediately to freeze the transaction\n2. File complaint at cybercrime.gov.in within 24 hours (faster recovery)\n3. Call helpline: 1930\n4. Save all screenshots, transaction IDs and chat records as evidence\n5. Do NOT transfer any more money — even if threatened\n\n💡 Tip: If you report within 1 hour, banks can often reverse the transaction.\n\n📞 Cyber Crime Helpline: 1930\n📞 Bank Fraud: 14440",
            "💸 Yeh Online Vittiya Dhokhadhadi lagti hai!\n\nSadharan prakar: UPI scam, nakli lottery, investment fraud, fake cashback.\n\n✅ Turant karein:\n1. Bank ko turant call karein aur transaction rokein\n2. 24 ghante ke andar cybercrime.gov.in par shikayat karein\n3. Helpline: 1930 par call karein\n4. Sabhi screenshots aur transaction ID surakshit rakhein\n5. Aur paise transfer na karein — chahe dhamki ho\n\n💡 Tip: 1 ghante ke andar report karne par bank transaction wapas kar sakta hai.\n\n📞 Cyber Crime: 1930\n📞 Bank Fraud: 14440"
        )})

    # Hacking
    if any(w in t for w in ["hack","hacked","unauthorized","breach","data leak","account taken","password changed","someone logged","unknown device","account access","my account","login alert"]):
        return jsonify({"reply": h(
            "🔓 This is Hacking / Unauthorized Account Access!\n\nSomeone has gained access to your account without permission.\n\n✅ Immediate steps:\n1. Change your password immediately from a different device\n2. Enable 2-Factor Authentication (2FA) on all accounts\n3. Check 'Active Sessions' and log out all unknown devices\n4. Check if your email is in a data breach: haveibeenpwned.com\n5. Report to CERT-In: cert-in.org.in\n6. File complaint at cybercrime.gov.in\n\n🔐 Use a strong password: mix of letters, numbers & symbols (min 12 chars)\n\n📞 Cyber Crime: 1930\n📞 CERT-In: 1800-11-4949",
            "🔓 Yeh Hacking / Anadhikrit Account Access hai!\n\nKisi ne aapki anumati ke bina aapke account mein pravesh kiya hai.\n\n✅ Turant karein:\n1. Dusre device se turant password badlein\n2. Sabhi accounts par 2FA chaluu karein\n3. 'Active Sessions' check karein aur anjaan devices logout karein\n4. CERT-In ko report karein: cert-in.org.in\n5. cybercrime.gov.in par shikayat darj karein\n\n🔐 Mazboot password: letters, numbers aur symbols ka mix (min 12 characters)\n\n📞 Cyber Crime: 1930\n📞 CERT-In: 1800-11-4949"
        )})

    # Cyberbullying / Harassment
    if any(w in t for w in ["bully","harass","abuse","stalk","blackmail","troll","insult","threat","intimidate","morphed","photo leak","video leak","sextortion","revenge porn","nude","intimate","screenshot","spread","defame","character"]):
        return jsonify({"reply": h(
            "😡 This is Cyberbullying / Online Harassment!\n\nThis is a serious crime under IT Act Section 66A and IPC.\n\n✅ Immediate steps:\n1. Do NOT respond to the bully — it encourages them\n2. Screenshot all messages, posts and profiles as evidence\n3. Block the person on all platforms immediately\n4. Report the profile to the platform (Instagram/WhatsApp/Facebook)\n5. File a police complaint at your nearest station\n6. For sextortion/morphed images: report immediately to cybercrime.gov.in\n\n💙 You are not alone. Talk to a trusted adult or counselor.\n\n📞 Cyber Crime: 1930\n📞 Women Helpline: 1091\n📞 iCall Student: 9152987821",
            "😡 Yeh Cyber Bullying / Online Utpeedan hai!\n\nYeh IT Act Section 66A aur IPC ke tahat gambhir apradh hai.\n\n✅ Turant karein:\n1. Bully ko jawab NA dein — isse unhe protsahan milta hai\n2. Sabhi messages, posts aur profiles ke screenshots lein\n3. Us vyakti ko sabhi platforms par block karein\n4. Platform par profile report karein\n5. Najdeeki police station mein shikayat darj karein\n6. Morphed images ke liye: cybercrime.gov.in par turant report karein\n\n💙 Aap akele nahi hain. Kisi vishwasniya vyakti se baat karein.\n\n📞 Cyber Crime: 1930\n📞 Mahila Helpline: 1091\n📞 iCall: 9152987821"
        )})

    # Malware / Ransomware
    if any(w in t for w in ["virus","malware","ransomware","trojan","spyware","infected","encrypt","files locked","pay ransom","slow computer","popup","adware","keylogger"]):
        return jsonify({"reply": h(
            "🦠 This is a Malware / Ransomware Attack!\n\nMalware can steal data, encrypt files, or spy on you.\n\n✅ Immediate steps:\n1. Disconnect from internet immediately (turn off WiFi/data)\n2. Do NOT pay any ransom — it doesn't guarantee file recovery\n3. Do NOT restart the computer (may trigger more encryption)\n4. Contact your college IT department or a cybersecurity expert\n5. Report to CERT-In: cert-in.org.in\n6. Restore files from backup if available\n\n🛡️ Prevention: Keep antivirus updated, never download from unknown sources\n\n📞 CERT-In: 1800-11-4949\n📞 Cyber Crime: 1930",
            "🦠 Yeh Malware / Ransomware Attack hai!\n\nMalware data chura sakta hai, files encrypt kar sakta hai ya aap par nazar rakh sakta hai.\n\n✅ Turant karein:\n1. Turant internet se disconnect karein\n2. Koi bhi fidya NA dein\n3. Computer restart NA karein\n4. College IT department ya cyber expert se sampark karein\n5. CERT-In ko report karein: cert-in.org.in\n6. Backup se files restore karein\n\n🛡️ Bachav: Antivirus update rakhein, anjaan sources se download na karein\n\n📞 CERT-In: 1800-11-4949\n📞 Cyber Crime: 1930"
        )})

    # Identity theft
    if any(w in t for w in ["identity","impersonate","fake profile","stolen identity","someone using my name","fake account","my photo","my name","pretend to be me","fake id"]):
        return jsonify({"reply": h(
            "🪪 This is Identity Theft / Impersonation!\n\nSomeone is using your identity, photos or name without permission.\n\n✅ Immediate steps:\n1. Report the fake profile to the platform immediately (use 'Report' button)\n2. Inform your friends and contacts about the fake account\n3. File complaint at cybercrime.gov.in\n4. File an FIR at your nearest police station\n5. Change passwords on all accounts linked to your identity\n6. Monitor your credit/bank accounts for suspicious activity\n\n📞 Cyber Crime: 1930\n📞 Police: 100",
            "🪪 Yeh Pahchan ki Chori / Naqli Profile hai!\n\nKoi aapki pahchan, photos ya naam ka bina anumati ke upyog kar raha hai.\n\n✅ Turant karein:\n1. Platform par naqli profile turant report karein\n2. Apne dosto aur contacts ko naqli account ke baare mein batayein\n3. cybercrime.gov.in par shikayat darj karein\n4. Najdeeki police station mein FIR darj karein\n5. Sabhi linked accounts ke passwords badlein\n\n📞 Cyber Crime: 1930\n📞 Police: 100"
        )})

    # How to file complaint
    if any(w in t for w in ["complaint","report","file","register","submit","how to","kaise","shikayat","darj","portal","cybercrime.gov"]):
        return jsonify({"reply": h(
            "📋 How to File a Cybercrime Complaint:\n\n🌐 Online (Recommended):\n1. Visit cybercrime.gov.in\n2. Click 'Report Cyber Crime'\n3. Select crime category\n4. Fill in your details and describe the incident\n5. Upload evidence (screenshots, videos)\n6. Submit — you'll get a complaint ID\n\n🏛️ On this Portal:\n1. Click '📋 Report Incident' in the navbar\n2. Fill the form with your details\n3. Describe the incident in detail\n4. Upload evidence\n5. Submit\n\n📞 Helplines:\n• Cyber Crime: 1930\n• Women: 1091\n• Police: 100",
            "📋 Cyber Crime Shikayat Kaise Darj Karein:\n\n🌐 Online (Anushansit):\n1. cybercrime.gov.in par jayein\n2. 'Report Cyber Crime' par click karein\n3. Apradh ki shreni chunein\n4. Apni jaankari bharein aur ghatna ka vivaran dein\n5. Saboot upload karein\n6. Submit karein — aapko shikayat ID milegi\n\n🏛️ Is Portal Par:\n1. Navbar mein '📋 Report Incident' par click karein\n2. Form mein apni jaankari bharein\n3. Ghatna ka vivaran dein\n4. Saboot upload karein\n5. Submit karein\n\n📞 Helplines:\n• Cyber Crime: 1930\n• Mahila: 1091\n• Police: 100"
        )})

    # Safety tips
    if any(w in t for w in ["safe","protect","prevent","tips","advice","secure","password","2fa","two factor","privacy","stay safe","bachao","suraksha"]):
        return jsonify({"reply": h(
            "🛡️ Top Cyber Safety Tips for Students:\n\n🔐 Passwords:\n• Use unique passwords for every account\n• Minimum 12 characters with letters, numbers & symbols\n• Use a password manager (Bitwarden is free)\n\n📱 Account Security:\n• Enable 2FA on all accounts (especially email & banking)\n• Never share OTP with anyone — ever\n\n🌐 Online Behaviour:\n• Never click links in unknown SMS/emails\n• Verify website URLs before entering credentials\n• Keep your social media profiles private\n\n💻 Device Security:\n• Keep OS and apps updated\n• Use antivirus software\n• Avoid public WiFi for banking\n\n📞 If attacked: Call 1930 immediately",
            "🛡️ Students ke liye Top Cyber Safety Tips:\n\n🔐 Passwords:\n• Har account ke liye alag password rakhein\n• Min 12 characters — letters, numbers aur symbols\n• Password manager use karein (Bitwarden free hai)\n\n📱 Account Security:\n• Sabhi accounts par 2FA chaluu karein\n• OTP kisi ke saath share na karein — kabhi bhi\n\n🌐 Online Behaviour:\n• Anjaan SMS/email ke links par click na karein\n• Credentials dalne se pehle website URL verify karein\n• Social media profiles private rakhein\n\n💻 Device Security:\n• OS aur apps update rakhein\n• Antivirus use karein\n• Banking ke liye public WiFi avoid karein\n\n📞 Attack hone par: 1930 par turant call karein"
        )})

    # Helplines
    if any(w in t for w in ["helpline","number","contact","call","police","emergency","1930","help","kahan","where","whom"]):
        return jsonify({"reply": h(
            "📞 Important Cybercrime Helplines (India):\n\n🚨 Cyber Crime Helpline: 1930\n👩 Women Helpline: 1091\n👶 Child Helpline: 1098\n🚔 Police: 100\n🚑 Ambulance: 108\n📱 iCall Student Helpline: 9152987821\n🌐 Online Portal: cybercrime.gov.in\n🔒 CERT-In: 1800-11-4949\n\n💡 Tip: Call 1930 immediately after any cyber fraud — the faster you report, the better the chance of recovering money.",
            "📞 Mahatvapurn Cyber Crime Helplines (India):\n\n🚨 Cyber Crime Helpline: 1930\n👩 Mahila Helpline: 1091\n👶 Bal Helpline: 1098\n🚔 Police: 100\n🚑 Ambulance: 108\n📱 iCall Student: 9152987821\n🌐 Online Portal: cybercrime.gov.in\n🔒 CERT-In: 1800-11-4949\n\n💡 Tip: Cyber fraud ke baad turant 1930 par call karein — jitni jaldi report karein, paise wapas milne ki utni zyada sambhavna."
        )})

    # Thanks / bye
    if any(w in t for w in ["thank","thanks","ok","okay","bye","goodbye","done","great","shukriya","dhanyawad","theek","acha","accha"]):
        return jsonify({"reply": h(
            "You're welcome! Stay safe online. 🛡️\n\nRemember:\n• Cyber Crime Helpline: 1930\n• Portal: cybercrime.gov.in\n\nI'm always here if you need help. Take care! 👋",
            "Aapka swagat hai! Online surakshit rahein. 🛡️\n\nYaad rakhein:\n• Cyber Crime Helpline: 1930\n• Portal: cybercrime.gov.in\n\nMain hamesha aapki madad ke liye yahan hoon. Dhyan rakhein! 👋"
        )})

    # Use crime analyzer for anything else
    r = analyze_text(t)
    if r["crime"] != "Other Cyber Crime":
        try:
            conn = get_db()
            p = ph_for(conn)
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO ai_analysis_logs(user_email,input_text,crime,category,threat,confidence,language,source) VALUES({p},{p},{p},{p},{p},{p},{p},{p})",
                (session.get("email","anonymous"), msg[:500], r["crime"], r["category"], r["threat"], r["confidence"], "hi" if hindi else "en", "chatbot")
            )
            conn.commit(); conn.close()
        except Exception: pass
        return jsonify({"reply": h(
            f"🔍 Based on your message, this appears to be:\n\n🚨 Crime Type: {r['crime']}\n📂 Category: {r['category']}\n⚠️ Threat Level: {r['threat']}\n✅ Confidence: {r['confidence']}\n\n📌 Recommended Action:\n{r['action']}\n\n📞 Cyber Crime Helpline: 1930\n🌐 cybercrime.gov.in",
            f"🔍 Aapke sandesh ke aadhar par yeh lagta hai:\n\n🚨 Apradh Prakar: {r['crime']}\n📂 Shreni: {r['category']}\n⚠️ Khatra Star: {r['threat']}\n✅ Vishwas: {r['confidence']}\n\n📌 Anushansit Kadam:\n{r['action']}\n\n📞 Cyber Crime Helpline: 1930\n🌐 cybercrime.gov.in"
        )})

    # Off-topic or unclear
    return jsonify({"reply": h(
        "🤖 I'm CyberBot — I specialize in cybercrime assistance.\n\nI can help you with:\n• Phishing & bank fraud\n• Hacking & account security\n• Cyberbullying & harassment\n• UPI & online payment fraud\n• Malware & ransomware\n• Identity theft\n• How to file a complaint\n• Cyber safety tips\n\nPlease describe your cybercrime issue and I'll guide you.\n\n📞 Emergency: 1930",
        "🤖 Main CyberBot hoon — main cyber crime mein visheshagya hoon.\n\nMain in vishyon mein madad kar sakta hoon:\n• Phishing aur bank fraud\n• Hacking aur account security\n• Cyber bullying aur utpeedan\n• UPI aur online payment fraud\n• Malware aur ransomware\n• Identity theft\n• Shikayat kaise darj karein\n• Cyber safety tips\n\nApni cyber crime samasya batayein.\n\n📞 Emergency: 1930"
    )})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
