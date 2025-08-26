import os
import sqlite3
import secrets
import datetime
from datetime import datetime as dt
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

# =========================
# Config (Render-friendly)
# =========================
DB_PATH = os.environ.get("DB_PATH", "/opt/uploads/student_palace.db")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/opt/uploads")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")  # set in Render → Environment
ADMIN_DEBUG = os.environ.get("ADMIN_DEBUG", "0") == "1"  # set to 1 to show verbose errors

# Ensure dirs exist even if a persistent disk is mounted
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# Version string (used for cache-busting + footer badge)
BUILD_VERSION = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

# Make BUILD_VERSION and a 'now()' helper available in templates
@app.context_processor
def inject_globals():
    import datetime as _dt
    return {
        "BUILD_VERSION": BUILD_VERSION,
        "now": _dt.datetime.utcnow,   # usage: {{ now().year }}
    }

# =========================
# DB helpers
# =========================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def table_has_column(conn, table, column):
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = [r["name"] for r in cur.fetchall()]
        return column in cols
    except Exception as e:
        print(f"[WARN] PRAGMA table_info({table}) failed:", e)
        return False

def ensure_db():
    conn = get_db()
    c = conn.cursor()

    # Admin-managed cities (with ordering via 'position')
    c.execute("""
    CREATE TABLE IF NOT EXISTS cities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      position INTEGER NOT NULL DEFAULT 1000
    );
    """)

    # Landlords
    c.execute("""
    CREATE TABLE IF NOT EXISTS landlords(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    """)

    # Landlord profile (1–1)
    c.execute("""
    CREATE TABLE IF NOT EXISTS landlord_profiles(
      landlord_id INTEGER PRIMARY KEY,
      display_name TEXT,
      phone TEXT,
      website TEXT,
      bio TEXT,
      public_slug TEXT UNIQUE,
      profile_views INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE
    );
    """)

    # (Houses table will come later in Step 4; we keep Step 1-3 minimal)

    conn.commit()

    # --- Migrations for older DBs ---
    if not table_has_column(conn, "cities", "position"):
        print("[MIGRATE] Adding cities.position")
        try:
            conn.execute("ALTER TABLE cities ADD COLUMN position INTEGER NOT NULL DEFAULT 1000")
            conn.commit()
        except Exception as e:
            print("[WARN] MIGRATE cities.position:", e)

    if not table_has_column(conn, "landlords", "created_at"):
        print("[MIGRATE] Adding landlords.created_at")
        try:
            conn.execute("ALTER TABLE landlords ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            conn.commit()
            now = dt.utcnow().isoformat()
            conn.execute("UPDATE landlords SET created_at=? WHERE created_at='' OR created_at IS NULL", (now,))
            conn.commit()
        except Exception as e:
            print("[WARN] MIGRATE landlords.created_at:", e)

    conn.close()

ensure_db()

# =========================
# Utils
# =========================
def is_admin():
    return bool(session.get("is_admin"))

def current_landlord_id():
    return session.get("landlord_id")

def require_landlord():
    if not current_landlord_id():
        flash("Please log in to continue.", "error")
        return redirect(url_for("login"))
    return None

def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out).strip("-")
    return slug or "landlord"

def get_active_cities():
    conn = get_db()
    rows = conn.execute("SELECT name FROM cities WHERE is_active=1 ORDER BY position ASC, name ASC").fetchall()
    conn.close()
    return [r["name"] for r in rows]

def next_city_position(conn):
    row = conn.execute("SELECT COALESCE(MAX(position), 999) AS m FROM cities").fetchone()
    return (row["m"] or 999) + 1

# =========================
# Health / diagnostics
# =========================
@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/diag")
def diag():
    return jsonify({
        "db_path": DB_PATH,
        "upload_folder": UPLOAD_FOLDER,
        "db_exists": os.path.exists(DB_PATH),
        "upload_exists": os.path.isdir(UPLOAD_FOLDER),
        "env_ok": bool(SECRET_KEY),
        "is_admin": bool(session.get("is_admin")),
        "landlord_id": current_landlord_id(),
        "build": BUILD_VERSION,
        "admin_debug": ADMIN_DEBUG,
    }), 200

@app.route("/routes")
def routes():
    rules = []
    for r in app.url_map.iter_rules():
        rules.append({
            "rule": str(r),
            "endpoint": r.endpoint,
            "methods": sorted(list(r.methods))
        })
    return jsonify(sorted(rules, key=lambda x: x["rule"]))

@app.route("/admin/ping")
def admin_ping():
    if not is_admin():
        return "not-admin", 403
    return "admin-ok", 200

# =========================
# Admin auth
# =========================
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    try:
        if request.method == "POST":
            token = (request.form.get("token") or "").strip()
            if ADMIN_TOKEN and token == ADMIN_TOKEN:
                session["is_admin"] = True
                flash("Admin session started.", "ok")
                return redirect(url_for("admin_cities"))
            flash("Invalid admin token.", "error")
        return render_template("admin_login.html")
    except Exception as e:
        print("[ERROR] admin_login:", e)
        flash("Admin login error.", "error")
        return redirect(url_for("index"))

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "ok")
    return redirect(url_for("index"))

# =========================
# Admin: Cities (with ordering)
# =========================
@app.route("/admin/cities", methods=["GET","POST"])
def admin_cities():
    if not is_admin():
        return redirect(url_for("admin_login"))
    conn = get_db()
    try:
        if request.method == "POST":
            action = request.form.get("action") or ""
            if action == "add":
                name = (request.form.get("name") or "").strip()
                if name:
                    try:
                        pos = next_city_position(conn)
                        conn.execute("INSERT INTO cities(name,is_active,position) VALUES(?,1,?)", (name, pos))
                        conn.commit()
                        flash(f"Added city: {name}", "ok")
                    except sqlite3.IntegrityError:
                        flash("That city already exists.", "error")
            elif action in ("activate","deactivate","delete","move_up","move_down"):
                try:
                    cid = int(request.form.get("city_id"))
                except Exception:
                    cid = 0
                if cid:
                    if action == "delete":
                        conn.execute("DELETE FROM cities WHERE id=?", (cid,))
                        conn.commit()
                        flash("City deleted.", "ok")
                    elif action in ("activate","deactivate"):
                        new_val = 1 if action == "activate" else 0
                        conn.execute("UPDATE cities SET is_active=? WHERE id=?", (new_val, cid))
                        conn.commit()
                        flash("City updated.", "ok")
                    else:
                        # move_up / move_down: swap position with neighbor
                        cur = conn.execute("SELECT id, position FROM cities WHERE id=?", (cid,)).fetchone()
                        if cur:
                            if action == "move_up":
                                neighbor = conn.execute("""
                                  SELECT id, position FROM cities
                                  WHERE position < ?
                                  ORDER BY position DESC LIMIT 1
                                """, (cur["position"],)).fetchone()
                            else:
                                neighbor = conn.execute("""
                                  SELECT id, position FROM cities
                                  WHERE position > ?
                                  ORDER BY position ASC LIMIT 1
                                """, (cur["position"],)).fetchone()
                            if neighbor:
                                conn.execute("UPDATE cities SET position=? WHERE id=?", (neighbor["position"], cur["id"]))
                                conn.execute("UPDATE cities SET position=? WHERE id=?", (cur["position"], neighbor["id"]))
                                conn.commit()
        rows = conn.execute("SELECT * FROM cities ORDER BY position ASC, name ASC").fetchall()
        return render_template("admin_cities.html", cities=rows)
    finally:
        conn.close()

# =========================
# Admin: Landlords (stub pages, to be expanded later)
# =========================
@app.route("/admin/landlords")
def admin_landlords():
    if not is_admin():
        return redirect(url_for("admin_login"))
    conn = get_db()
    rows = conn.execute("""
        SELECT l.id, l.email, l.created_at,
               COALESCE(p.display_name,'') AS display_name,
               COALESCE(p.public_slug,'') AS public_slug,
               COALESCE(p.profile_views,0) AS profile_views
        FROM landlords l
        LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
        ORDER BY l.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("admin_landlords.html", landlords=rows, q="")

@app.route("/admin/landlord/<int:lid>", methods=["GET","POST"])
def admin_landlord_detail(lid):
    if not is_admin():
        return redirect(url_for("admin_login"))
    conn = get_db()
    landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
    profile = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
    houses = []  # populated in Step 4
    conn.close()
    return render_template("admin_landlord_view.html", landlord=landlord, profile=profile, houses=houses)

# =========================
# Public: Home + Search (preview)
# =========================
@app.route("/")
def index():
    cities = get_active_cities()
    featured = {
        "title": "Spacious 5-bed student house",
        "city": cities[0] if cities else "Leeds",
        "price_pppw": 135,
        "badges": ["Bills included", "Close to campus", "Wi-Fi"],
        "image": "",
        "link": "#"
    }
    return render_template("index.html", cities=cities, featured=featured)

@app.route("/search")
def search():
    cities = get_active_cities()
    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",
    }
    return render_template("search.html", query=q, cities=cities)

# =========================
# Landlord entry + auth
# =========================
@app.route("/landlords")
def landlords_entry():
    return render_template("landlords_entry.html")

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        try:
            email = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "")
            if not email or not password:
                flash("Email and password are required.", "error")
                return render_template("signup.html")
            if "@" not in email or "." not in email.split("@")[-1]:
                flash("Please enter a valid email address.", "error")
                return render_template("signup.html")
            if len(password) < 6:
                flash("Password must be at least 6 characters long.", "error")
                return render_template("signup.html")

            conn = get_db()
            exists = conn.execute("SELECT id FROM landlords WHERE email=?", (email,)).fetchone()
            if exists:
                flash("That email is already registered. Try logging in.", "error")
                conn.close()
                return render_template("signup.html")

            ph = generate_password_hash(password)
            conn.execute(
                "INSERT INTO landlords(email, password_hash, created_at) VALUES (?,?,?)",
                (email, ph, dt.utcnow().isoformat()),
            )
            conn.commit()
            row = conn.execute("SELECT id FROM landlords WHERE email=?", (email,)).fetchone()
            lid = row["id"]
            conn.execute(
                "INSERT OR IGNORE INTO landlord_profiles(landlord_id, display_name, public_slug) VALUES (?,?,?)",
                (lid, email.split("@")[0], None)
            )
            conn.commit()
            conn.close()

            session["landlord_id"] = lid
            flash("Welcome! Your landlord account is ready.", "ok")
            return redirect(url_for("dashboard"))

        except Exception as e:
            print("[ERROR] signup:", e)
            flash("Sign up failed. Please try again.", "error")
            return render_template("signup.html")

    return render_template("signup.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        try:
            email = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "")
            if not email or not password:
                flash("Email and password are required.", "error")
                return render_template("login.html")

            conn = get_db()
            row = conn.execute("SELECT * FROM landlords WHERE email=?", (email,)).fetchone()
            conn.close()
            if not row or not check_password_hash(row["password_hash"], password):
                flash("Invalid email or password.", "error")
                return render_template("login.html")

            session["landlord_id"] = row["id"]
            flash("Logged in.", "ok")
            return redirect(url_for("dashboard"))

        except Exception as e:
            print("[ERROR] login:", e)
            flash("Login failed. Please try again.", "error")
            return render_template("login.html")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "ok")
    return redirect(url_for("index"))

# =========================
# Landlord dashboard + profile
# =========================
@app.route("/dashboard")
def dashboard():
    lid = current_landlord_id()
    if not lid:
        return render_template("dashboard.html", landlord=None, profile=None)

    conn = get_db()
    landlord = conn.execute("SELECT id,email,created_at FROM landlords WHERE id=?", (lid,)).fetchone()
    profile = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
    houses = []  # Step 4
    conn.close()
    return render_template("dashboard.html", landlord=landlord, profile=profile, houses=houses)

@app.route("/landlord/profile", methods=["GET","POST"])
def landlord_profile():
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
    if not prof:
        conn.execute("INSERT INTO landlord_profiles(landlord_id, display_name) VALUES (?,?)", (lid, ""))
        conn.commit()
        prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()

    if request.method == "POST":
        try:
            display_name = (request.form.get("display_name") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            website = (request.form.get("website") or "").strip()
            bio = (request.form.get("bio") or "").strip()
            slug = prof["public_slug"]
            if not slug and display_name:
                base = slugify(display_name)
                candidate = base
                i = 2
                while conn.execute("SELECT 1 FROM landlord_profiles WHERE public_slug=?", (candidate,)).fetchone():
                    candidate = f"{base}-{i}"
                    i += 1
                slug = candidate
            conn.execute("""
                UPDATE landlord_profiles
                SET display_name=?, phone=?, website=?, bio=?, public_slug=COALESCE(?, public_slug)
                WHERE landlord_id=?
            """, (display_name, phone, website, bio, slug, lid))
            conn.commit()
            prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
            conn.close()
            flash("Profile saved.", "ok")
            return redirect(url_for("landlord_profile"))
        except Exception as e:
            conn.close()
            print("[ERROR] landlord_profile POST:", e)
            flash("Could not save profile.", "error")
            return redirect(url_for("landlord_profile"))

    conn.close()
    return render_template("landlord_profile_edit.html", profile=prof)

@app.route("/l/<slug>")
def landlord_public_by_slug(slug):
    conn = get_db()
    prof = conn.execute("SELECT * FROM landlord_profiles WHERE public_slug=?", (slug,)).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute("UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?", (prof["landlord_id"],))
    conn.commit()
    ll = conn.execute("SELECT email FROM landlords WHERE id=?", (prof["landlord_id"],)).fetchone()
    conn.close()
    return render_template("landlord_profile_public.html", profile=prof, contact_email=ll["email"] if ll else "")

@app.route("/l/id/<int:lid>")
def landlord_public_by_id(lid):
    conn = get_db()
    prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute("UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?", (lid,))
    conn.commit()
    ll = conn.execute("SELECT email FROM landlords WHERE id=?", (lid,)).fetchone()
    conn.close()
    return render_template("landlord_profile_public.html", profile=prof, contact_email=ll["email"] if ll else "")

# =========================
# Errors
# =========================
@app.errorhandler(404)
def not_found(e):
    path = request.path or ""
    if path.endswith(".json"):
        return jsonify({"error": "not found", "path": path}), 404
    cities = get_active_cities()
    return render_template("search.html", query={"error": "Page not found"}, cities=cities), 404

@app.errorhandler(500)
def server_error(e):
    print("[ERROR] 500:", e)
    path = request.path or ""
    if path.endswith(".json"):
        return jsonify({"error": "server error", "detail": str(e)}), 500
    if ADMIN_DEBUG:
        return f"Internal Server Error: {e}", 500
    cities = get_active_cities()
    return render_template("search.html", query={"error": "Something went wrong"}, cities=cities), 500

# =========================
# Main
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
