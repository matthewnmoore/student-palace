=================================================================
Student Palace – Internal Reference File
=================================================================
FILE: DB_Schema_& Rules_READ_ME.txt
PURPOSE:
    - Permanent reference for database schema, photo upload rules,
      image processing (resize + watermark), and known pitfalls.
    - This file is NOT code, but critical documentation.
    - It should live in the repo at all times.
    - DO NOT delete, rename, or overwrite without explicit backup.

USAGE:
    - Read-only reference for developers and admins.
    - Copy/paste snippets as needed (SQL, schema checks, etc).
    - Keep updated ONLY when schema or image processing logic changes.

HISTORY:
    - Created during initial build of landlord photo upload feature.
    - Updated as of: <<INSERT DATE HERE>>
=================================================================





updated 31-08-2025
==================

UPDATE 2025-08-31 — Address Preview & EPC

Address model (authoritative)
	•	Single source of truth: houses.address (one-line string).
	•	Address parts (flat_number, house_name, house_number, street_name, address_extra, postcode) exist only in the form UI to build a preview.
Do NOT store these parts in the DB.
	•	What is saved: the hidden form field address (the preview line) only.

Normalisation rules (server + client)
	•	Capitalisation: Non-postcode parts are light title-cased (handles spaces, hyphens, apostrophes).
Examples:
o'connor house → O'Connor House
north-east road → North-East Road
	•	Postcode: Uppercased, ensure final 3 characters separated by a space if missing.
Example: sw1a1aa → SW1A 1AA
	•	City/Town: City is admin-controlled and trusted; the Town input in the form mirrors City (read-only).

Form behaviour (safety)
	•	On Edit, if a saved address exists, the UI displays it as-is and will not recompute from parts unless the user edits the parts (tracked by a partsDirty flag).
	•	On New, or if no saved address, the preview composes from parts.
	•	On submit, the hidden address is updated only if parts were edited; otherwise the saved value passes through unchanged.

Validation
	•	houses.address is required (must be non-empty after normalisation).

EPC rating (Phase 1)
	•	Column: houses.epc_rating (TEXT, nullable/empty allowed) with allowed bands: A|B|C|D|E|F|G.
	•	Form: <select name="epc_rating"> with options A–G and blank (optional).
	•	Validation: If provided, must be one of A–G; otherwise store empty string.

Migrations (add-only)
	•	Ensure _safe_add_column(houses, "ADD COLUMN epc_rating TEXT NOT NULL DEFAULT ''").
(If you already applied this, no action required.)

Testing checklist (addresses & EPC)
	•	New House: enter parts → preview shows one-line → Save → revisit Edit → preview shows saved line unchanged.
	•	Edit House (no edits): Save → address persists exactly.
	•	Edit House (change parts): preview updates → Save → DB shows new one-line.
	•	Postcode formats to AA9 9AA shape where applicable.
	•	EPC select enforces A–G when chosen; blank allowed.

Known gotcha (fixed)
	•	Symptom: Saved addresses “disappeared” on Edit.
	•	Cause: JS recomposed from empty parts on load and overwrote hidden address.
	•	Fix: Guard with partsDirty and only recompute when user edits parts; always prefer existing saved address on load.

Restore points
	•	Added: checkpoint-address-preview-sorted-2025-08-31 (UI + server aligned; preview guarded; EPC field live).






THIS IS THE LATEST UPDATE PROVIDED BY CHATGPT 31/08/2025
========================================================


ADD: Frontend Style Conventions (canonical class names)
	•	Accent edges (purple on both sides): use card--accent-edges
• Old aliases sometimes seen: card--accent-lr → prefer card--accent-edges
	•	Thickness variable: --accent-border (CSS), default 3px
	•	Cards always: .card + .card--accent-edges when you want accent
	•	Search button sizing helper (homepage): .btn-wide-ish (wider than default)
	•	Centering helpers used on homepage:
• hero-centered (center text)
• Search form wrapper constrained at ~820px; button centered and conditionally shown by JS

ADD: Homepage Search – UX Rules (authoritative)

Required dropdowns (button stays hidden until all are chosen):
	•	City (select[name="city"], data-required)
	•	Group size (select[name="group_size"], data-required)
	•	Academic year (select[name="academic_year"], data-required)
	•	A house that identifies as (select[name="gender_pref"], values: Male/Female/Anything)

Conditional dropdown:
	•	“Can I politely ask…” (select[name="seeker_gender"] with values Male/Female/NA)
• Shown when gender_pref has a value.
• Required once shown.

Optional checkboxes (do not gate button):
	•	Ensuite / own bathroom
	•	All bills included

Button behavior:
	•	#find_btn is hidden until all data-required selects have values.
	•	Button sits centered between the two optional checkboxes.

ADD: House Bills – Detailed Utilities (DB + form names)

DB columns (INTEGER 0/1):
	•	bills_util_gas
	•	bills_util_electric
	•	bills_util_water
	•	bills_util_broadband
	•	bills_util_tv

Form input names (checkboxes):
	•	bills_util_gas
	•	bills_util_electric
	•	bills_util_water
	•	bills_util_broadband
	•	bills_util_tv

Authoritative rule:
	•	If bills_option = 'yes' → set all five utilities to 1 (checked)
	•	If bills_option = 'no' → set all five utilities to 0 (unchecked)
	•	If bills_option = 'some' → respect individual checkboxes

Legacy sync rule:
	•	bills_included (legacy boolean) mirrors only the YES case:
• bills_included = 1 iff bills_option == ‘yes’
• Otherwise 0

ADD: Landlord House Form – Field Map (names you see in HTML)
	•	air_conditioning (form) → air_con (DB)
	•	bills_included (form: ‘yes’|‘no’|‘some’) → bills_option (DB text)
	•	listing_type (form: ‘owner’|‘agent’) → listing_type (DB text)
	•	cleaning_service (form: ‘none’|‘weekly’|‘fortnightly’|‘monthly’) → same in DB
	•	Checkbox booleans map 1/0:
washing_machine, tumble_dryer, dishwasher, cooker, microwave, coffee_maker, central_heating, vacuum,
wifi, wired_internet, common_area_tv, cctv, video_door_entry, fob_entry, off_street_parking, local_parking,
garden, roof_terrace, bike_storage, games_room, cinema_room

ADD: Refactor Notes (routes split + ownership)
	•	landlord/houses.py now focuses on routes only.
	•	landlord/house_form.py:
• get_default_listing_type(conn, landlord_id, existing=None)
• parse_house_form(form, mode, default_listing_type) → returns (payload, errors)
	•	landlord/house_repo.py:
• insert_house(conn, landlord_id, payload)
• update_house(conn, landlord_id, house_id, payload)
	•	Ownership checks use utils.owned_house_or_none(conn, hid, lid) (unchanged behavior).

ADD: Env Vars (authoritative set)
	•	DB_PATH=/opt/render/project/src/static/uploads/houses/student_palace.db
	•	ADMIN_TOKEN= (required for /debug/db-backup)
	•	Optional (future address API):
• UK_POSTCODES_API_KEY= (if using a paid service; not needed for open postcodes.io)
• ADDRESS_LOOKUP_PROVIDER=postcodes_io|getaddress|ideal_postcodes (TBD)

ADD: Debug Endpoints (temporary)
	•	GET /debug/db → shows active DB path, size, table counts, sample rows
	•	GET /debug/db-candidates → lists *.db files under project with size/mtime
	•	GET /debug/db-scan → opens each *.db and reports key table counts
	•	POST /debug/db-backup?token=ADMIN_TOKEN → creates timestamped snapshot under uploads/backups/
Notes: remove or protect behind stricter auth when stable.

ADD: Photo Stack – Code Freeze (Do-Not-Touch)
	•	Confirmed perfect (uploads, drag & drop, watermarking).
	•	Files locked (no changes unless agreed):
• image_helpers.py
• landlord/photos.py
• templates/house_photos.html
• templates/photos_room.html
• DB table: house_images (indices + NOT NULLs)
• Static pathing: relative under static/uploads/houses/
	•	Future room photos: replicate pipeline; DO NOT modify house photo code.

ADD: DNS/SSL Final State Target (quick crib)
	•	Apex A: student-palace.co.uk → 216.24.57.1 (only)
	•	WWW CNAME: www → student-palace.onrender.com (resolves to 216.24.57.251/7)
	•	No residual 62.233.121.5 anywhere.
	•	SSL: valid padlock at both https://student-palace.co.uk and https://www.student-palace.co.uk (Render-managed cert).

ADD: Testing Checklist (quick, practical)
	•	Landlord:
[ ] Login/logout
[ ] Houses list loads
[ ] Add house (all validations)
[ ] Edit house (bills yes/no/some flow incl. utilities)
[ ] Photos: upload ≤5, drag order, watermark visible, primary image set
	•	Public:
[ ] Homepage: purple accents visible on all three cards
[ ] Search form: button shows only when required selects chosen
[ ] “Can I politely ask…” shows after gender_pref picked, is required
[ ] City grid renders with active cities (or placeholder tile)
	•	Admin:
[ ] Cities CRUD
[ ] Landlords view
[ ] Images admin list
[ ] Stats dashboard loads
	•	Ops:
[ ] /debug/db shows correct DB_PATH and non-zero counts
[ ] /debug/db-backup creates a snapshot

ADD: Future Enhancements (logged but not active yet)
	•	Address auto-complete by postcode (UK):
• On “Add/Edit House”: user enters postcode → fetch address list → dropdown to fill address.
• Candidate provider: postcodes.io (free), or paid (GetAddress/Ideal Postcodes) if we need UDPRN/UMPRN or SLA.
• DB impact: none (still a single “address” field); we only assist with form filling.
	•	Public House Detail:
• Minor layout tweaks only; backend complete.
	•	Room Photos:
• Implement same house photo pipeline and UI for rooms (separate table or reuse with type flag if desired later).

ADD: Repo Structure (current snapshot – concise)

admin/
init.py
auth.py
backups.py
cities.py
images.py
landlords.py
stats.py

landlord/
init.py
dashboard.py
helpers.py
house_form.py        new helper
house_repo.py        new helper
houses.py            refactored routes
photos.py
profile.py
rooms.py

static/
css/style.css
img/student-palace-logo.*
uploads/houses/

templates/
(admin, landlord, student HTML templates)

DB_Schema_& Rules_READ_ME.txt
app.py
db.py
utils.py

ADD: Versioning / Restore Points (labels you can use)
	•	baseline-stable-2025-08-31
	•	landlord-forms-split-2025-08-31
	•	photos-stack-locked-2025-08-30
Tip: when you take /debug/db-backup, note the label alongside the timestamp.

ADD: Known Gotchas (quick reminders)
	•	Don’t prefix file_path with “/”; keep it relative (e.g., uploads/houses/img.jpg).
	•	When reading images: COALESCE(filename, file_name) to survive legacy rows.
	•	Checkbox booleans: HTML “on” → truthy; always normalize via clean_bool.
	•	Gender fields:
• House field: gender_preference (Male|Female|Mixed|Either)
• Public search “identifies as”: (Male|Female|Anything) → separate, do not mix with house DB field
• Seeker gender: seeker_gender (Male|Female|NA) used for search refinement only (not stored in DB).

⸻














STYLE GUIDELINE – Cards, Rounded Corners & Purple Accent
=========================================================


- Page layout uses multiple small "cards" (white boxes) rather than one long panel.
- Each card:
  • background: #fff
  • subtle shadow (var(--shadow))
  • rounded corners (var(--radius), currently 8px)
  • 1px neutral border (var(--border))

- Accent edges:
  • Use `card--accent-edges` to add a purple accent on BOTH left and right sides.
  • Thickness is controlled by CSS variable: `--accent-edge-width` (currently 3px).
  • Accent color: `var(--brand)` (Student Palace purple).

- When to accent:
  • Hero/intro on landing pages.
  • Key callouts (e.g., verification, warnings, success summaries).
  • Top-most card on important dashboard/editor pages.

- Consistency:
  • Keep form pages split into logical sections (Basics, Bathrooms, Amenities, Actions).
  • Avoid stacking >3–4 dense sections in a single card.
  • Prefer readability and breathing room over dense layouts.









REFERENCE: Database – Persistence, Safety & Ops (Render)
========================================================

Status: Authoritative as of <>

Absolute rule
	•	The production database file is never recreated or dropped by application code.
	•	All schema changes are non-destructive (add-only).

DB location (Render)
	•	Env var (must be set): DB_PATH=/opt/render/project/src/uploads/student_palace.db
	•	This lives on the persistent disk and survives deploys/rollbacks.

Connection/SQLite runtime settings

Applied on every connection:
	•	PRAGMA foreign_keys = ON
	•	PRAGMA journal_mode = WAL  (crash-safe write-ahead logging)
	•	PRAGMA synchronous = FULL  (maximum durability)
	•	PRAGMA busy_timeout = 15000  (15s)
	•	(Nice-to-have) PRAGMA temp_store = MEMORY, PRAGMA mmap_size = 268435456

Schema creation & migrations (non-destructive)
	•	On boot, the app calls ensure_db() which:
	•	Creates core tables if missing.
	•	Never drops or truncates anything.
	•	Uses add-only ALTER TABLE … ADD COLUMN guards (via _safe_add_column).
	•	For house_images, keeps file_name and filename in sync when one was missing.

Backups (on-disk snapshots)
	•	Protected endpoint: POST /debug/db-backup?token=<ADMIN_TOKEN>
	•	Env var required: ADMIN_TOKEN=
	•	Creates /opt/render/project/src/uploads/backups/student_palace.YYYYMMDD-HHMMSS.sqlite
	•	Keeps last 20 snapshots; older ones pruned automatically.
	•	Suggested cadence: before deploys, schema changes, or data imports.

Quick examples:
	•	curl -X POST “https://www.student-palace.co.uk/debug/db-backup?token=REDACTED”
	•	To download a backup from Render shell: ls -lh uploads/backups/

(Optional) We can add a “restore from backup” admin task later; for now restore is a manual copy: stop app → copy snapshot to uploads/student_palace.db → start app.

Debug/verification routes (temporary; remove when not needed)
	•	GET /debug/db
Shows: active DB path (env + SQLite), file size/mtime, table counts, latest 5 houses.
	•	GET /debug/db-candidates
Lists every *.db under /opt/render/project/src with size/mtime.
	•	GET /debug/db-scan
Opens each *.db, reports row counts for key tables, tiny sample of houses.

Post-deploy verification checklist
	1.	Hit /debug/db and confirm:
	•	db_path_env == /opt/render/project/src/uploads/student_palace.db
	•	db_path_sqlite matches the same file
	•	Table counts look correct (non-zero in prod once data exists)
	2.	Optional: Trigger /debug/db-backup and confirm snapshot created.

Operational “Do / Don’t”

Do
	•	Always set/keep DB_PATH pointing at /opt/render/project/src/uploads/student_palace.db.
	•	Take a backup (/debug/db-backup) before risky changes.
	•	Treat migrations as add-only; add columns/indices—don’t drop/rename in place.

Don’t
	•	Don’t commit a student_palace.db file into the repo for production.
	•	Don’t point DB_PATH at a repo-tracked path (e.g., project root).
	•	Don’t remove WAL files manually; SQLite manages them.

Troubleshooting quick checks
	•	Wrong DB in use? /debug/db paths don’t match → fix Render env DB_PATH, redeploy.
	•	“Missing data” after deploy? Check /debug/db-candidates and /debug/db-scan to locate the largest/most recent DB; ensure DB_PATH targets that file.
	•	Locked DB errors under load? WAL + busy_timeout=15000 are already set; investigate long-running writes.









REFERENCE: Student Palace – House Images DB Schema & Rules
=========================================================

Table: house_images
-------------------
Columns (from PRAGMA table_info):
- id (INTEGER, PK, AUTOINCREMENT)
- house_id (INTEGER, NOT NULL)  
  → Foreign key reference to houses.id

- file_name (TEXT, NOT NULL)  
  → Legacy column, MUST be set (duplicate of filename)

- filename (TEXT, NOT NULL)  
  → Newer column, MUST also be set (duplicate of file_name)

- file_path (TEXT, NOT NULL)  
  → Relative path under /static, e.g. "uploads/houses/abc.jpg"  
  → DO NOT prefix with "/" (Flask’s url_for('static', …) will break)

- width (INTEGER, NOT NULL)  
  → Image pixel width, e.g. 1920

- height (INTEGER, NOT NULL)  
  → Image pixel height, e.g. 1080

- bytes (INTEGER, NOT NULL)  
  → File size in bytes, e.g. 245367

- is_primary (INTEGER, NOT NULL, DEFAULT 0)  
  → Exactly one image per house should have is_primary=1  
  → Used for thumbnails / cover photo  
  → If none exists, fall back to first by sort_order

- sort_order (INTEGER, NOT NULL, DEFAULT 0)  
  → Controls gallery order  
  → Default 0, increment when inserting multiple images

- created_at (TEXT, NOT NULL)  
  → ISO 8601 string, e.g. "2025-08-28T16:14:33"

Schema Meta
-----------
- Currently NO schema_meta table in DB  
- Recommended if schema changes later:  
  key = 'house_images_version', val = 'v1'

Insert Rules
------------
When saving an uploaded image, populate ALL required fields:

file_name      = "<uuid>.jpg"  
filename       = "<uuid>.jpg"  
file_path      = "uploads/houses/<uuid>.jpg"  
width          = measured width  
height         = measured height  
bytes          = file size in bytes  
is_primary     = 1 if first image for house, else 0  
sort_order     = (next available number for this house)  
created_at     = ISO timestamp at insert

⚠️ If you omit ANY of these → SQLite will raise “NOT NULL constraint failed”.  
⚠️ Especially critical: file_name, filename, file_path, width, height, bytes.

Reading Rules
-------------
- Always use:
    COALESCE(filename, file_name) AS fname
  → Protects against environments where only one is populated.

- Full path in HTML:
    url_for("static", filename=file_path)

- Ensure file_path does NOT start with "/"  
  (Otherwise `url_for` doubles the slash → broken URLs)

Known Pitfalls
--------------
❌ Environments diverged: some had file_name only, others had filename only  
❌ file_path added later caused insert errors when code didn’t supply it  
❌ width/height/bytes are required → cannot be NULL  
❌ Confusion between filename vs file_name broke SELECT queries  
❌ Storing file_path with leading "/" broke Flask static serving

Best Practices
--------------
✅ Always fill BOTH file_name and filename with same value  
✅ Ensure exactly ONE image per house has is_primary=1  
✅ Use sort_order gaps (+10) for flexibility in reordering  
✅ Store relative paths (uploads/houses/abc.jpg)  
✅ Verify dimensions + bytes at upload before DB insert  
✅ Wrap DB insert in try/except + rollback on failure  
✅ Document any schema change in this file and bump version

Future Ideas
------------
- Add schema_meta for version tracking  
- Add is_deleted (soft delete) instead of removing rows  
- Add caption/alt_text for accessibility and SEO  
- Add landlord_id reference for faster ownership checks  
- Add file_hash (e.g., SHA256) to prevent duplicate uploads

SQL Snippets
------------
Create Table (current state):
CREATE TABLE house_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    bytes INTEGER NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    filename TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

Insert Example (Python DB-API style):
conn.execute("""
INSERT INTO house_images
(house_id, file_name, filename, file_path, width, height, bytes,
 is_primary, sort_order, created_at)
VALUES (?,?,?,?,?,?,?,?,?,?)
""", (
    hid, "abc123.jpg", "abc123.jpg", "uploads/houses/abc123.jpg",
    1920, 1080, 245367, 1, 0, dt.utcnow().isoformat()
))

Select Example (safe for legacy fields):
SELECT id,
       COALESCE(filename, file_name) AS fname,
       file_path, width, height, bytes,
       is_primary, sort_order, created_at
FROM house_images
WHERE house_id=?
ORDER BY is_primary DESC, sort_order ASC, id ASC;

Debugging
---------
- Check schema live: /debug/hi-schema
- Validate NOT NULL rules before deploying inserts
- Compare schema across dev/prod to avoid mismatches




REFERENCE: Student Palace – Photo Upload & Logo Watermark
=========================================================

Processing Rules
----------------
- All uploaded images are:
  → Opened safely (auto EXIF rotation applied)
  → Converted to RGB (to avoid PNG/alpha bugs)
  → Resized so the longest side = 1600px max
  → Saved as JPEG at ~85 quality (progressive, optimized)
  → Branded with "Student Palace" watermark

Watermark Details
-----------------
- Text: "Student Palace"
- Font: scalable (TTF if available, fallback to PIL default)
- Size: ~image width / 16 (scales with photo size)
- Position: bottom-right corner
- Style: semi-transparent white text with a soft black shadow
- Ensures readability on both light and dark images

DB Consistency
--------------
- width, height, bytes → measured *after* resize/watermark
- file_name + filename → same UUID-based name (".jpg")
- file_path → "uploads/houses/<uuid>.jpg" (no leading slash)

Limits
------
- Max 5 photos per house
- Max 5 MB per photo (pre-resize)
- Allowed formats: JPEG, PNG, WebP, GIF

Best Practices
--------------
✅ Never bypass process_image → ensures watermark + resize  
✅ Store only relative paths → Flask’s static serving works  
✅ Use select_images() → protects against filename vs file_name mismatch  
✅ Always commit/rollback → prevents half-saved files  

Debugging
---------
- Check processed output: download file directly from static/uploads/houses  
- Watermark should always be visible bottom-right at ~6–8% image width  
- /debug/hi-schema still validates DB side




-- Verify stored sizes match actual files
SELECT id, filename, width, height, bytes
FROM house_images
WHERE house_id=123;

-- Then cross-check against:
!ls -lh static/uploads/houses/house123_*.jpg






=========================================================
REFERENCE: Domain & DNS – student-palace.co.uk (Render)
=========================================================

Authoritative target (Render):
- Root (apex) A record:   @  ->  216.24.57.1
- WWW host CNAME:         www ->  student-palace.onrender.com

Why two records:
- Apex/root cannot be a CNAME at most DNS hosts; use the A record to Render.
- The www host can be a CNAME and should point to Render’s hostname.

Propagation & what to expect:
- DNS changes can take up to ~24 hours (rarely 48) to fully propagate worldwide.
- During propagation you may see MIXED answers when checking from different locations:
  * Old Easyspace IP: 62.233.121.5  (stale cache; old redirect)
  * Correct Render A (root): 216.24.57.1
  * Correct Render LB IPs for www (behind the CNAME): 216.24.57.251 or 216.24.57.7 (varies)
- Cloudflare “Error 1001: DNS resolution error” can appear temporarily while CNAMEs settle.

How to verify (simple checklist):
1) Check the root (apex) record:
   - Query student-palace.co.uk (A)
   - EXPECT: 216.24.57.1 ONLY (no 62.233.121.5 anywhere)
2) Check the www host:
   - Query www.student-palace.co.uk (CNAME/A)
   - EXPECT: CNAME to student-palace.onrender.com, resolving to 216.24.57.251 / 216.24.57.7 (Render)
3) Browser tests:
   - Visit https://www.student-palace.co.uk → should load the live site with a valid padlock (SSL).
   - Visit https://student-palace.co.uk → should also work; if desired, configure Render to redirect root → www.

Render dashboard “Verify” buttons:
- Use them after you’ve created the DNS records. If verification fails immediately, wait and retry after propagation (1–24h).
- Once verified, Render auto-provisions the TLS certificate. If the cert still says “pending,” give it more time.

TTL guidance (at the DNS host):
- Use the lowest available TTL when making changes (e.g., 300–3600 seconds). If the lowest offered is 1 hour, that’s fine.

If things still look wrong after 24 hours:
- Re-check records:
  * A @  ->  216.24.57.1 (exact match)
  * CNAME www -> student-palace.onrender.com (spelling matters; no trailing dot issues on most UIs)
- Remove any legacy/extra records that conflict (old A/CNAME/URL-forwarding at either apex or www).
- Flush local DNS cache if needed (OS/browser), but global propagation is the main factor.

Notes / sanity checks:
- “URL/Web Redirect” services at the registrar should be DISABLED; we want pure DNS to Render.
- Mixed answers on whatsmydns.net during the first hours are normal. Final state = only Render answers.
- After propagation & cert issuance, both apex and www should serve over HTTPS without warnings.




House Amenities – Display Grouping (UI order)

Bills
	•	bills_option (yes / no / some)
	•	(legacy: bills_included → derived: 1 if bills_option='yes' else 0)

Cleaning
	•	cleaning_service (none / weekly / fortnightly / monthly)

Kitchen / Utilities
	•	washing_machine (default ✔)
	•	tumble_dryer
	•	dishwasher
	•	cooker (default ✔)
	•	microwave
	•	coffee_maker

Heating / Comfort
	•	central_heating (default ✔)
	•	air_con
	•	vacuum

Connectivity / Media
	•	wifi (default ✔)
	•	wired_internet
	•	common_area_tv

Security / Access
	•	cctv
	•	video_door_entry
	•	fob_entry

Parking / Outdoors
	•	off_street_parking
	•	local_parking
	•	garden
	•	roof_terrace
	•	bike_storage

Shared Facilities
	•	games_room
	•	cinema_room










THESE FIELDS HAVE BEEN ADDED LATER AND WE THINK ARE CORRECT BUT PLEASE CHECK YOURSELF

Tables & Columns (authoritative list)

cities
	•	id (PK)
	•	name (TEXT, UNIQUE, NOT NULL)
	•	is_active (INTEGER, NOT NULL, default 1)

landlords
	•	id (PK)
	•	email (TEXT, UNIQUE, NOT NULL)
	•	password_hash (TEXT, NOT NULL)
	•	created_at (TEXT, NOT NULL)

landlord_profiles
	•	landlord_id (PK, FK → landlords.id)
	•	display_name (TEXT)
	•	phone (TEXT)
	•	website (TEXT)
	•	bio (TEXT)
	•	public_slug (TEXT, UNIQUE)
	•	profile_views (INTEGER, NOT NULL, default 0)
	•	is_verified (INTEGER, NOT NULL, default 0)  ← added earlier
	•	role (TEXT, NOT NULL, default 'owner', allowed: 'owner'|'agent')  ← added earlier

houses
	•	id (PK)
	•	landlord_id (FK → landlords.id)
	•	title (TEXT, NOT NULL)
	•	city (TEXT, NOT NULL)
	•	address (TEXT, NOT NULL)
	•	letting_type (TEXT, NOT NULL, 'whole'|'share')
	•	bedrooms_total (INTEGER, NOT NULL)
	•	gender_preference (TEXT, NOT NULL, 'Male'|'Female'|'Mixed'|'Either')
	•	bills_included (INTEGER, NOT NULL, default 0) — legacy yes/no flag
	•	shared_bathrooms (INTEGER, NOT NULL, default 0)
	•	off_street_parking (INTEGER, NOT NULL, default 0)
	•	local_parking (INTEGER, NOT NULL, default 0)
	•	cctv (INTEGER, NOT NULL, default 0)
	•	video_door_entry (INTEGER, NOT NULL, default 0)
	•	bike_storage (INTEGER, NOT NULL, default 0)
	•	cleaning_service (TEXT, NOT NULL, default 'none', allowed: 'none'|'weekly'|'fortnightly'|'monthly')
	•	wifi (INTEGER, NOT NULL, default 1)
	•	wired_internet (INTEGER, NOT NULL, default 0)
	•	common_area_tv (INTEGER, NOT NULL, default 0)
	•	created_at (TEXT, NOT NULL)
	•	listing_type (TEXT, NOT NULL, default 'owner', allowed: 'owner'|'agent')  ← added earlier

Houses — new fields (Phase 2)
	•	bills_option (TEXT, NOT NULL, default 'no', allowed: 'yes'|'no'|'some')  ← new
	•	washing_machine (INTEGER, NOT NULL, default 1)  ← new
	•	tumble_dryer (INTEGER, NOT NULL, default 0)  ← new
	•	dishwasher (INTEGER, NOT NULL, default 0)  ← new
	•	cooker (INTEGER, NOT NULL, default 1)  ← new
	•	microwave (INTEGER, NOT NULL, default 0)  ← new
	•	coffee_maker (INTEGER, NOT NULL, default 0)  ← new
	•	central_heating (INTEGER, NOT NULL, default 1)  ← new
	•	air_con (INTEGER, NOT NULL, default 0)  ← new
	•	vacuum (INTEGER, NOT NULL, default 0)  ← new
	•	fob_entry (INTEGER, NOT NULL, default 0)  ← new
	•	garden (INTEGER, NOT NULL, default 0)  ← new
	•	roof_terrace (INTEGER, NOT NULL, default 0)  ← new
	•	games_room (INTEGER, NOT NULL, default 0)  ← new
	•	cinema_room (INTEGER, NOT NULL, default 0)  ← new

Note: we keep bills_included (legacy boolean) in sync with bills_option (yes ⇒ 1, no/some ⇒ 0).

rooms
	•	id (PK)
	•	house_id (FK → houses.id)
	•	name (TEXT, NOT NULL)
	•	ensuite (INTEGER, NOT NULL, default 0)
	•	bed_size (TEXT, NOT NULL, 'Single'|'Small double'|'Double'|'King')
	•	tv (INTEGER, NOT NULL, default 0)
	•	desk_chair (INTEGER, NOT NULL, default 0)
	•	wardrobe (INTEGER, NOT NULL, default 0)
	•	chest_drawers (INTEGER, NOT NULL, default 0)
	•	lockable_door (INTEGER, NOT NULL, default 0)
	•	wired_internet (INTEGER, NOT NULL, default 0)
	•	room_size (TEXT, nullable)
	•	created_at (TEXT, NOT NULL)

house_images
	•	id (PK)
	•	house_id (FK → houses.id)
	•	file_name (TEXT, NOT NULL) — legacy duplicate
	•	filename (TEXT, NOT NULL) — canonical duplicate
	•	file_path (TEXT, NOT NULL) — relative path under static/ (e.g. uploads/houses/abc.jpg)
	•	width (INTEGER, NOT NULL)
	•	height (INTEGER, NOT NULL)
	•	bytes (INTEGER, NOT NULL)
	•	is_primary (INTEGER, NOT NULL, default 0)
	•	sort_order (INTEGER, NOT NULL, default 0)
	•	created_at (TEXT, NOT NULL)

⸻

Form ↔ DB name mapping (gotchas)
	•	Bills included (dropdown)
	•	Form field: bills_included with values 'yes'|'no'|'some'
	•	DB:
	•	bills_option ← stores 'yes'|'no'|'some' (authoritative)
	•	bills_included ← kept in sync as 1 if 'yes' else 0 (legacy)
	•	Air conditioning
	•	Form field: air_conditioning
	•	DB column: air_con
	•	Cleaning service
	•	Form field: cleaning_service ('none'|'weekly'|'fortnightly'|'monthly')
	•	DB column: cleaning_service (same values)
	•	Listing type
	•	Form field: listing_type ('owner'|'agent')
	•	DB column: listing_type
	•	Boolean checkboxes (all map 1/0 in DB):
	•	washing_machine, tumble_dryer, dishwasher, cooker, microwave, coffee_maker,
	•	central_heating, air_conditioning→air_con, vacuum,
	•	wifi, wired_internet, common_area_tv,
	•	cctv, video_door_entry, fob_entry,
	•	off_street_parking, local_parking, garden, roof_terrace,
	•	bike_storage, games_room, cinema_room.

⸻

Defaults (authoritative)
	•	bills_option: 'no' (and bills_included → 0)
	•	Checked by default (1): washing_machine, cooker, central_heating, wifi
	•	Unchecked by default (0): all other amenities listed above
	•	cleaning_service: 'none'
	•	listing_type: 'owner'
	•	Existing pre-Phase fields keep their original defaults (see tables above).




Progress
=========



Stable files (do-not-touch unless we agree)
	•	db.py — schema + add-only migrations (bills model, amenities).
	•	landlord/houses.py — add/edit flows, validations, DB writes.
	•	templates/house_form.html — new layout, bills dropdown + utilities panel, amenity defaults.
	•	utils.py — helpers used by the house form routes.

Photo stack — do not edit/change

Everything here is confirmed working (uploads, drag-and-drop ordering, watermarking):
	•	image_helpers.py (processing: resize + watermark)
	•	landlord/photos.py (routes/logic)
	•	templates/house_photos.html (house photo UI)
	•	templates/photos_room.html (room photo UI)
	•	DB table: house_images (including indices & NOT NULL rules)
	•	Static pathing: static/uploads/houses/… (relative paths only)

Notes for future work
	•	When we add room photos, we’ll replicate the same photo pipeline and UI patterns rather than changing the existing house photo code.
	•	Public house detail page is ready for layout tweaks only (the backend fields are all in place).














