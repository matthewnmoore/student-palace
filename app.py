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
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_DEBUG = os.environ.get("ADMIN_DEBUG", "0") == "1"

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
        "now": _dt.datetime.utcnow,
    }

# =========================
# DB helpers
# =========================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # ensure FK cascades (rooms -> houses)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
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

    # Admin-managed cities
    c.execute("""
    CREATE TABLE IF NOT EXISTS cities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1
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
      profile_views INTEGER NOT NULL DEFAULT 0
    );
    """)

    # Houses
    c.execute("""
    CREATE TABLE IF NOT EXISTS houses(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      landlord_id INTEGER NOT NULL,
      title TEXT NOT NULL,
      city TEXT NOT NULL,
      address TEXT NOT NULL,
      letting_type TEXT NOT NULL CHECK (letting_type IN ('whole','share')),
      bedrooms_total INTEGER NOT NULL,
      gender_preference TEXT NOT NULL CHECK (gender_preference IN ('Male','Female','Mixed','Either')),
      bills_included INTEGER NOT NULL DEFAULT 0,
      shared_bathrooms INTEGER NOT NULL DEFAULT 0,

      off_street_parking INTEGER NOT NULL DEFAULT 0,
      local_parking INTEGER NOT NULL DEFAULT 0,
      cctv INTEGER NOT NULL DEFAULT 0,
      video_door_entry INTEGER NOT NULL DEFAULT 0,
      bike_storage INTEGER NOT NULL DEFAULT 0,
      cleaning_service TEXT NOT NULL DEFAULT 'none',
      wifi INTEGER NOT NULL DEFAULT 1,
      wired_internet INTEGER NOT NULL DEFAULT 0,
      common_area_tv INTEGER NOT NULL DEFAULT 0,

      created_at TEXT NOT NULL,

      FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE
    );
    """)

    # NEW: Rooms (CRUD Step 1)
    c.execute("""
    CREATE TABLE IF NOT EXISTS rooms(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      house_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      ensuite INTEGER NOT NULL DEFAULT 0,

      -- non-searchable room info
      bed_size TEXT NOT NULL CHECK (bed_size IN ('Single','Small double','Double','King')),
      tv INTEGER NOT NULL DEFAULT 0,
      desk_chair INTEGER NOT NULL DEFAULT 0,
      wardrobe INTEGER NOT NULL DEFAULT 0,
      chest_drawers INTEGER NOT NULL DEFAULT 0,
      lockable_door INTEGER NOT NULL DEFAULT 0,
      wired_internet INTEGER NOT NULL DEFAULT 0,

      room_size TEXT, -- optional free text (e.g. "12.5 m²")

      created_at TEXT NOT NULL,

      FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
    );
    """)

    conn.commit()

    # --- Migrations for older DBs (safe, non-destructive) ---
    if not table_has_column(conn, "landlords", "created_at"):
        print("[MIGRATE] Adding landlords.created_at")
        conn.execute("ALTER TABLE landlords ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        conn.commit()
        now = dt.utcnow().isoformat()
        conn.execute("UPDATE landlords SET created_at=? WHERE created_at='' OR created_at IS NULL", (now,))
        conn.commit()

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

def get_active_cities_safe():
    try:
        conn = get_db()
        rows = conn.execute("SELECT name FROM cities WHERE is_active=1 ORDER BY name ASC").fetchall()
        conn.close()
        return [r["name"] for r in rows]
    except Exception as e:
        print("[WARN] get_active_cities_safe error:", e)
        return []

def validate_city_active(city):
    if not city:
        return False
    conn = get_db()
    row = conn.execute("SELECT 1 FROM cities WHERE name=? AND is_active=1", (city,)).fetchone()
    conn.close()
    return bool(row)

def clean_bool(field_name):
    return 1 if (request.form.get(field_name) == "on") else 0

def valid_choice(value, choices):
    return value in choices

def _owned_house_or_abort(conn, hid, landlord_id):
    """Fetch house ensuring ownership; returns row or None (with flash+redirect)."""
    h = conn.execute("SELECT * FROM houses WHERE id=? AND landlord_id=?", (hid, landlord_id)).fetchone()
    if not h:
        flash("House not found.", "error")
        return None
    return h

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
# Admin: Cities
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
                        conn.execute("INSERT INTO cities(name,is_active) VALUES(?,1)", (name,))
                        conn.commit()
                        flash(f"Added city: {name}", "ok")
                    except sqlite3.IntegrityError:
                        flash("That city already exists.", "error")
            elif action in ("activate","deactivate","delete"):
                try:
                    cid = int(request.form.get("city_id"))
                except Exception:
                    cid = 0
                if cid:
                    if action == "delete":
                        conn.execute("DELETE FROM cities WHERE id=?", (cid,))
                        conn.commit()
                        flash("City deleted.", "ok")
                    else:
                        new_val = 1 if action == "activate" else 0
                        conn.execute("UPDATE cities SET is_active=? WHERE id=?", (new_val, cid))
                        conn.commit()
                        flash("City updated.", "ok")
        rows = conn.execute("SELECT * FROM cities ORDER BY name ASC").fetchall()
        return render_template("admin_cities.html", cities=rows)
    finally:
        conn.close()

# =========================
# Admin: Landlords (view/edit/delete all)
# =========================
@app.route("/admin/landlords", methods=["GET"])
def admin_landlords():
    if not is_admin():
        return redirect(url_for("admin_login"))
    q = (request.args.get("q") or "").strip().lower()
    conn = get_db()
    try:
        if q:
            rows = conn.execute("""
                SELECT l.id, l.email, l.created_at,
                       COALESCE(p.display_name,'') AS display_name,
                       COALESCE(p.public_slug,'') AS public_slug,
                       COALESCE(p.profile_views,0) AS profile_views
                FROM landlords l
                LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
                WHERE LOWER(l.email) LIKE ? OR LOWER(COALESCE(p.display_name,'')) LIKE ?
                ORDER BY l.created_at DESC
            """, (f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = conn.execute("""
                SELECT l.id, l.email, l.created_at,
                       COALESCE(p.display_name,'') AS display_name,
                       COALESCE(p.public_slug,'') AS public_slug,
                       COALESCE(p.profile_views,0) AS profile_views
                FROM landlords l
                LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
                ORDER BY l.created_at DESC
            """).fetchall()
        return render_template("admin_landlords.html", landlords=rows, q=q)
    except Exception as e:
        print("[ERROR] admin_landlords:", e)
        if ADMIN_DEBUG:
            return f"admin_landlords error: {e}", 500
        raise
    finally:
        conn.close()

@app.route("/admin/landlord/<int:lid>", methods=["GET","POST"])
def admin_landlord_detail(lid):
    if not is_admin():
        return redirect(url_for("admin_login"))
    conn = get_db()
    try:
        if request.method == "POST":
            action = request.form.get("action") or ""
            if action == "update_email":
                new_email = (request.form.get("email") or "").strip().lower()
                if new_email:
                    try:
                        conn.execute("UPDATE landlords SET email=? WHERE id=?", (new_email, lid))
                        conn.commit()
                        flash("Email updated.", "ok")
                    except sqlite3.IntegrityError:
                        flash("That email is already taken.", "error")
            elif action == "reset_password":
                new_pw = (request.form.get("new_password") or "").strip()
                if not new_pw:
                    new_pw = secrets.token_urlsafe(8)
                    flash(f"Generated temporary password: {new_pw}", "ok")
                ph = generate_password_hash(new_pw)
                conn.execute("UPDATE landlords SET password_hash=? WHERE id=?", (ph, lid))
                conn.commit()
                flash("Password reset.", "ok")
            elif action == "update_profile":
                display_name = (request.form.get("display_name") or "").strip()
                phone = (request.form.get("phone") or "").strip()
                website = (request.form.get("website") or "").strip()
                bio = (request.form.get("bio") or "").strip()
                conn.execute("INSERT OR IGNORE INTO landlord_profiles(landlord_id) VALUES(?)", (lid,))
                prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
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
                flash("Profile updated.", "ok")
            elif action == "delete_landlord":
                conn.execute("DELETE FROM landlord_profiles WHERE landlord_id=?", (lid,))
                conn.execute("DELETE FROM landlords WHERE id=?", (lid,))
                conn.commit()
                flash("Landlord deleted.", "ok")
                return redirect(url_for("admin_landlords"))

        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        profile = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
        houses = conn.execute("SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)).fetchall()
        return render_template("admin_landlord_view.html",
                               landlord=landlord, profile=profile, houses=houses)
    except Exception as e:
        print("[ERROR] admin_landlord_detail:", e)
        if ADMIN_DEBUG:
            return f"admin_landlord_detail error: {e}", 500
        raise
    finally:
        conn.close()

# =========================
# Public: Home + Search (preview)
# =========================
@app.route("/")
def index():
    cities = get_active_cities_safe()
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
    cities = get_active_cities_safe()
    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",
    }
    return render_template("search.html", query=q, cities=cities)

# =========================
# Landlord entry page (navbar "Landlords" button)
# =========================
@app.route("/landlords")
def landlords_entry():
    return render_template("landlords_entry.html")

# =========================
# Landlord auth (signup/login/logout)
# =========================
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
    houses = conn.execute("SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)).fetchall()
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

# Public profile
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
# Phase 4: Houses CRUD (landlord)
# =========================
@app.route("/landlord/houses")
def landlord_houses():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    rows = conn.execute("SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)).fetchall()
    conn.close()
    return render_template("houses_list.html", houses=rows)

@app.route("/landlord/houses/new", methods=["GET","POST"])
def house_new():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    cities = get_active_cities_safe()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()
        bills_included = clean_bool("bills_included")
        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)

        off_street_parking = clean_bool("off_street_parking")
        local_parking = clean_bool("local_parking")
        cctv = clean_bool("cctv")
        video_door_entry = clean_bool("video_door_entry")
        bike_storage = clean_bool("bike_storage")
        cleaning_service = (request.form.get("cleaning_service") or "none").strip()
        wifi = 1 if request.form.get("wifi") is None else clean_bool("wifi")
        wired_internet = clean_bool("wired_internet")
        common_area_tv = clean_bool("common_area_tv")

        errors = []
        if not title: errors.append("Title is required.")
        if not address: errors.append("Address is required.")
        if bedrooms_total < 1: errors.append("Bedrooms must be at least 1.")
        if not validate_city_active(city): errors.append("Please choose a valid active city.")
        if not valid_choice(letting_type, ("whole","share")): errors.append("Invalid letting type.")
        if not valid_choice(gender_pref, ("Male","Female","Mixed","Either")): errors.append("Invalid gender preference.")
        if not valid_choice(cleaning_service, ("none","weekly","fortnightly","monthly")): errors.append("Invalid cleaning service value.")
        if errors:
            for e in errors: flash(e, "error")
            return render_template("house_form.html", cities=cities, form=request.form, mode="new")

        conn = get_db()
        conn.execute("""
          INSERT INTO houses(
            landlord_id,title,city,address,letting_type,bedrooms_total,gender_preference,bills_included,
            shared_bathrooms,off_street_parking,local_parking,cctv,video_door_entry,bike_storage,cleaning_service,
            wifi,wired_internet,common_area_tv,created_at
          ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            lid, title, city, address, letting_type, bedrooms_total, gender_pref, bills_included,
            shared_bathrooms, off_street_parking, local_parking, cctv, video_door_entry, bike_storage,
            cleaning_service, wifi, wired_internet, common_area_tv, dt.utcnow().isoformat()
        ))
        conn.commit()
        conn.close()
        flash("House added.", "ok")
        return redirect(url_for("landlord_houses"))

    # GET
    return render_template("house_form.html", cities=cities, form={}, mode="new")

@app.route("/landlord/houses/<int:hid>/edit", methods=["GET","POST"])
def house_edit(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    cities = get_active_cities_safe()
    conn = get_db()
    house = conn.execute("SELECT * FROM houses WHERE id=? AND landlord_id=?", (hid, lid)).fetchone()
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord_houses"))

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()
        bills_included = clean_bool("bills_included")
        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)

        off_street_parking = clean_bool("off_street_parking")
        local_parking = clean_bool("local_parking")
        cctv = clean_bool("cctv")
        video_door_entry = clean_bool("video_door_entry")
        bike_storage = clean_bool("bike_storage")
        cleaning_service = (request.form.get("cleaning_service") or "none").strip()
        wifi = 1 if request.form.get("wifi") is None else clean_bool("wifi")
        wired_internet = clean_bool("wired_internet")
        common_area_tv = clean_bool("common_area_tv")

        errors = []
        if not title: errors.append("Title is required.")
        if not address: errors.append("Address is required.")
        if bedrooms_total < 1: errors.append("Bedrooms must be at least 1.")
        if not validate_city_active(city): errors.append("Please choose a valid active city.")
        if not valid_choice(letting_type, ("whole","share")): errors.append("Invalid letting type.")
        if not valid_choice(gender_pref, ("Male","Female","Mixed","Either")): errors.append("Invalid gender preference.")
        if not valid_choice(cleaning_service, ("none","weekly","fortnightly","monthly")): errors.append("Invalid cleaning service value.")
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            return render_template("house_form.html", cities=cities, form=request.form, mode="edit", house=house)

        conn.execute("""
          UPDATE houses SET
            title=?, city=?, address=?, letting_type=?, bedrooms_total=?, gender_preference=?, bills_included=?,
            shared_bathrooms=?, off_street_parking=?, local_parking=?, cctv=?, video_door_entry=?, bike_storage=?,
            cleaning_service=?, wifi=?, wired_internet=?, common_area_tv=?
          WHERE id=? AND landlord_id=?
        """, (
            title, city, address, letting_type, bedrooms_total, gender_pref, bills_included,
            shared_bathrooms, off_street_parking, local_parking, cctv, video_door_entry, bike_storage,
            cleaning_service, wifi, wired_internet, common_area_tv, hid, lid
        ))
        conn.commit()
        conn.close()
        flash("House updated.", "ok")
        return redirect(url_for("landlord_houses"))

    # GET
    form = dict(house)
    conn.close()
    return render_template("house_form.html", cities=cities, form=form, mode="edit", house=house)

@app.route("/landlord/houses/<int:hid>/delete", methods=["POST"])
def house_delete(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    # safety: also delete rooms (if FK pragma off)
    conn.execute("DELETE FROM rooms WHERE house_id=(SELECT id FROM houses WHERE id=? AND landlord_id=?)", (hid, lid))
    conn.execute("DELETE FROM houses WHERE id=? AND landlord_id=?", (hid, lid))
    conn.commit()
    conn.close()
    flash("House deleted.", "ok")
    return redirect(url_for("landlord_houses"))

# =========================
# Rooms CRUD (NEW)
# =========================
def _room_form_values():
    """Extract & validate room form values. Returns (values_dict, errors_list)."""
    name = (request.form.get("name") or "").strip()
    ensuite = clean_bool("ensuite")
    bed_size = (request.form.get("bed_size") or "").strip()
    tv = clean_bool("tv")
    desk_chair = clean_bool("desk_chair")
    wardrobe = clean_bool("wardrobe")
    chest_drawers = clean_bool("chest_drawers")
    lockable_door = clean_bool("lockable_door")
    wired_internet = clean_bool("wired_internet")
    room_size = (request.form.get("room_size") or "").strip()  # optional

    errors = []
    if not name:
        errors.append("Room name is required.")
    if bed_size not in ("Single","Small double","Double","King"):
        errors.append("Please choose a valid bed size.")

    vals = dict(
        name=name, ensuite=ensuite, bed_size=bed_size, tv=tv,
        desk_chair=desk_chair, wardrobe=wardrobe, chest_drawers=chest_drawers,
        lockable_door=lockable_door, wired_internet=wired_internet,
        room_size=room_size
    )
    return vals, errors

@app.route("/landlord/houses/<int:hid>/rooms")
def rooms_list(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = _owned_house_or_abort(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord_houses"))
    rows = conn.execute("SELECT * FROM rooms WHERE house_id=? ORDER BY id ASC", (hid,)).fetchall()
    conn.close()
    return render_template("rooms_list.html", house=house, rooms=rows)

@app.route("/landlord/houses/<int:hid>/rooms/new", methods=["GET","POST"])
def room_new(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = _owned_house_or_abort(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord_houses"))

    if request.method == "POST":
        vals, errors = _room_form_values()
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="new")
        conn.execute("""
          INSERT INTO rooms(house_id,name,ensuite,bed_size,tv,desk_chair,wardrobe,chest_drawers,lockable_door,wired_internet,room_size,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            hid, vals["name"], vals["ensuite"], vals["bed_size"], vals["tv"],
            vals["desk_chair"], vals["wardrobe"], vals["chest_drawers"],
            vals["lockable_door"], vals["wired_internet"], vals["room_size"],
            dt.utcnow().isoformat()
        ))
        conn.commit()
        conn.close()
        flash("Room added.", "ok")
        return redirect(url_for("rooms_list", hid=hid))

    # GET
    conn.close()
    return render_template("room_form.html", house=house, form={}, mode="new")

@app.route("/landlord/houses/<int:hid>/rooms/<int:rid>/edit", methods=["GET","POST"])
def room_edit(hid, rid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = _owned_house_or_abort(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord_houses"))
    room = conn.execute("SELECT * FROM rooms WHERE id=? AND house_id=?", (rid, hid)).fetchone()
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("rooms_list", hid=hid))

    if request.method == "POST":
        vals, errors = _room_form_values()
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="edit", room=room)
        conn.execute("""
          UPDATE rooms SET
            name=?, ensuite=?, bed_size=?, tv=?, desk_chair=?, wardrobe=?, chest_drawers=?, lockable_door=?, wired_internet=?, room_size=?
          WHERE id=? AND house_id=?
        """, (
            vals["name"], vals["ensuite"], vals["bed_size"], vals["tv"], vals["desk_chair"],
            vals["wardrobe"], vals["chest_drawers"], vals["lockable_door"], vals["wired_internet"],
            vals["room_size"], rid, hid
        ))
        conn.commit()
        conn.close()
        flash("Room updated.", "ok")
        return redirect(url_for("rooms_list", hid=hid))

    # GET
    form = dict(room)
    conn.close()
    return render_template("room_form.html", house=house, form=form, mode="edit", room=room)

@app.route("/landlord/houses/<int:hid>/rooms/<int:rid>/delete", methods=["POST"])
def room_delete(hid, rid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = _owned_house_or_abort(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord_houses"))
    conn.execute("DELETE FROM rooms WHERE id=? AND house_id=?", (rid, hid))
    conn.commit()
    conn.close()
    flash("Room deleted.", "ok")
    return redirect(url_for("rooms_list", hid=hid))

# =========================
# Public property page (minimal placeholder)
# =========================
@app.route("/p/<int:hid>")
def property_public(hid):
    conn = get_db()
    h = conn.execute("SELECT * FROM houses WHERE id=?", (hid,)).fetchone()
    # NOTE: We are not surfacing rooms here yet — that comes in Step 5.
    conn.close()
    if not h:
        return render_template("property.html", house=None), 404
    return render_template("property.html", house=h)

# =========================
# Errors (JSON for .json endpoints)
# =========================
@app.errorhandler(404)
def not_found(e):
    path = request.path or ""
    if path.endswith(".json"):
        return jsonify({"error": "not found", "path": path}), 404
    cities = get_active_cities_safe()
    return render_template("search.html", query={"error": "Page not found"}, cities=cities), 404

@app.errorhandler(500)
def server_error(e):
    print("[ERROR] 500:", e)
    path = request.path or ""
    if path.endswith(".json"):
        return jsonify({"error": "server error", "detail": str(e)}), 500
    if ADMIN_DEBUG:
        return f"Internal Server Error: {e}", 500
    cities = get_active_cities_safe()
    return render_template("search.html", query={"error": "Something went wrong"}, cities=cities), 500

# =========================
# Main
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
