import sqlite3
import os
import html
import datetime
from flask import Flask, jsonify, render_template, request, send_from_directory, session, render_template_string
from werkzeug.utils import secure_filename

from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

# Resend — outbound transactional email (admin order notifications, etc.).
# The package is listed in requirements.txt; the API key below is the literal
# placeholder from the Resend dashboard and is swapped for the real key at
# deploy time. Every resend.Emails.send() call site in this file is wrapped in
# its own try/except, so a bad key or a Resend outage can never crash a route.
import resend
resend.api_key = "re_3FTMQJJT_5Hib8mBXrygHA528XZcFMiJ8"

# Load local environment variables from .env when python-dotenv is available.
# Deployments normally inject the same values through the platform dashboard, so
# the import is optional and never blocks startup.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = Flask(__name__, template_folder='.')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'pack-sip-development-secret')
CORS(app)
# Trust the X-Forwarded-Proto/Host headers of the hosting reverse proxy so that
# request.host_url (used by the canonical URL, the Open Graph URL and the XML
# sitemap) reports the public https:// address on free hosts such as Render or
# PythonAnywhere instead of the internal http://127.0.0.1 address.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# The SQLite file lives NEXT TO this script and is resolved to an absolute
# path, so every process (dev server, gunicorn/uwsgi, VS Code debugger, or a
# re-deploy started from a different working directory) opens the SAME app.db.
# A relative path would silently create a fresh, default-seeded database
# whenever the working directory changed — wiping real stock counts.
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.db')
MICROWAVABLE_PRICE_PER_BOX = 1500.0

# Uploaded payment proofs (GCash screenshots from the Order Confirmation Modal
# and the /upload-receipt page) are written to an absolute `uploads/` folder
# next to this script. Keeping it absolute means every process — dev server,
# gunicorn/uwsgi, or a re-deploy started from another working directory — writes
# to the SAME place. The relative path recorded in orders.gcash_proof is
# `uploads/<filename>`, which the generic serve_static route can hand back.
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Only real image files are accepted as payment proof.
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.heic', '.heif'}

# ---------------------------------------------------------------------------
# Lalamove local courier shipping (origin: Taguig City).
#
# The delivery fee is a flat destination base rate (what a Lalamove booking
# costs from our Taguig warehouse to the customer's area) PLUS a per-box item
# surcharge for the boxes that consume rider space:
#
#   Base rates by destination                 Item surcharges (cups + lids only)
#     Taguig City                     P60       Cups: 5 + (cup_boxes - 1) * 2
#     Neighboring Cities              P90       Lids: 3 + (lid_boxes - 1) * 2
#       (Makati, Pasig, Pateros)
#     Rest of Metro Manila           P150
#     Nearby Provinces               P280
#       (Rizal, Cavite, Laguna, Bulacan)
#     Outer Provincial               P450
#
#   Total Shipping Fee = Base Location Rate + Cup Surcharge + Lid Surcharge.
#
# Microwavables are EXCLUDED from both the base-rate zone and the surcharges
# (they are billed through the subtotal only).
# The FULL applicable fee is always charged upfront, even for 50% downpayment:
#   Initial Amount Due = (Subtotal * 0.50) + Full Shipping Fee.
# ---------------------------------------------------------------------------
LALAMOVE_ORIGIN = 'Taguig'
LALAMOVE_DELIVERY_LABEL = 'Lalamove Delivery (Local Courier Rates)'
LALAMOVE_DELIVERY_NOTE = (
    'Estimated shipping rate calculated based on your location from Taguig '
    '+ box quantity.'
)
LALAMOVE_SHIPPING_LABEL = 'Lalamove'
# Zone ids are the stable keys spoken by the storefront <select>, the calculate
# API and the orders table; the labels stay presentational only.
LALAMOVE_ZONE_TAGUIG = 'taguig_city'
LALAMOVE_ZONE_NEIGHBORING = 'neighboring_cities'
LALAMOVE_ZONE_METRO_MANILA = 'metro_manila'
LALAMOVE_ZONE_NEARBY_PROVINCES = 'nearby_provinces'
LALAMOVE_ZONE_OUTER_PROVINCIAL = 'outer_provincial'
LALAMOVE_DEFAULT_ZONE = LALAMOVE_ZONE_TAGUIG
# Each zone carries the destination base rate AND the dynamic payment
# reservation window (in minutes) shown on the storefront, the Confirm Order
# modal and checkout summary:
#   Taguig City                      30 minutes
#   Nearby NCR cities                1 hour
#   Provincial (nearby + outer)      2 hours or more
LALAMOVE_ZONE_OPTIONS = [
    {'id': LALAMOVE_ZONE_TAGUIG, 'label': 'Taguig City', 'short': 'Taguig City', 'rate': 60.0,
     'reservation_minutes': 30},
    {
        'id': LALAMOVE_ZONE_NEIGHBORING,
        'label': 'Neighboring Cities (Makati, Pasig, Pateros)',
        'short': 'Neighboring Cities',
        'rate': 90.0,
        'reservation_minutes': 60,
    },
    {
        'id': LALAMOVE_ZONE_METRO_MANILA,
        'label': 'Rest of Metro Manila',
        'short': 'Rest of Metro Manila',
        'rate': 150.0,
        'reservation_minutes': 60,
    },
    {
        'id': LALAMOVE_ZONE_NEARBY_PROVINCES,
        'label': 'Nearby Provinces (Rizal, Cavite, Laguna, Bulacan)',
        'short': 'Nearby Provinces',
        'rate': 280.0,
        'reservation_minutes': 120,
    },
    {
        'id': LALAMOVE_ZONE_OUTER_PROVINCIAL,
        'label': 'Outer Provincial',
        'short': 'Outer Provincial',
        'rate': 450.0,
        'reservation_minutes': 180,
    },
]
LALAMOVE_ZONE_RATES = {zone['id']: zone['rate'] for zone in LALAMOVE_ZONE_OPTIONS}
LALAMOVE_ZONE_LABELS = {zone['id']: zone['label'] for zone in LALAMOVE_ZONE_OPTIONS}
# Compact labels used in fee/summary lines (e.g. 'Lalamove (Neighboring Cities)').
LALAMOVE_ZONE_SHORT_LABELS = {zone['id']: zone['short'] for zone in LALAMOVE_ZONE_OPTIONS}
# Dynamic payment reservation window per destination zone, in minutes.
LALAMOVE_ZONE_RESERVATION_MINUTES = {
    zone['id']: zone.get('reservation_minutes', 60) for zone in LALAMOVE_ZONE_OPTIONS
}
# Free-text city/area fallbacks so a typed location still lands in the right
# zone (legacy orders stored the address only, without a zone id).
LALAMOVE_ZONE_ALIASES = {
    'taguig': LALAMOVE_ZONE_TAGUIG,
    LALAMOVE_ZONE_TAGUIG: LALAMOVE_ZONE_TAGUIG,
    'makati': LALAMOVE_ZONE_NEIGHBORING,
    'pasig': LALAMOVE_ZONE_NEIGHBORING,
    'pateros': LALAMOVE_ZONE_NEIGHBORING,
    'neighboring': LALAMOVE_ZONE_NEIGHBORING,
    LALAMOVE_ZONE_NEIGHBORING: LALAMOVE_ZONE_NEIGHBORING,
    'manila': LALAMOVE_ZONE_METRO_MANILA,
    'metro_manila': LALAMOVE_ZONE_METRO_MANILA,
    'ncr': LALAMOVE_ZONE_METRO_MANILA,
    'caloocan': LALAMOVE_ZONE_METRO_MANILA,
    'las_pinas': LALAMOVE_ZONE_METRO_MANILA,
    'malabon': LALAMOVE_ZONE_METRO_MANILA,
    'mandaluyong': LALAMOVE_ZONE_METRO_MANILA,
    'marikina': LALAMOVE_ZONE_METRO_MANILA,
    'muntinlupa': LALAMOVE_ZONE_METRO_MANILA,
    'navotas': LALAMOVE_ZONE_METRO_MANILA,
    'paranaque': LALAMOVE_ZONE_METRO_MANILA,
    'pasay': LALAMOVE_ZONE_METRO_MANILA,
    'quezon_city': LALAMOVE_ZONE_METRO_MANILA,
    'san_juan': LALAMOVE_ZONE_METRO_MANILA,
    'valenzuela': LALAMOVE_ZONE_METRO_MANILA,
    LALAMOVE_ZONE_METRO_MANILA: LALAMOVE_ZONE_METRO_MANILA,
    'rizal': LALAMOVE_ZONE_NEARBY_PROVINCES,
    'antipolo': LALAMOVE_ZONE_NEARBY_PROVINCES,
    'cainta': LALAMOVE_ZONE_NEARBY_PROVINCES,
    'cavite': LALAMOVE_ZONE_NEARBY_PROVINCES,
    'laguna': LALAMOVE_ZONE_NEARBY_PROVINCES,
    'bulacan': LALAMOVE_ZONE_NEARBY_PROVINCES,
    LALAMOVE_ZONE_NEARBY_PROVINCES: LALAMOVE_ZONE_NEARBY_PROVINCES,
    'provincial': LALAMOVE_ZONE_OUTER_PROVINCIAL,
    'outer': LALAMOVE_ZONE_OUTER_PROVINCIAL,
    LALAMOVE_ZONE_OUTER_PROVINCIAL: LALAMOVE_ZONE_OUTER_PROVINCIAL,
}
# Per-box item surcharges: the first box rides at a fixed rate, every
# succeeding box adds P2 (cups: 5 + (n-1) * 2, lids: 3 + (n-1) * 2).
CUP_BOX_SURCHARGE_FIRST = 5.0
CUP_BOX_SURCHARGE_ADDITIONAL = 2.0
LID_BOX_SURCHARGE_FIRST = 3.0
LID_BOX_SURCHARGE_ADDITIONAL = 2.0

# Delivery Method options for the cart checkout flow.
#   standard     -> Lalamove Delivery (Local Courier Rates):
#                   base location rate from Taguig + cup/lid box surcharges.
#                   The stored key stays 'standard' so existing orders keep
#                   resolving; only the customer-facing label changed.
#   self_booking -> Customer Self-Booking / Warehouse Pick-up:
#                   Shipping Fee is always P0.00 (the customer books their own
#                   rider, e.g. Lalamove/Grab, once the order is Ready for Pick-up).
DELIVERY_METHOD_STANDARD = 'standard'
DELIVERY_METHOD_SELF_BOOKING = 'self_booking'
STANDARD_DELIVERY_LABEL = LALAMOVE_DELIVERY_LABEL
SELF_BOOKING_DELIVERY_LABEL = 'Customer Self-Booking / Warehouse Pick-up'
SELF_BOOKING_SHIPPING_LABEL = 'Customer Self-Booking'
SELF_BOOKING_STATUS = 'Ready for Pick-up'
SELF_BOOKING_NOTE = (
    "Note: You will book your own rider (Lalamove/Grab) once your order "
    "status is updated to 'Ready for Pick-up'."
)
DELIVERY_METHOD_LABELS = {
    DELIVERY_METHOD_STANDARD: STANDARD_DELIVERY_LABEL,
    DELIVERY_METHOD_SELF_BOOKING: SELF_BOOKING_DELIVERY_LABEL,
}
# Accepted aliases for the Customer Self-Booking / Warehouse Pick-up option.
SELF_BOOKING_ALIASES = {
    'self_booking', 'self-booking', 'selfbooking', 'self booking', 'self_book',
    'pickup', 'pick_up', 'pick-up', 'warehouse_pickup', 'warehouse pick-up',
    'customer_pickup', 'customer_self_booking',
}


def normalize_delivery_method(value):
    """Return the canonical Delivery Method key (defaults to Lalamove Delivery)."""
    method = str(value or '').strip().lower()
    return DELIVERY_METHOD_SELF_BOOKING if method in SELF_BOOKING_ALIASES else DELIVERY_METHOD_STANDARD


def is_self_booking(value):
    """True when the order uses Customer Self-Booking / Warehouse Pick-up."""
    return normalize_delivery_method(value) == DELIVERY_METHOD_SELF_BOOKING


def delivery_method_label(value):
    """Human-readable label for the selected Delivery Method."""
    return DELIVERY_METHOD_LABELS[normalize_delivery_method(value)]


def apply_delivery_method(shipping_fee, shipping_label, is_dynamic_cod, delivery_method):
    """Apply the selected Delivery Method to a computed courier fee.

    Lalamove Delivery (Local Courier Rates) keeps the zone-based fee (Taguig
    base rate + cup/lid box surcharges), while Customer Self-Booking /
    Warehouse Pick-up always ships at P0.00 because the customer books their own
    rider (Lalamove/Grab) once the order is marked 'Ready for Pick-up'.
    """
    if is_self_booking(delivery_method):
        return 0.0, SELF_BOOKING_SHIPPING_LABEL, False
    return float(shipping_fee or 0), shipping_label, is_dynamic_cod


def _parse_box_count(value):
    """Parse a box count defensively (form strings, ints, None)."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_delivery_zone(value):
    """Return the canonical Lalamove shipping zone id (defaults to Taguig)."""
    zone = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    if zone in LALAMOVE_ZONE_RATES:
        return zone
    return LALAMOVE_ZONE_ALIASES.get(zone, LALAMOVE_DEFAULT_ZONE)


def delivery_zone_label(value):
    """Human-readable label for a Lalamove shipping zone."""
    return LALAMOVE_ZONE_LABELS[normalize_delivery_zone(value)]


def delivery_zone_short_label(value):
    """Compact zone label used in fee/summary lines."""
    return LALAMOVE_ZONE_SHORT_LABELS[normalize_delivery_zone(value)]


def reservation_window_minutes(value):
    """Dynamic payment reservation window (minutes) for a destination zone.

    Taguig City = 30 minutes, nearby NCR cities = 1 hour and provincial
    addresses = 2 hours or more, mirroring LALAMOVE_ZONE_RESERVATION_MINUTES.
    """
    return LALAMOVE_ZONE_RESERVATION_MINUTES[normalize_delivery_zone(value)]


def reservation_window_label(value):
    """Human-readable reservation window, e.g. '30 minutes' or '1 hour'."""
    minutes = reservation_window_minutes(value)
    if minutes and minutes % 60 == 0:
        hours = minutes // 60
        return '%d hour%s' % (hours, '' if hours == 1 else 's')
    return '%d minutes' % minutes


def cup_box_surcharge(cup_boxes):
    """Cup box surcharge: first box P5.00, every succeeding box +P2.00."""
    cups = _parse_box_count(cup_boxes)
    if cups <= 0:
        return 0.0
    return CUP_BOX_SURCHARGE_FIRST + (cups - 1) * CUP_BOX_SURCHARGE_ADDITIONAL


def lid_box_surcharge(lid_boxes):
    """Lid box surcharge: first box P3.00, every succeeding box +P2.00."""
    lids = _parse_box_count(lid_boxes)
    if lids <= 0:
        return 0.0
    return LID_BOX_SURCHARGE_FIRST + (lids - 1) * LID_BOX_SURCHARGE_ADDITIONAL


def get_lalamove_shipping_fee(zone, cup_boxes=0, lid_boxes=0):
    """Return (fee, label, breakdown) for a Lalamove delivery from Taguig.

    Total Shipping Fee = Base Location Rate + Cup Surcharge + Lid Surcharge.
    Microwavables never add a base rate or a surcharge (subtotal only).
    """
    zone_key = normalize_delivery_zone(zone)
    base_rate = LALAMOVE_ZONE_RATES[zone_key]
    cup_fee = cup_box_surcharge(cup_boxes)
    lid_fee = lid_box_surcharge(lid_boxes)
    fee = round(base_rate + cup_fee + lid_fee, 2)
    zone_short = delivery_zone_short_label(zone_key)
    label = '%s (%s)' % (LALAMOVE_SHIPPING_LABEL, zone_short)
    breakdown = {
        'zone': zone_key,
        'zone_label': zone_short,
        'base_rate': base_rate,
        'cup_boxes': _parse_box_count(cup_boxes),
        'cup_surcharge': cup_fee,
        'lid_boxes': _parse_box_count(lid_boxes),
        'lid_surcharge': lid_fee,
        'fee': fee,
    }
    return fee, label, breakdown


def shipping_breakdown_text(breakdown):
    """Invoice-friendly Lalamove breakdown: base location rate + item surcharges."""
    if not breakdown:
        return ''
    parts = ['%s base P%.2f' % (breakdown['zone_label'], breakdown['base_rate'])]
    if breakdown['cup_boxes'] > 0:
        parts.append('cups %d box%s P%.2f' % (
            breakdown['cup_boxes'],
            '' if breakdown['cup_boxes'] == 1 else 'es',
            breakdown['cup_surcharge'],
        ))
    if breakdown['lid_boxes'] > 0:
        parts.append('lids %d box%s P%.2f' % (
            breakdown['lid_boxes'],
            '' if breakdown['lid_boxes'] == 1 else 'es',
            breakdown['lid_surcharge'],
        ))
    return ' + '.join(parts)


def get_db():
    """Establish and return a database connection with dict-like row access."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database schema and seed initial inventory if empty."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
            shipping_address TEXT
        )
    ''')

    # Create Products Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            size TEXT,
            style TEXT,
            quantity_per_box INTEGER NOT NULL,
            price_per_box REAL NOT NULL,
            stock_boxes INTEGER NOT NULL,
            description TEXT NOT NULL
        )
    ''')

    # Seed initial data ONLY when the products table is empty. When the table
    # (or the whole app.db file) already exists — the normal case after a
    # restart, re-deploy or code update — this block is skipped entirely so
    # every existing row, and especially its stock_boxes quantity, is read
    # straight back from the database instead of being re-seeded or reset to
    # the default values below.
    cursor.execute('SELECT COUNT(*) FROM products')
    if cursor.fetchone()[0] == 0:
        initial_products = [
            ('cup-12oz', 'cup', 'Cups — 12 oz (Box of 1,250)', '12oz', None, 1250, 2860.0, 50, 'High-quality, durable disposable plastic cups for cold beverages, milk tea, and iced coffee. Sealed per box of 1,250 units.'),
            ('cup-16oz', 'cup', 'Cups — 16 oz (Box of 1,250)', '16oz', None, 1250, 2960.0, 40, 'High-quality, durable disposable plastic cups for cold beverages, milk tea, and iced coffee. Sealed per box of 1,250 units.'),
            ('cup-22oz', 'cup', 'Cups — 22 oz (Box of 1,250)', '22oz', None, 1250, 3840.0, 25, 'High-quality, durable disposable plastic cups for cold beverages, milk tea, and iced coffee. Sealed per box of 1,250 units.'),
            ('lid-strawless', 'lid', 'Lids — Strawless (Box of 1,250)', None, 'Strawless', 1250, 1150.0, 60, 'Precision-fit leak-resistant lids engineered for standard cup rims. Sealed per box of 1,250 units.'),
            ('lid-dome', 'lid', 'Lids — Dome (Box of 1,250)', None, 'Dome', 1250, 1300.0, 30, 'Precision-fit leak-resistant lids engineered for standard cup rims. Sealed per box of 1,250 units.'),
            ('lid-flat', 'lid', 'Lids — Flat (Box of 1,250)', None, 'Flat', 1250, 1150.0, 15, 'Precision-fit leak-resistant lids engineered for standard cup rims. Sealed per box of 1,250 units.')
        ]
        # OR IGNORE is a second safety net: even if this guard were ever
        # bypassed, rows that already exist (and their live stock counts)
        # would never be overwritten by the default seed values.
        cursor.executemany('''
            INSERT OR IGNORE INTO products (id, type, name, size, style, quantity_per_box, price_per_box, stock_boxes, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', initial_products)
        conn.commit()

    # New microwavable products are appended with OR IGNORE so an existing
    # catalog (and every existing stock_boxes value) is left untouched; the
    # defaults below apply only to brand-new rows on a fresh database.
    microwavable_products = [
        ('container-re-3200', 'microwavable', 'RE 3200 Rectangular Container (3,200ml)', '3,200ml', 'RE Series', 100, 1800.0, 20, 'Extra-large heavy-duty food packaging. Excellent for full-sized platter meals and catering takeaways.'),
        ('container-re-2500', 'microwavable', 'RE 2500 Rectangular Container (2,500ml)', '2,500ml', 'RE Series', 100, 1600.0, 20, 'Large capacity food containers designed for family shares, party trays, and bulk food orders.'),
        ('container-re-1600', 'microwavable', 'RE 1600 Rectangular Container (1,600ml)', '1,600ml', 'RE Series', 100, 1400.0, 20, 'Medium-sized durable food containers with tight-fitting lids. Perfect for standard meals and pasta dishes.'),
        ('container-re-1000', 'microwavable', 'RE 1000 Rectangular Container (1,000ml)', '1,000ml', 'RE Series', 100, 1650.0, 20, 'Compact food-grade microwaveable containers. Ideal for rice meals, side dishes, and small take-out servings.'),
        ('container-re-750', 'microwavable', 'RE 750 Rectangular Container (750ml)', '750ml', 'RE Series', 100, 1450.0, 20, 'Compact food-grade microwaveable containers. Ideal for rice meals, side dishes, and small take-out servings.'),
        ('container-re-500', 'microwavable', 'RE 500 Rectangular Container (500ml)', '500ml', 'RE Series', 100, 1250.0, 20, 'Compact food-grade microwaveable containers. Ideal for rice meals, side dishes, and small take-out servings.'),
        ('container-ro-30', 'microwavable', 'RO 30 Round Container (30 oz)', '30oz', 'RO Series', 100, 1230.0, 20, 'Large capacity round food containers designed for family shares, party trays, and bulk food orders.'),
        ('container-ro-16', 'microwavable', 'RO 16 Round Container (16 oz)', '16oz', 'RO Series', 100, 960.0, 20, 'Medium-sized durable round food containers with tight-fitting lids. Perfect for standard meals and pasta dishes.'),
        ('container-ro-10', 'microwavable', 'RO 10 Round Container (10 oz)', '10oz', 'RO Series', 100, 820.0, 20, 'Compact food-grade microwaveable round containers. Ideal for rice meals, side dishes, and small take-out servings.')
    ]
    cursor.executemany('''
        INSERT OR IGNORE INTO products (id, type, name, size, style, quantity_per_box, price_per_box, stock_boxes, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', microwavable_products)
    conn.commit()

    # IMPORTANT: none of the startup migrations/backfills below ever writes
    # stock_boxes. Inventory numbers are changed only by the two write paths
    # that own them — the checkout deduction (/api/checkout) and the admin
    # stock update (/api/admin/update-stock) — so re-deploys and restarts
    # always preserve the actual remaining stock counts stored in app.db.

    # Cups and lids ship in 1,250-unit boxes (microwavable packs stay at 100).
    # Existing databases were seeded with 1,000-unit boxes, so backfill the unit
    # count and the product names; guarded so we only write when a legacy row is
    # still present (fresh databases are already seeded with 1,250).
    legacy_cup_lid_packs = cursor.execute(
        "SELECT COUNT(*) FROM products WHERE type IN ('cup', 'lid') "
        "AND (quantity_per_box <> 1250 OR name LIKE '%(Box of 1,000)%')"
    ).fetchone()[0]
    if legacy_cup_lid_packs > 0:
        cursor.execute('''
            UPDATE products
            SET quantity_per_box = 1250,
                name = REPLACE(name, '(Box of 1,000)', '(Box of 1,250)')
            WHERE type IN ('cup', 'lid')
        ''')
        conn.commit()

    # Microwavable container pricing update (per-box, packs of 100). Databases
    # seeded before this change carry the legacy rates, so backfill them here;
    # guarded so we only write while a legacy price is still present (fresh
    # databases are seeded directly with the new rates and any admin-updated
    # prices are left untouched).
    legacy_microwavable_prices = cursor.execute(
        "SELECT COUNT(*) FROM products WHERE type = 'microwavable' "
        "AND price_per_box IN (950.0, 800.0, 1100.0, 900.0, 750.0)"
    ).fetchone()[0]
    if legacy_microwavable_prices > 0:
        cursor.executemany('''
            UPDATE products SET price_per_box = ? WHERE id = ?
        ''', (
            (1450.0, 'container-re-750'),
            (1250.0, 'container-re-500'),
            (1230.0, 'container-ro-30'),
            (960.0, 'container-ro-16'),
            (820.0, 'container-ro-10'),
        ))
        conn.commit()

    # RE 1000 per-box price update: the 1,000ml rectangular container now
    # sells for ₱1,650.00 per box (packs of 100). Databases seeded before
    # this change carry the ₱1,200.00 rate, so backfill them here; guarded
    # so we only write while the old price is still present (fresh databases
    # are seeded directly with the new rate and any admin-updated price is
    # left untouched).
    re1000_current = cursor.execute(
        "SELECT price_per_box FROM products WHERE id = 'container-re-1000'"
    ).fetchone()
    if re1000_current and float(re1000_current[0] or 0) == 1200.0:
        cursor.execute(
            "UPDATE products SET price_per_box = ? WHERE id = ?",
            (1650.0, 'container-re-1000')
        )
        conn.commit()

    # Professional catalog copy: cups, lids, and microwavable containers use
    # complete marketing descriptions (pairs with the Dabba/GoUp badges above
    # each section on the storefront). Databases seeded before this change
    # carry the legacy one-line copy, so backfill them here; each UPDATE is
    # guarded by an exact match on a known legacy text so we only write while
    # the old copy is still present — fresh databases are seeded directly
    # with the professional wording and any admin-edited descriptions are
    # left untouched.
    professional_description_backfill = (
        ('High-quality, durable disposable plastic cups for cold beverages, milk tea, and iced coffee. Sealed per box of 1,250 units.',
         'cup-12oz', 'Durable 12oz disposable cups.'),
        ('High-quality, durable disposable plastic cups for cold beverages, milk tea, and iced coffee. Sealed per box of 1,250 units.',
         'cup-16oz', 'Classic 16oz disposable cups.'),
        ('High-quality, durable disposable plastic cups for cold beverages, milk tea, and iced coffee. Sealed per box of 1,250 units.',
         'cup-22oz', 'Large 22oz disposable cups.'),
        ('Precision-fit leak-resistant lids engineered for standard cup rims. Sealed per box of 1,250 units.',
         'lid-strawless', 'Strawless lids — universal fit.'),
        ('Precision-fit leak-resistant lids engineered for standard cup rims. Sealed per box of 1,250 units.',
         'lid-dome', 'Dome lids — universal fit.'),
        ('Precision-fit leak-resistant lids engineered for standard cup rims. Sealed per box of 1,250 units.',
         'lid-flat', 'Flat lids — universal fit.'),
        ('Extra-large heavy-duty food packaging. Excellent for full-sized platter meals and catering takeaways.',
         'container-re-3200', 'Authentic GoUp high-grade microwavable rectangular container with a 3,200ml capacity.'),
        ('Large capacity food containers designed for family shares, party trays, and bulk food orders.',
         'container-re-2500', 'Authentic GoUp high-grade microwavable rectangular container with a 2,500ml capacity.'),
        ('Medium-sized durable food containers with tight-fitting lids. Perfect for standard meals and pasta dishes.',
         'container-re-1600', 'Authentic GoUp high-grade microwavable rectangular container with a 1,600ml capacity.'),
        ('Compact food-grade microwaveable containers. Ideal for rice meals, side dishes, and small take-out servings.',
         'container-re-1000', 'Authentic GoUp high-grade microwavable rectangular container with a 1,000ml capacity.'),
        ('Compact food-grade microwaveable containers. Ideal for rice meals, side dishes, and small take-out servings.',
         'container-re-750', 'Authentic GoUp high-grade microwavable rectangular container with a 750ml capacity.'),
        ('Compact food-grade microwaveable containers. Ideal for rice meals, side dishes, and small take-out servings.',
         'container-re-500', 'Authentic GoUp high-grade microwavable rectangular container with a 500ml capacity.'),
        ('Large capacity round food containers designed for family shares, party trays, and bulk food orders.',
         'container-ro-30', 'Authentic GoUp high-grade microwavable round container with a 30oz capacity.'),
        ('Medium-sized durable round food containers with tight-fitting lids. Perfect for standard meals and pasta dishes.',
         'container-ro-16', 'Authentic GoUp high-grade microwavable round container with a 16oz capacity.'),
        ('Compact food-grade microwaveable round containers. Ideal for rice meals, side dishes, and small take-out servings.',
         'container-ro-10', 'Authentic GoUp high-grade microwavable round container with a 10oz capacity.'),
    )
    legacy_professional_descriptions = tuple(row[2] for row in professional_description_backfill)
    legacy_professional_count = cursor.execute(
        "SELECT COUNT(*) FROM products WHERE description IN (%s)" % ','.join('?' * len(legacy_professional_descriptions)),
        legacy_professional_descriptions
    ).fetchone()[0]
    if legacy_professional_count > 0:
        cursor.executemany('''
            UPDATE products SET description = ? WHERE id = ? AND description = ?
        ''', professional_description_backfill)
        conn.commit()


    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            customer_name TEXT NOT NULL,
            email TEXT,
            customer_address TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            gcash_ref TEXT,
            payment_method TEXT NOT NULL DEFAULT 'Cash on Delivery',
            delivery_method TEXT NOT NULL DEFAULT 'standard',
            delivery_zone TEXT NOT NULL DEFAULT 'taguig_city',
            status TEXT NOT NULL DEFAULT 'Pending',
            cup_id TEXT,
            cup_size TEXT,
            cup_boxes INTEGER,
            lid_id TEXT,
            lid_style TEXT,
            lid_boxes INTEGER,
            microwavable_size TEXT,
            total_amount REAL,
            created_at TEXT
        )
    ''')

    order_columns = [row['name'] for row in cursor.execute('PRAGMA table_info(orders)').fetchall()]
    if 'email' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN email TEXT")
    if 'payment_method' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'Cash on Delivery'")
    if 'status' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'Pending'")
    if 'microwavable_boxes' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN microwavable_boxes INTEGER NOT NULL DEFAULT 0")
    if 'cup_size' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN cup_size TEXT")
    if 'lid_style' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN lid_style TEXT")
    if 'microwavable_size' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN microwavable_size TEXT")
    if 'downpayment_amount' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN downpayment_amount REAL NOT NULL DEFAULT 0")
    if 'remaining_balance' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN remaining_balance REAL NOT NULL DEFAULT 0")
    if 'payment_status' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'Pending Downpayment'")
    if 'delivery_method' not in order_columns:
        # Delivery Method: 'standard' (Lalamove Delivery — local courier rates)
        # or 'self_booking' (Customer Self-Booking / Warehouse Pick-up, P0.00).
        cursor.execute("ALTER TABLE orders ADD COLUMN delivery_method TEXT NOT NULL DEFAULT 'standard'")
    if 'delivery_zone' not in order_columns:
        # Lalamove destination zone ('taguig_city' — the origin area — when
        # unknown). The base location rate and the cup/lid box surcharges are
        # derived from it.
        cursor.execute("ALTER TABLE orders ADD COLUMN delivery_zone TEXT NOT NULL DEFAULT 'taguig_city'")
    if 'user_id' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if 'total_amount' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN total_amount REAL NOT NULL DEFAULT 0")
    if 'created_at' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN created_at TEXT")
    if 'gcash_ref' not in order_columns:
        # GCash Reference Number (13-digit proof of payment) captured at
        # checkout; NULL when the customer has not paid yet.
        cursor.execute("ALTER TABLE orders ADD COLUMN gcash_ref TEXT")
    if 'gcash_proof' not in order_columns:
        # Relative path of the GCash payment screenshot uploaded from the Order
        # Confirmation Modal (e.g. 'uploads/gcash_proof_12_shot.png'); NULL when
        # the customer did not attach proof.
        cursor.execute("ALTER TABLE orders ADD COLUMN gcash_proof TEXT")
    conn.commit()

    conn.close()


init_db()


def user_profile(user):
    """Return the public profile fields exposed by authentication endpoints."""
    return {
        'full_name': user['full_name'],
        'email': user['email'],
        'phone': user['phone'],
        'shipping_address': user['shipping_address']
    }


@app.route('/register', methods=['POST'])
def register_form():
    """Create an account from a standard form POST, and redirect to the index."""
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()

    if not email or not password or not full_name:
        return "Email, password, and full name are required.", 400
    if len(password) < 8:
        return "Password must be at least 8 characters.", 400

    conn = get_db()
    try:
        password_hash = generate_password_hash(password)
        cursor = conn.execute('''
            INSERT INTO users (email, password_hash, full_name, phone, shipping_address)
            VALUES (?, ?, ?, ?, ?)
        ''', (email, password_hash, full_name, phone, address))
        conn.commit()
        user_id = cursor.lastrowid
        session.clear()
        session['user_id'] = user_id
    except sqlite3.IntegrityError:
        conn.close()
        return "An account with that email already exists.", 409
    conn.close()

    from flask import redirect
    return redirect('/')


@app.route('/api/register', methods=['POST'])
def register():
    """Create an account and sign the new user into the current session."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    full_name = (data.get('full_name') or data.get('fullName') or '').strip()
    phone = (data.get('phone') or data.get('phone_number') or '').strip()
    shipping_address = (data.get('address') or data.get('shipping_address') or data.get('shippingAddress') or '').strip()

    if not email or not password or not full_name:
        return jsonify({'error': 'Email, password, and full name are required.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400

    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO users (email, password_hash, full_name, phone, shipping_address)
            VALUES (?, ?, ?, ?, ?)
        ''', (email, generate_password_hash(password), full_name, phone, shipping_address))
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (cursor.lastrowid,)).fetchone()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'An account with that email already exists.'}), 409
    conn.close()

    session.clear()
    session['user_id'] = user['id']
    return jsonify({'user': user_profile(user)}), 201


@app.route('/api/login', methods=['POST'])
def login():
    """Validate credentials and store the authenticated user ID in session."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ? COLLATE NOCASE', (email,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid email or password.'}), 401

    session.clear()
    session['user_id'] = user['id']
    return jsonify({'user': user_profile(user)})


@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    """Set a new password for the account matching the supplied email address.

    This prototype flow lets a customer choose a new password directly from the
    browser (no emailed reset token), so it intentionally reports whether the
    email exists to keep the UI helpful. A production deployment should instead
    email a single-use, expiring reset link and always return a generic message.
    """
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    new_password = data.get('new_password') or data.get('newPassword') or data.get('password') or ''

    if not email or not new_password:
        return jsonify({'error': 'Email address and new password are required.'}), 400
    if len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ? COLLATE NOCASE', (email,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'No account found with that email address.'}), 404

    conn.execute(
        'UPDATE users SET password_hash = ? WHERE id = ?',
        (generate_password_hash(new_password), user['id'])
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Your password has been reset. You can now log in.'}), 200


@app.route('/api/me', methods=['GET'])
def current_user():
    """Return the current user's profile from the signed session."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Authentication required.'}), 401

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if not user:
        session.clear()
        return jsonify({'error': 'Authentication required.'}), 401
    return jsonify({'user': user_profile(user)})


@app.route('/api/logout', methods=['POST'])
def logout():
    """Sign the current user out by clearing the server-side session."""
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully.'}), 200


@app.route('/api/user/orders', methods=['GET'])
def user_orders():
    """Return the current customer's orders, filtered by the logged-in user name.

    Orders placed during a signed-in checkout are linked via user_id; they are
    also matched by the full name stored on the order so customers only ever
    see their own orders.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Authentication required.'}), 401

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        session.clear()
        return jsonify({'error': 'Authentication required.'}), 401

    orders = conn.execute(
        '''SELECT *
           FROM orders
           WHERE user_id = ? OR customer_name = ?
           ORDER BY id DESC''',
        (user_id, user['full_name'])
    ).fetchall()
    conn.close()

    return jsonify({'orders': [dict(order) for order in orders]})


# ---------------------------------------------------------------------------
# SEO assets: canonical base URL, public page list and the XML sitemap.
# ---------------------------------------------------------------------------
def get_site_base_url():
    """Return the absolute site root (no trailing slash) used by SEO assets.

    Resolution order:
      1. The SITE_URL (or PUBLIC_BASE_URL) environment variable. Set this on a
         free host such as Render / PythonAnywhere, or as soon as a custom
         domain goes live, e.g. SITE_URL=https://packandsip.com . A missing
         scheme is filled in with https:// so SITE_URL=packandsip.com works too.
      2. request.host_url, so the same build also works on 127.0.0.1:5000,
         <app>.onrender.com and <user>.pythonanywhere.com without any config.
    """
    configured = (os.getenv('SITE_URL') or os.getenv('PUBLIC_BASE_URL') or '').strip()
    if configured:
        if '://' not in configured:
            configured = 'https://' + configured
        return configured.rstrip('/')
    return request.host_url.rstrip('/')


# Public crawlable pages published in /sitemap.xml: (path, changefreq, priority).
# The storefront is a single-page app, so the catalogue, configurator and
# microwavable sections are all part of '/' and are not listed separately
# ('#section' anchors are ignored by search engines and would only duplicate the
# homepage). Any new public GET route is discovered automatically by
# get_public_sitemap_pages(); add an entry here when it needs custom SEO values.
SITEMAP_PAGES = (
    ('/', 'weekly', '1.0'),
)

# Routes that must never be published even though they answer GET requests.
SITEMAP_EXCLUDED_RULES = frozenset({
    '/sitemap.xml',
    '/robots.txt',
    '/index.html',            # alias of '/'
    '/manage-orders-ps.html',  # staff-only order dashboard
    '/manage-orders',         # clean alias of the staff dashboard
    '/manage-orders.html',    # legacy alias of the staff dashboard
    '/admin',                 # clean alias of the staff dashboard
    '/admin.html',            # legacy alias of the staff dashboard
    '/upload-receipt',        # order-specific receipt upload link
})
SITEMAP_EXCLUDED_PREFIXES = ('/api/', '/admin/', '/static/')


def get_public_sitemap_pages():
    """Return the public (path, changefreq, priority) entries for the sitemap.

    Starts from SITEMAP_PAGES and appends every other GET route that is public
    (no URL arguments, not an excluded admin/API/utility rule), so newly added
    pages appear in the sitemap without further changes.
    """
    pages = [tuple(entry) for entry in SITEMAP_PAGES]
    known = {path for path, _, _ in pages}
    for rule in app.url_map.iter_rules():
        path = rule.rule
        if path in known or path in SITEMAP_EXCLUDED_RULES:
            continue
        if rule.arguments or path.startswith(SITEMAP_EXCLUDED_PREFIXES):
            continue
        if 'GET' not in (rule.methods or set()):
            continue
        # Discovered pages get conservative defaults until listed in SITEMAP_PAGES.
        pages.append((path, 'monthly', '0.5'))
    return pages


def build_sitemap_xml():
    """Build a valid sitemap.org XML document for the public storefront pages."""
    base_url = get_site_base_url()
    lastmod = datetime.date.today().isoformat()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, changefreq, priority in get_public_sitemap_pages():
        lines.extend([
            '  <url>',
            f'    <loc>{html.escape(base_url + path, quote=True)}</loc>',
            f'    <lastmod>{lastmod}</lastmod>',
            f'    <changefreq>{changefreq}</changefreq>',
            f'    <priority>{priority}</priority>',
            '  </url>',
        ])
    lines.append('</urlset>')
    return '\n'.join(lines)


@app.route('/')
@app.route('/index.html')
def index():
    """Render the storefront with request-aware SEO metadata.

    Both '/' and '/index.html' serve the same rendered page so the Jinja SEO
    placeholders (canonical + Open Graph URL) are always resolved, and the
    canonical tag consolidates the two URLs into a single one.
    """
    site_url = get_site_base_url()
    # The City/Location <select> is rendered from the same Lalamove zone table
    # the API bills against, so the storefront estimate cannot drift.
    return render_template(
        'index.html',
        site_url=site_url,
        canonical_url=site_url + '/',
        lalamove_zones=LALAMOVE_ZONE_OPTIONS,
        lalamove_origin=LALAMOVE_ORIGIN,
        lalamove_note=LALAMOVE_DELIVERY_NOTE,
    )


@app.route('/sitemap.xml')
def sitemap():
    """Serve the dynamically generated XML sitemap of the public pages."""
    return build_sitemap_xml(), 200, {'Content-Type': 'application/xml'}


@app.route('/robots.txt')
def robots_txt():
    """Serve robots.txt pointing crawlers at the sitemap and hiding staff URLs."""
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        'Disallow: /admin',
        'Disallow: /admin.html',
        'Disallow: /api/',
        'Disallow: /manage-orders-ps.html',
        'Disallow: /manage-orders',
        'Disallow: /manage-orders.html',
        'Disallow: /upload-receipt',
        '',
        f'Sitemap: {get_site_base_url()}/sitemap.xml',
        '',
    ]
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


@app.route('/api/products', methods=['GET'])
def get_products():
    """Fetch all products from SQLite database.

    This is the single source of truth for live inventory (``stock_boxes``).
    The storefront (``main.js``) must always render these server values
    instead of hardcoded defaults, so the response is marked ``no-store`` to
    prevent browsers / proxies from serving a stale cached copy after an
    order or an admin stock update.
    """
    conn = get_db()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()

    result = []
    for p in products:
        item = dict(p)
        # Compatible sizes for universal lids
        if item['type'] == 'lid':
            item['compatible_sizes'] = ["12oz", "16oz", "22oz"]
        try:
            item['stock_boxes'] = int(item.get('stock_boxes', 0) or 0)
        except (TypeError, ValueError):
            item['stock_boxes'] = 0
        item['in_stock'] = item['stock_boxes'] > 0
        result.append(item)

    response = jsonify({"products": result})
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response


@app.route('/manage-orders-ps.html', methods=['GET'])
@app.route('/manage-orders.html', methods=['GET'])
@app.route('/manage-orders', methods=['GET'])
@app.route('/admin', methods=['GET'])
@app.route('/admin.html', methods=['GET'])
def admin_dashboard():
    """Render the order management dashboard.

    The canonical file on disk is ``manage-orders-ps.html``. The extra
    ``/manage-orders``, ``/manage-orders.html``, ``/admin`` and
    ``/admin.html`` aliases exist so footer links, bookmarks, and mobile
    browsers that request the short names never hit the generic
    ``/<path:filename>`` static handler (which would 404 when the file is
    not found). All aliases render the same staff template.
    """
    return render_template('manage-orders-ps.html')


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Serve an uploaded GCash payment proof (or receipt) screenshot.

    Uploads live in the ABSOLUTE UPLOAD_FOLDER next to app.py, so this route
    keeps working no matter which working directory the server was started from
    (the generic ``/<path:filename>`` handler below resolves against the process
    cwd instead, which would 404 after a deploy started from another folder).

    Every ``orders.gcash_proof`` value stores the relative path
    ``uploads/<filename>``, which maps 1:1 onto this route, so the admin
    dashboard's "PAYMENT PROOF" column can load the image with a plain <img>.
    """
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)


@app.route('/api/admin/orders', methods=['GET'])
def get_admin_orders():
    """Fetch all orders for the admin dashboard, newest first."""
    conn = get_db()
    orders = conn.execute('''
        SELECT
            id,
            -- Contact identity comes straight from the order row captured at
            -- checkout (guest checkout included), so a registered account is
            -- NEVER required to identify a customer. user_id is exposed only so
            -- the dashboard can badge an order as Guest vs Registered.
            user_id,
            customer_name AS full_name,
            customer_phone AS phone_number,
            email,
            customer_address AS shipping_address,
            payment_method,
            COALESCE(cup_boxes, 0) AS cup_boxes,
            cup_size,
            COALESCE(lid_boxes, 0) AS lid_boxes,
            lid_style,
            COALESCE(microwavable_boxes, 0) AS microwavable_boxes,
            microwavable_size,
            total_amount,
            status,
            payment_status,
            COALESCE(delivery_method, 'standard') AS delivery_method,
            COALESCE(delivery_zone, 'taguig_city') AS delivery_zone,
            gcash_ref,
            gcash_proof
        FROM orders
        ORDER BY created_at DESC, id DESC
    ''').fetchall()
    conn.close()
    return jsonify({"orders": [dict(order) for order in orders]})


@app.route('/api/admin/orders/<int:order_id>/status', methods=['PATCH', 'PUT'])
@app.route('/api/orders/<int:order_id>/status', methods=['PUT', 'PATCH'])
def update_order_status(order_id):
    """Update an order's fulfillment status."""
    allowed_statuses = {'Pending', 'Paid', SELF_BOOKING_STATUS, 'Shipping', 'Shipped', 'Completed'}
    data = request.get_json(force=True, silent=True) or {}
    status = data.get('status')

    if status not in allowed_statuses:
        return jsonify({
            "error": "Status must be Pending, Paid, Ready for Pick-up, Shipped, or Completed."
        }), 400

    conn = get_db()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "Order not found."}), 404

    conn.execute(
        'UPDATE orders SET status = ? WHERE id = ?',
        (status, order_id)
    )
    conn.commit()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()

    return jsonify({"order": dict(order)})


@app.route('/admin/ship-order/<int:order_id>', methods=['POST'])
def admin_ship_order(order_id):
    """Verify payment receipt and mark the order ready for fulfillment.

    Lalamove Delivery orders are marked 'Shipping'; Customer Self-Booking /
    Warehouse Pick-up orders are marked 'Ready for Pick-up' instead (no courier
    is booked — the customer arranges their own rider).
    """
    conn = get_db()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "Order not found."}), 404

    self_booking = is_self_booking(order['delivery_method'] or '')
    new_status = SELF_BOOKING_STATUS if self_booking else 'Shipping'

    conn.execute(
        'UPDATE orders SET status = ?, payment_status = ? WHERE id = ?',
        (new_status, 'Verified', order_id)
    )
    conn.commit()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Order #{order_id} verified. Status updated to {new_status}.",
        "order": dict(order)
    })


@app.route('/api/cart/calculate', methods=['POST'])
def calculate_cart():
    """Calculate subtotal, shipping, and total dynamically."""
    data = request.get_json(force=True, silent=True) or {}

    cup_id = data.get('cup_id')
    lid_id = data.get('lid_id')

    try:
        cup_boxes = int(data.get('cup_boxes', 0) or 0)
    except Exception:
        cup_boxes = 0

    try:
        lid_boxes = int(data.get('lid_boxes', 0) or 0)
    except Exception:
        lid_boxes = 0

    try:
        microwavable_boxes = int(data.get('microwavable_boxes', 0) or 0)
    except Exception:
        microwavable_boxes = 0

    # Delivery Method: 'standard' = Lalamove Delivery (Local Courier Rates);
    # 'self_booking' ships at P0.00 (customer books their own rider).
    delivery_method = normalize_delivery_method(data.get('delivery_method'))

    conn = get_db()
    items = []
    subtotal = 0.0

    if cup_id and cup_boxes > 0:
        cup = conn.execute('SELECT * FROM products WHERE id = ?', (cup_id,)).fetchone()
        if cup:
            line_total = cup['price_per_box'] * cup_boxes
            items.append({
                "id": cup['id'],
                "name": cup['name'],
                "unit_price": cup['price_per_box'],
                "boxes": cup_boxes,
                "quantity_per_box": cup['quantity_per_box'],
                "line_total": round(line_total, 2)
            })
            subtotal += line_total

    if lid_id and lid_boxes > 0:
        lid = conn.execute('SELECT * FROM products WHERE id = ?', (lid_id,)).fetchone()
        if lid:
            line_total = lid['price_per_box'] * lid_boxes
            items.append({
                "id": lid['id'],
                "name": lid['name'],
                "unit_price": lid['price_per_box'],
                "boxes": lid_boxes,
                "quantity_per_box": lid['quantity_per_box'],
                "line_total": round(line_total, 2)
            })
            subtotal += line_total

    subtotal = round(subtotal, 2)
    # Lalamove Delivery fee (origin: Taguig) = destination base rate + cup/lid
    # box surcharges. Microwavables add neither a base rate nor a surcharge, so
    # only cups + lids feed the fee.
    total_boxes = cup_boxes + lid_boxes + microwavable_boxes
    delivery_zone = normalize_delivery_zone(data.get('delivery_zone'))
    shipping, shipping_label, shipping_breakdown = get_lalamove_shipping_fee(
        delivery_zone,
        cup_boxes=cup_boxes,
        lid_boxes=lid_boxes,
    )
    if subtotal <= 0:
        shipping, shipping_label, shipping_breakdown = 0.0, '—', None
    # Delivery Method: Lalamove Delivery keeps the zone-based fee;
    # Customer Self-Booking / Warehouse Pick-up always ships at P0.00.
    shipping, shipping_label, is_dynamic_cod = apply_delivery_method(
        shipping, shipping_label, False, delivery_method
    )
    shipping = round(shipping, 2)
    shipping_display = 'P%.2f' % shipping
    if is_self_booking(delivery_method):
        shipping_display = 'P0.00 (Customer Self-Booking)'
    total = round(subtotal + shipping, 2)

    conn.close()

    return jsonify({
        "items": items,
        "subtotal": subtotal,
        "shipping": shipping,
        "shipping_label": shipping_label,
        "shipping_display": shipping_display,
        "shipping_breakdown": shipping_breakdown_text(shipping_breakdown),
        "total_boxes": total_boxes,
        "is_dynamic_cod": is_dynamic_cod,
        "delivery_method": delivery_method,
        "delivery_method_label": delivery_method_label(delivery_method),
        "delivery_zone": delivery_zone,
        "delivery_zone_label": delivery_zone_label(delivery_zone),
        "reservation_minutes": reservation_window_minutes(delivery_zone),
        "reservation_window": reservation_window_label(delivery_zone),
        "total": total
    })


@app.route('/checkout', methods=['POST'])
@app.route('/api/checkout', methods=['POST'])
@app.route('/api/orders', methods=['POST'])
def process_checkout():
    """Read the customer details and cart items, then save the order to app.db."""
    data = request.get_json(silent=True)
    if not data:
        # Accept standard form/multipart submissions, e.g.
        # <form action="/checkout" method="POST" id="checkoutForm">. The cart
        # items, quantities and totals arrive as hidden fields in the form.
        data = {key: request.form.get(key) for key in request.form}

    # GCash proof-of-payment screenshot: the Order Confirmation Modal always
    # submits the form as multipart/form-data with the chosen image in the
    # "gcash_proof" field (see main.js submitOrder).
    proof_file = request.files.get('gcash_proof') if request.files else None

    name = (data.get('name') or '').strip()
    # Email is OPTIONAL: the storefront checkout identifies the customer by
    # Full Name + Phone Number (collected first, no email address), so no email
    # value is submitted. The field is kept for backward compatibility with
    # account-based orders and older clients.
    email = (data.get('email') or '').strip()
    address = (data.get('address') or '').strip()
    phone = (data.get('phone') or '').strip()
    # GCash Reference Number (proof of payment): OPTIONAL — the storefront saves
    # the order as Pending Payment so the customer can pay afterwards and send
    # the screenshot/reference by email. When a value IS supplied it must be a
    # complete 13-digit GCash reference so the staff dashboard always shows a
    # verifiable proof of payment (blank is stored as NULL).
    gcash_ref = (data.get('gcash_ref') or '').strip()
    if gcash_ref and not (len(gcash_ref) == 13 and gcash_ref.isascii() and gcash_ref.isdigit()):
        return jsonify({"error": "Please enter a valid 13-digit GCash reference number, or leave it blank."}), 400
    gcash_ref = gcash_ref or None
    payment_type = (data.get('payment_type') or '50_percent').strip()
    payment_method = (data.get('payment_method') or '').strip()
    if not payment_method:
        payment_method = 'GCash (50% Downpayment)' if payment_type == '50_percent' else 'GCash (Full Payment)'
    # Delivery Method radio group (defaults to Lalamove Delivery when absent).
    delivery_method = normalize_delivery_method(data.get('delivery_method'))
    # City / Location selector: drives the Lalamove destination base rate
    # (origin: Taguig). Unknown/legacy submissions fall back to Taguig City.
    delivery_zone = normalize_delivery_zone(data.get('delivery_zone'))
    user_id = session.get('user_id')
    cup_id = data.get('cup_id') or None
    lid_id = data.get('lid_id') or None
    microwavable_id = data.get('microwavable_id') or None
    cup_size = (data.get('cup_size') or '').strip() or None
    lid_style = (data.get('lid_style') or '').strip() or None
    microwavable_size = (data.get('microwavable_size') or '').strip() or None

    try:
        due_now = float(data.get('due_now', 0))
        remaining_balance = float(data.get('remaining_balance', 0))
    except (TypeError, ValueError):
        due_now = 0.0
        remaining_balance = 0.0

    try:
        cup_boxes = int(data.get('cup_boxes', 0) or 0)
        lid_boxes = int(data.get('lid_boxes', 0) or 0)
        microwavable_boxes = int(data.get('microwavable_boxes', 0) or 0)
    except Exception:
        return jsonify({"error": "Invalid quantities provided"}), 400

    if not name or not phone:
        return jsonify({"error": "Customer name and phone number are required."}), 400

    self_booking = is_self_booking(delivery_method)
    if not address and not self_booking:
        return jsonify({"error": "Shipping address is required for Lalamove Delivery."}), 400

    if cup_boxes < 0 or lid_boxes < 0 or microwavable_boxes < 0:
        return jsonify({"error": "Quantities cannot be negative"}), 400

    if cup_boxes <= 0 and lid_boxes <= 0 and microwavable_boxes <= 0:
        return jsonify({"error": "Cart is empty"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Validate stock availability first
    orders_to_process = []
    if cup_id and cup_boxes > 0:
        orders_to_process.append((cup_id, cup_boxes))
    if lid_id and lid_boxes > 0:
        orders_to_process.append((lid_id, lid_boxes))
    if microwavable_id and microwavable_boxes > 0:
        orders_to_process.append((microwavable_id, microwavable_boxes))
    elif microwavable_boxes > 0:
        conn.close()
        return jsonify({"error": "A microwavable container must be selected."}), 400

    for pid, requested_qty in orders_to_process:
        product = cursor.execute('SELECT name, stock_boxes, price_per_box FROM products WHERE id = ?', (pid,)).fetchone()
        if not product:
            conn.close()
            return jsonify({"error": f"Product {pid} not found"}), 404
        if product['stock_boxes'] < requested_qty:
            conn.close()
            return jsonify({
                "error": f"Insufficient stock for {product['name']}. Only {product['stock_boxes']} box(es) left."
            }), 400

    # Compute totals
    subtotal = 0.0
    unit_prices = {'cup': 0.0, 'lid': 0.0, 'microwavable': MICROWAVABLE_PRICE_PER_BOX}
    if cup_id and cup_boxes > 0:
        cup = cursor.execute('SELECT price_per_box FROM products WHERE id = ?', (cup_id,)).fetchone()
        unit_prices['cup'] = float(cup['price_per_box'] or 0)
        subtotal += cup['price_per_box'] * cup_boxes
    if lid_id and lid_boxes > 0:
        lid = cursor.execute('SELECT price_per_box FROM products WHERE id = ?', (lid_id,)).fetchone()
        unit_prices['lid'] = float(lid['price_per_box'] or 0)
        subtotal += lid['price_per_box'] * lid_boxes
    if microwavable_id and microwavable_boxes > 0:
        # Charge the selected container's own per-box price (admin-editable);
        # fall back to the legacy flat rate only if the product is missing.
        micro = cursor.execute(
            'SELECT price_per_box FROM products WHERE id = ?', (microwavable_id,)
        ).fetchone()
        micro_price = float(micro['price_per_box']) if micro else MICROWAVABLE_PRICE_PER_BOX
    else:
        micro_price = MICROWAVABLE_PRICE_PER_BOX
    unit_prices['microwavable'] = micro_price
    subtotal += micro_price * microwavable_boxes

    subtotal = round(subtotal, 2)
    # Lalamove Delivery fee (origin: Taguig) = destination base rate + cup/lid
    # box surcharges. The FULL fee is always charged upfront, even for 50%
    # downpayment: Initial Amount Due = (Subtotal * 0.50) + Full Shipping Fee.
    # Microwavables add neither a base rate nor a surcharge (they still count in
    # the order subtotal/total).
    total_boxes = cup_boxes + lid_boxes + microwavable_boxes
    shipping, shipping_label, shipping_breakdown = get_lalamove_shipping_fee(
        delivery_zone,
        cup_boxes=cup_boxes,
        lid_boxes=lid_boxes,
    )
    if subtotal <= 0:
        shipping, shipping_label, shipping_breakdown = 0.0, '—', None
    # Delivery Method: Lalamove Delivery (Local Courier Rates) keeps the
    # zone-based fee; Customer Self-Booking / Warehouse Pick-up always ships at
    # P0.00 (no courier is booked).
    shipping, shipping_label, is_dynamic_cod = apply_delivery_method(
        shipping, shipping_label, False, delivery_method
    )
    shipping = round(shipping, 2)
    total = round(subtotal + shipping, 2)
    if payment_type == 'full':
        # Full payment: everything (subtotal + FULL shipping) is due now.
        downpayment_amount = round(total, 2)
        remaining_balance = 0.0
        payment_status = 'Full Payment Pending'
    else:
        # Downpayment (50%): initial due = (subtotal * 50%) + FULL shipping;
        # remaining balance = subtotal * 50% (shipping already collected at 100%).
        downpayment_base = round(subtotal * 0.5, 2)
        downpayment_amount = round(downpayment_base + shipping, 2)
        remaining_balance = round(subtotal * 0.5, 2)
        payment_status = 'Pending Downpayment'

    # Deduct stock and insert order within a transaction
    try:
        for pid, requested_qty in orders_to_process:
            cursor.execute(
                # This app stores available inventory in stock_boxes.
                'UPDATE products SET stock_boxes = stock_boxes - ? WHERE id = ?',
                (requested_qty, pid)
            )

        created_at = datetime.datetime.utcnow().isoformat()

        cursor.execute('''
            INSERT INTO orders (user_id, customer_name, email, customer_address, customer_phone, payment_method, delivery_method, delivery_zone, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total_amount, downpayment_amount, remaining_balance, payment_status, created_at, gcash_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, name, email, address, phone, payment_method, delivery_method, delivery_zone, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total, downpayment_amount, remaining_balance, payment_status, created_at, gcash_ref))


        order_id = cursor.lastrowid
        conn.commit()

        # Persist the uploaded GCash proof AFTER the order row is committed, so
        # a storage/disk failure can never lose the order or roll it back. The
        # saved relative path is recorded in orders.gcash_proof for the staff
        # dashboard.
        if proof_file is not None and (proof_file.filename or '').strip():
            try:
                safe_name = secure_filename(proof_file.filename) or 'gcash_proof'
                extension = os.path.splitext(safe_name)[1].lower()
                if extension in IMAGE_EXTENSIONS:
                    stored_name = f"gcash_proof_{order_id}_{safe_name}"
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    proof_file.save(os.path.join(app.config['UPLOAD_FOLDER'], stored_name))
                    cursor.execute(
                        'UPDATE orders SET gcash_proof = ? WHERE id = ?',
                        (f"uploads/{stored_name}", order_id)
                    )
                    conn.commit()
                else:
                    print(f"GCash proof ignored for order {order_id}: unsupported file type '{extension}'")
            except Exception as proof_err:
                print("GCash proof save error:", proof_err)

        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": f"Failed to process order: {str(e)}"}), 500

    conn.close()

    # Admin notification email (Resend) — fired immediately AFTER the order row
    # has been committed to app.db and the connection closed. The entire send
    # sits in its own try/except so it can NEVER crash the checkout route: if
    # Resend fails (bad key, network outage, API error) we just print the error
    # and the customer still receives their normal success response below.
    # NOTE: order is a sqlite3.Row (subscript access, not attributes), so the
    # saved row's id/total are read via order_id and the computed `total`
    # local — the same values stored in orders.id / orders.total_amount.
    try:
        resend.Emails.send({
            "from": "Pack & Sip <onboarding@resend.dev>",
            "to": ["legolandcreator@gmail.com"],
            "subject": f"📦 New Order #{order_id} Received!",
            "html": f"<h3>New Order Alert!</h3><p><strong>Customer:</strong> {name}</p><p><strong>Phone:</strong> {phone}</p><p><strong>Total:</strong> ₱{total}</p>"
        })
    except Exception as e:
        print("Resend notification error:", e)

    return jsonify({'success': True, 'message': 'Order placed successfully!'}), 200


@app.route('/upload-receipt', methods=['GET', 'POST'])
def upload_receipt():
    order_id = request.args.get('order_id')
    if request.method == 'POST':
        order_id = request.form.get('order_id')
        file = request.files.get('receipt')
        if not order_id or not file:
            return "Missing Order ID or Receipt File", 400
        
        filename = secure_filename(f"receipt_{order_id}_{file.filename}")
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        conn = get_db()
        conn.execute('UPDATE orders SET payment_status = ? WHERE id = ?', ('Receipt Uploaded', order_id))
        conn.commit()
        conn.close()
        
        return "<h1>Receipt Uploaded Successfully!</h1><p>We will verify your payment and update your order status soon.</p>"

    return render_template_string('''
        <!doctype html>
        <html>
        <head>
            <title>Upload Receipt - Pack & Sip</title>
            <link rel="icon" type="image/png" sizes="512x512" href="favicon.png">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4">
            <div class="bg-white p-8 rounded-xl shadow-lg max-w-md w-full">
                <h1 class="text-2xl font-bold mb-4 text-indigo-700">Upload Payment Receipt</h1>
                <p class="text-slate-700 font-medium mb-6 text-sm">Please upload your GCash screenshot for Order #{{ order_id }}</p>
                <form method="POST" enctype="multipart/form-data" class="space-y-4">
                    <input type="hidden" name="order_id" value="{{ order_id }}">
                    <div>
                        <label class="block text-sm font-medium text-slate-700 mb-2">Select Screenshot</label>
                        <input type="file" name="receipt" accept="image/*" required class="w-full border p-2 rounded-md">
                    </div>
                    <button type="submit" class="w-full bg-indigo-600 text-white py-2 rounded-md font-bold hover:bg-indigo-700">Upload Receipt</button>
                </form>
            </div>
        </body>
        </html>
    ''', order_id=order_id)


@app.route('/admin/delete-order/<int:order_id>', methods=['DELETE', 'POST'])
def delete_order(order_id):
    """Delete an order from the database."""
    conn = get_db()
    conn.execute('DELETE FROM orders WHERE id = ?', (order_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Order deleted successfully'})



@app.route('/api/admin/inventory', methods=['GET'])

def admin_inventory():
    """Fetch all products and their stock levels for management."""
    conn = get_db()
    products = conn.execute('SELECT id, name, stock_boxes FROM products').fetchall()
    conn.close()
    response = jsonify({"inventory": [dict(p) for p in products]})
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response


@app.route('/api/admin/update-stock', methods=['POST'])
def update_stock():
    """Update stock_boxes for a specific product.

    This is the backend write path for admin stock edits: the value is
    persisted in SQLite so the next GET /api/products (storefront refresh)
    returns the real updated quantity.
    """
    data = request.get_json(force=True, silent=True) or {}
    product_id = data.get('product_id')
    try:
        new_stock = int(data.get('new_stock', 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid stock value"}), 400

    if not product_id:
        return jsonify({"error": "Product ID required"}), 400
    if new_stock < 0:
        return jsonify({"error": "Stock cannot be negative"}), 400

    conn = get_db()
    cursor = conn.execute('UPDATE products SET stock_boxes = ? WHERE id = ?', (new_stock, product_id))
    conn.commit()
    success = cursor.rowcount > 0
    row = conn.execute('SELECT id, name, stock_boxes FROM products WHERE id = ?', (product_id,)).fetchone() if success else None
    conn.close()

    if not success:
        return jsonify({"error": "Product not found"}), 404

    return jsonify({"success": True, "message": "Stock updated successfully", "product": dict(row) if row else None})


if __name__ == '__main__':

    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)