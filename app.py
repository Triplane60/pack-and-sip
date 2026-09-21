import sqlite3
import os
import io
import html
import datetime
import threading
from flask import Flask, jsonify, render_template, request, send_from_directory, session, render_template_string
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa

from flask_cors import CORS
from flask_mail import Mail, Message
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, template_folder='.')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'pack-sip-development-secret')
CORS(app, supports_credentials=True)

# Flask-Mail configuration for Gmail SMTP.
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'jambyletesa@gmail.com'  # Replace with your real sender email
app.config['MAIL_PASSWORD'] = 'hzwmquliysbajowt'  # Google App Password
app.config['MAIL_DEFAULT_SENDER'] = 'jambyletesa@gmail.com'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
mail = Mail(app)

DB_FILE = 'app.db'
MICROWAVABLE_PRICE_PER_BOX = 1500.0
# Automatic shipping tiers based on CUPS + LIDS box count + order composition.
# Microwavables are EXCLUDED from vehicle/shipping-tier assignment (they do not
# count toward total_boxes and never disqualify Motorcycle).
# The FULL applicable fee is always charged upfront, even for 50% downpayment:
#   Initial Amount Due = (Subtotal * 0.50) + Full Shipping Fee.
# Tiers (cups + lids only):
#   1-3 boxes (content-aware):
#     Motorcycle P120 ONLY if (max 2 boxes of 12oz cups ONLY) OR
#       (max 1 box of 16oz/22oz cups ONLY) OR (max 1 cup + 1 lid = 2 boxes
#       total) OR (max 3 boxes of lids ONLY); otherwise Sedan P250.
#   Sedan P250 upgrade if: 2+ boxes of 16oz/22oz, OR cups+lids > 3,
#     OR overall (cups+lids) total 4-8 boxes.
#   9-18 boxes:  P400 MPV / Small Van
#   19-40 boxes: P600 L300 / Medium Truck
#   41+ boxes:   P1200 Large Truck
SHIPPING_TIERS = [
    (120.0, 'Motorcycle'),
    (250.0, 'Sedan'),
    (400.0, 'MPV / Small Van'),
    (600.0, 'L300 / Medium Truck'),
    (1200.0, 'Large Truck'),
]
# Kept for backwards compatibility (motorcycle tier rate).
MOTORCYCLE_SHIPPING_FEE = 120.0
LARGE_CUP_SIZES = {'16oz', '22oz'}
LARGE_CUP_IDS = {'cup-16oz', 'cup-22oz'}

# Delivery Method options for the cart checkout flow.
#   standard     -> Standard Delivery (Ship via Pack & Sip Courier):
#                   the existing content-aware box-tier logic (P120-P1200).
#   self_booking -> Customer Self-Booking / Warehouse Pick-up:
#                   Shipping Fee is always P0.00 (the customer books their own
#                   rider, e.g. Lalamove/Grab, once the order is Ready for Pick-up).
DELIVERY_METHOD_STANDARD = 'standard'
DELIVERY_METHOD_SELF_BOOKING = 'self_booking'
STANDARD_DELIVERY_LABEL = 'Standard Delivery (Ship via Pack & Sip Courier)'
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
    """Return the canonical Delivery Method key (defaults to Standard Delivery)."""
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

    Standard Delivery keeps the content-aware box-tier fee (P120-P1200), while
    Customer Self-Booking / Warehouse Pick-up always ships at P0.00 because the
    customer books their own rider (Lalamove/Grab) once the order is marked
    'Ready for Pick-up'.
    """
    if is_self_booking(delivery_method):
        return 0.0, SELF_BOOKING_SHIPPING_LABEL, False
    return float(shipping_fee or 0), shipping_label, is_dynamic_cod


def _is_large_cup_size(cup_size):
    """True when the cup size string denotes a bulky 16oz/22oz box."""
    return str(cup_size or '').strip().lower() in LARGE_CUP_SIZES


def _is_large_cup_id(cup_id):
    """True when the cup product id denotes a bulky 16oz/22oz box."""
    return str(cup_id or '').strip().lower() in LARGE_CUP_IDS


def _normalize_has_large_cups(value):
    """Normalize bool/str/int flag for 'order contains 16oz or 22oz cups'."""
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on', '16oz', '22oz')
    return bool(value)


def _parse_box_count(value):
    """Parse a box count defensively (form strings, ints, None)."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_large_cup_boxes(value):
    """Parse the 16oz/22oz cup box count defensively.

    Returns None when the value is missing/blank (unknown — fall back to the
    has_large_cups flag / cup size / cup id signals instead of assuming 0).
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == '':
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def is_motorcycle_eligible(cup_boxes=0, lid_boxes=0, microwavable_boxes=0,
                           small_cup_boxes=None, large_cup_boxes=None):
    """Motorcycle (P120) is allowed ONLY for these small cup/lid-only orders.

    - Max 2 boxes of 12oz cups ONLY (no lids, no 16oz/22oz).
    - Max 1 box of 16oz or 22oz cups ONLY (>= 2 boxes auto-upgrades to Sedan).
    - Max 1 cup box + 1 lid box combined (2 boxes total).
    - Max 3 boxes of lids ONLY (no cups).
    Microwavables are EXCLUDED from vehicle assignment: they are ignored here
    (never disqualify Motorcycle, never count toward the box totals).
    When the per-size split is known (small_cup_boxes / large_cup_boxes), the
    cups-only branches use it strictly: pure 12oz <= 2, or pure 16oz/22oz <= 1.
    When the split is unknown (legacy single-size orders), fall back to the
    total cup count so 1-2 cup-only boxes still ride Motorcycle.
    """
    cup_boxes = _parse_box_count(cup_boxes)
    lid_boxes = _parse_box_count(lid_boxes)
    # Microwavables excluded from vehicle assignment — ignore entirely.
    if cup_boxes == 0 and 1 <= lid_boxes <= 3:
        return True
    if cup_boxes == 1 and lid_boxes == 1:
        return True
    if lid_boxes == 0 and cup_boxes >= 1 and cup_boxes <= 2:
        # Strict per-size check when the split is available.
        if small_cup_boxes is not None or large_cup_boxes is not None:
            small = _parse_box_count(small_cup_boxes)
            large = _parse_box_count(large_cup_boxes)
            # Pure 12oz, max 2 boxes.
            if large == 0 and 1 <= small <= 2 and small == cup_boxes:
                return True
            # Pure 16oz/22oz, max 1 box.
            if small == 0 and large == 1 and large == cup_boxes:
                return True
            return False
        return True
    return False


def is_sedan_upgrade(total_boxes=0, cup_boxes=0, lid_boxes=0, has_large_cups=False,
                     large_cup_boxes=None):
    """Sedan (P250) upgrade triggers.

    - 2 or more boxes of 16oz or 22oz cups are ordered.
    - Combined cups + lids total exceeds 3 boxes.
    - Overall box count is between 4 and 8 boxes (handled by volume tier,
       but reported here for clarity).
    """
    try:
        total_boxes = int(total_boxes or 0)
    except (TypeError, ValueError):
        total_boxes = 0
    try:
        cups_lids = int(cup_boxes or 0) + int(lid_boxes or 0)
    except (TypeError, ValueError):
        cups_lids = 0
    large_count = _parse_large_cup_boxes(large_cup_boxes)
    if large_count is None:
        # Split unknown: any 16oz/22oz presence + 2+ cups implies 2+ large boxes.
        try:
            cup_total = int(cup_boxes or 0)
        except (TypeError, ValueError):
            cup_total = 0
        if _normalize_has_large_cups(has_large_cups) and cup_total >= 2:
            return True
    elif large_count >= 2:
        return True
    if cups_lids > 3:
        return True
    if 4 <= total_boxes <= 8:
        return True
    return False


def get_shipping_tier(total_boxes, cup_boxes=0, lid_boxes=0, microwavable_boxes=0,
                      has_large_cups=False, cup_size=None, cup_id=None,
                      small_cup_boxes=None, large_cup_boxes=None):
    """Return (fee, vehicle_label, is_dynamic_cod) for an order.

    Content-aware + volume tiers. The third element is always False (kept
    only for backwards compatibility — 41+ boxes is now a P1200 Large Truck,
    never a dynamic-COD flag).
    """
    try:
        cup_boxes = int(cup_boxes or 0)
    except (TypeError, ValueError):
        cup_boxes = 0
    try:
        lid_boxes = int(lid_boxes or 0)
    except (TypeError, ValueError):
        lid_boxes = 0
    try:
        microwavable_boxes = int(microwavable_boxes or 0)
    except (TypeError, ValueError):
        microwavable_boxes = 0
    try:
        total_boxes = int(total_boxes or 0)
    except (TypeError, ValueError):
        total_boxes = 0
    # Normalize the per-size split (None = unknown → size/id/flag fallback).
    small_split = _parse_large_cup_boxes(small_cup_boxes)
    large_split = _parse_large_cup_boxes(large_cup_boxes)
    # Vehicle assignment uses CUPS + LIDS ONLY — microwavables excluded.
    breakdown_total = cup_boxes + lid_boxes
    # Prefer the authoritative per-category breakdown whenever provided.
    total = breakdown_total if breakdown_total > 0 else total_boxes
    # If the caller passed a combined total that includes microwavables,
    # subtract them back out so tiers are computed on cups + lids only.
    if breakdown_total <= 0 and microwavable_boxes > 0 and total_boxes > 0:
        total = max(0, total_boxes - microwavable_boxes)
    if total <= 0:
        return 0.0, '—', False
    large = (
        _normalize_has_large_cups(has_large_cups)
        or _is_large_cup_size(cup_size)
        or _is_large_cup_id(cup_id)
        or (large_split is not None and large_split > 0)
    )
    # Effective large-cup box count: explicit split wins; otherwise infer from
    # the single-size signals (a 16oz/22oz cup row means ALL cup boxes are large).
    effective_large = large_split
    if effective_large is None:
        if cup_boxes > 0 and (_is_large_cup_size(cup_size) or _is_large_cup_id(cup_id)):
            effective_large = cup_boxes
        elif _normalize_has_large_cups(has_large_cups):
            effective_large = cup_boxes if cup_boxes > 0 else 1
        else:
            effective_large = 0
    # Effective small-cup (12oz) box count: explicit split wins; otherwise the
    # remainder of cup boxes not counted as large (so 2x12oz → small=2).
    effective_small = small_split
    if effective_small is None:
        effective_small = max(0, cup_boxes - (effective_large or 0))
    if total >= 41:
        return 1200.0, 'Large Truck', False
    if total >= 19:
        return 600.0, 'L300 / Medium Truck', False
    if total >= 9:
        return 400.0, 'MPV / Small Van', False
    if total >= 4:
        return 250.0, 'Sedan', False
    # 1-3 boxes: content-aware motorcycle vs sedan.
    if is_sedan_upgrade(total, cup_boxes, lid_boxes, large, effective_large):
        return 250.0, 'Sedan', False
    if is_motorcycle_eligible(cup_boxes, lid_boxes, microwavable_boxes,
                              small_cup_boxes=effective_small,
                              large_cup_boxes=effective_large):
        return 120.0, 'Motorcycle', False
    # Fallback: any other small cups+lids order (e.g. 3x 12oz cups-only,
    # 1 cup + 2 lids) rides Sedan — never Motorcycle, never free.
    # (Microwavables are excluded from this decision entirely.)
    return 250.0, 'Sedan', False


def is_gmail_app_password(password):
    """Return True if the configured MAIL_PASSWORD looks like a Google App Password.

    Google App Passwords are exactly 16 characters long (usually displayed in the
    "abcd efgh ijkl mnop" format). A regular Gmail account password does not match
    this format and is rejected by Gmail's SMTP server when sign-in security is on.
    """
    if not password:
        return False
    compact = str(password).replace(' ', '')
    return len(compact) == 16 and compact.isalnum()


def log_email_fallback(recipient, subject, body, reason):
    """Print the full email content to the console when SMTP cannot be used.

    This keeps local development/testing uninterrupted even when Gmail rejects
    the configured credentials.
    """
    print('\n' + '=' * 72)
    print(' SMTP EMAIL FALLBACK - {}'.format(reason))
    print('=' * 72)
    print('To      : {}'.format(recipient))
    print('Subject : {}'.format(subject))
    print('-' * 72)
    print(body)
    print('=' * 72 + '\n')


def send_order_email(recipient, subject, body):
    """Send an order notification when SMTP credentials are configured.

    Email delivery is best-effort: failures (network errors, Gmail rejecting a
    normal account password, missing credentials, ...) never crash the request.
    The full email content is printed to the console as a fallback so testing
    can continue uninterrupted.
    """
    if not recipient or not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        app.logger.warning('Order email skipped: MAIL_USERNAME/MAIL_PASSWORD is not configured.')
        log_email_fallback(recipient, subject, body, 'MAIL_USERNAME/MAIL_PASSWORD is not configured')
        return

    # Gmail only accepts SMTP logins using a Google App Password. A normal Gmail
    # password will be rejected, so detect it early and fall back to console output.
    if not is_gmail_app_password(app.config.get('MAIL_PASSWORD')):
        app.logger.warning(
            'MAIL_PASSWORD does not look like a Google App Password. '
            'Create a 16-character App Password at https://myaccount.google.com/apppasswords '
            'so real SMTP delivery works. Falling back to console output for this email.'
        )
        log_email_fallback(recipient, subject, body, 'MAIL_PASSWORD does not look like a Google App Password')
        return

    try:
        mail.send(Message(subject=subject, recipients=[recipient], body=body))
    except Exception:
        app.logger.exception('Unable to send order email to %s', recipient)
        log_email_fallback(recipient, subject, body, 'SMTP send failed (see exception logged above)')


def order_items_text(order):
    """Build a readable item breakdown for customer notifications."""
    lines = []
    if int(order['cup_boxes'] or 0) > 0:
        cup_label = 'box' if int(order['cup_boxes']) == 1 else 'boxes'
        lines.append(f"Cups: {order['cup_size'] or 'Selected size'} - {order['cup_boxes']} {cup_label}")
    if int(order['lid_boxes'] or 0) > 0:
        lid_label = 'box' if int(order['lid_boxes']) == 1 else 'boxes'
        lines.append(f"Lids: {order['lid_style'] or 'Selected style'} - {order['lid_boxes']} {lid_label}")
    if int(order['microwavable_boxes'] or 0) > 0:
        container_label = 'box' if int(order['microwavable_boxes']) == 1 else 'boxes'
        lines.append(f"Containers: {order['microwavable_size'] or 'Selected size'} - {order['microwavable_boxes']} {container_label}")
    return '\n'.join(lines) or 'No item details available.'

# Inline HTML/CSS template for the official B2B sales invoice PDF.
# xhtml2pdf supports a limited CSS subset, so layout uses tables
# (no flexbox / grid). Rounded corners are approximated with
# bordered padded blocks which xhtml2pdf renders reliably.
INVOICE_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  body { font-family: Helvetica, Arial, sans-serif; color: #1e293b; font-size: 12px; }
  .topbar { width: 100%; margin-bottom: 6px; }
  .topbar td { vertical-align: top; }
  .brand { font-size: 26px; font-weight: bold; color: #4f46e5; margin: 0; }
  .brand-tag { font-size: 10px; font-weight: bold; color: #64748b; margin: 2px 0 0 0; letter-spacing: 1px; }
  .invoice-title { font-size: 20px; font-weight: bold; color: #0f172a; margin: 0; text-align: right; }
  .badge { display: inline-block; background-color: #fef08a; color: #854d0e; font-size: 10px; font-weight: bold; padding: 5px 14px; border: 1px solid #facc15; margin-top: 6px; }
  .badge-wrap { text-align: right; }
  .divider { background-color: #e0e7ff; height: 10px; width: 100%; margin: 10px 0 16px 0; }
  .meta-box { width: 100%; background-color: #f8fafc; border: 1px solid #e2e8f0; margin-bottom: 16px; }
  .meta-box td { vertical-align: top; padding: 12px 14px; width: 50%; }
  .meta-box .col-right { border-left: 1px solid #e2e8f0; }
  .section-label { font-size: 10px; font-weight: bold; color: #4f46e5; margin: 0 0 6px 0; letter-spacing: 1px; }
  .meta-value { margin: 0 0 3px 0; font-size: 12px; }
  .meta-name { margin: 0 0 3px 0; font-size: 13px; font-weight: bold; color: #0f172a; }
  .items { width: 100%; margin: 0 0 14px 0; border: 1px solid #4f46e5; }
  .items th { background-color: #4f46e5; color: #ffffff; text-align: left; padding: 9px 10px; font-size: 10px; font-weight: bold; }
  .items td { padding: 8px 10px; font-size: 12px; }
  .items .row-alt td { background-color: #f8fafc; }
  .items .num { text-align: right; }
  .desc-main { font-weight: bold; color: #0f172a; margin: 0; }
  .desc-sub { color: #64748b; font-size: 11px; margin: 2px 0 0 0; }
  .totals-wrap { width: 100%; margin-bottom: 14px; }
  .totals-wrap td { vertical-align: top; }
  .totals-spacer { width: 50%; }
  .totals { width: 100%; }
  .totals td { padding: 4px 8px; font-size: 12px; }
  .totals .label { text-align: right; color: #475569; }
  .totals .value { text-align: right; font-weight: bold; width: 130px; }
  .total-due td { background-color: #eef2ff; border-top: 2px solid #4f46e5; border-bottom: 2px solid #4f46e5; font-size: 13px; font-weight: bold; color: #0f172a; padding: 8px; }
  .payment-row td { padding: 4px 8px; font-size: 12px; }
  .payment-due td { background-color: #ecfdf5; border-top: 2px solid #059669; font-size: 13px; font-weight: bold; color: #065f46; padding: 8px; }
  .payment-balance td { background-color: #fffbeb; border-bottom: 2px solid #d97706; font-size: 12px; font-weight: bold; color: #92400e; padding: 8px; }
  .pay-box { border: 1px dashed #4f46e5; background-color: #f8fafc; padding: 12px 14px; margin-bottom: 12px; }
  .pay-title { font-size: 11px; font-weight: bold; color: #0f172a; margin: 0 0 8px 0; letter-spacing: 1px; }
  .pay-cards { width: 100%; }
  .pay-cards td { width: 33%; vertical-align: top; padding-right: 8px; }
  .pay-cards .last { padding-right: 0; }
  .pay-card { background-color: #ffffff; border: 1px solid #e2e8f0; padding: 9px 10px; }
  .pay-card-title { font-size: 11px; font-weight: bold; color: #4f46e5; margin: 0 0 4px 0; }
  .pay-card p { margin: 0; font-size: 11px; color: #334155; }
  .delivery-note { font-size: 10px; color: #475569; margin: 0 0 12px 0; }
  .footer { margin-top: 16px; border-top: 1px solid #cbd5e1; padding-top: 8px; font-size: 10px; color: #64748b; text-align: center; }
</style>
</head>
<body>
  <table class="topbar">
    <tr>
      <td>
        <p class="brand">Pack &amp; Sip</p>
        <p class="brand-tag">WHOLESALE CUPS, LIDS &amp; CONTAINERS</p>
      </td>
      <td>
        <p class="invoice-title">SALES INVOICE</p>
        <p class="badge-wrap"><span class="badge">PENDING PAYMENT</span></p>
      </td>
    </tr>
  </table>
  <div class="divider"></div>
  <table class="meta-box">
    <tr>
      <td>
        <p class="section-label">BILLED TO</p>
        <p class="meta-name">{{ customer_name }}</p>
        <p class="meta-value">{{ customer_email }}</p>
        <p class="meta-value">{{ customer_phone }}</p>
      </td>
      <td class="col-right">
        <p class="section-label">ORDER REFERENCE</p>
        <p class="meta-value">Order Number: <strong>#{{ order_id }}</strong></p>
        <p class="meta-value">Date: {{ order_date }}</p>
        <p class="meta-value">Delivery Method: {{ delivery_method_display }}</p>
        <p class="meta-value">Fulfillment Mode: {{ fulfillment_mode }}</p>
      </td>
    </tr>
  </table>
  <table class="items">
    <tr><th>ITEM DESCRIPTION</th><th>QUANTITY</th><th>UNIT PRICE</th><th>TOTAL AMOUNT</th></tr>
    {% for item in items %}
    <tr{% if loop.index0 % 2 == 1 %} class="row-alt"{% endif %}>
      <td><p class="desc-main">{{ item.name }}</p><p class="desc-sub">{{ item.details }}</p></td>
      <td class="num">{{ item.quantity }}</td>
      <td class="num">P{{ "%.2f"|format(item.unit_price) }}</td>
      <td class="num">P{{ "%.2f"|format(item.line_total) }}</td>
    </tr>
    {% endfor %}
  </table>
  <table class="totals-wrap">
    <tr>
      <td class="totals-spacer"></td>
      <td>
        <table class="totals">
          <tr><td class="label">Subtotal</td><td class="value">P{{ "%.2f"|format(subtotal) }}</td></tr>
          {% if is_self_booking %}
          <tr><td class="label">Shipping Fee</td><td class="value">{{ shipping_display }}</td></tr>
          {% else %}
          <tr><td class="label">Shipping ({{ shipping_label }}) — {{ total_boxes }} box{{ 'es' if total_boxes != 1 else '' }} (cups + lids; microwavables excluded)</td><td class="value">{{ shipping_display }}</td></tr>
          {% endif %}
          <tr><td class="label">Tax</td><td class="value">P{{ "%.2f"|format(tax_fee) }}</td></tr>
          <tr class="total-due"><td class="label"><strong>Grand Total (Subtotal + Shipping + Tax)</strong></td><td class="value">P{{ "%.2f"|format(total_due) }}</td></tr>
          {% if payment_option == 'downpayment' %}
          <tr class="payment-row"><td class="label">Downpayment (50% of Subtotal)</td><td class="value">P{{ "%.2f"|format(downpayment_base) }}</td></tr>
          {% if is_self_booking %}
          <tr class="payment-row"><td class="label">Shipping Fee (Customer Self-Booking — no courier fee)</td><td class="value">P0.00</td></tr>
          {% else %}
          <tr class="payment-row"><td class="label">Shipping Fee ({{ shipping_label }} — paid 100% upfront)</td><td class="value">P{{ "%.2f"|format(shipping_fee) }}</td></tr>
          {% endif %}
          <tr class="payment-due"><td class="label"><strong>Initial Amount Due Now (Downpayment + Full Shipping)</strong></td><td class="value">P{{ "%.2f"|format(amount_due_now) }}</td></tr>
          <tr class="payment-balance"><td class="label"><strong>Remaining Balance (on delivery)</strong></td><td class="value">P{{ "%.2f"|format(remaining_balance) }}</td></tr>
          {% else %}
          <tr class="payment-row"><td class="label">Full Payment (Subtotal)</td><td class="value">P{{ "%.2f"|format(subtotal) }}</td></tr>
          {% if is_self_booking %}
          <tr class="payment-row"><td class="label">Shipping Fee (Customer Self-Booking — no courier fee)</td><td class="value">P0.00</td></tr>
          {% else %}
          <tr class="payment-row"><td class="label">Shipping Fee ({{ shipping_label }} — paid 100% upfront)</td><td class="value">P{{ "%.2f"|format(shipping_fee) }}</td></tr>
          {% endif %}
          <tr class="payment-due"><td class="label"><strong>Initial Amount Due Now (Full Payment)</strong></td><td class="value">P{{ "%.2f"|format(amount_due_now) }}</td></tr>
          <tr class="payment-balance"><td class="label"><strong>Remaining Balance</strong></td><td class="value">P{{ "%.2f"|format(remaining_balance) }}</td></tr>
          {% endif %}
        </table>
      </td>
    </tr>
  </table>
  {% if is_self_booking %}
  <p class="delivery-note">{{ delivery_note }}</p>
  {% endif %}
  <div class="pay-box">
    <p class="pay-title">PAYMENT INSTRUCTIONS</p>
    <table class="pay-cards">
      <tr>
        <td><div class="pay-card"><p class="pay-card-title">GCash</p><p>Account: Pack &amp; Sip<br />0912 345 6789</p></div></td>
        <td><div class="pay-card"><p class="pay-card-title">Maya</p><p>Account: Pack &amp; Sip<br />0912 345 6789</p></div></td>
        <td class="last"><div class="pay-card"><p class="pay-card-title">BDO Bank Transfer</p><p>Account: Pack &amp; Sip<br />0012 3456 7890</p></div></td>
      </tr>
    </table>
  </div>
  <p class="footer">Thank you for ordering from Pack &amp; Sip. This is your official order receipt.</p>
</body>
</html>
"""


def _invoice_row(item, details, qty, unit_price, stripe=False):
    line_total = round(float(unit_price or 0) * int(qty or 0), 2)
    row_class = ' class="row-alt"' if stripe else ''
    return (
        f"<tr{row_class}>"
        f"<td><p class=\"desc-main\">{html.escape(str(item))}</p>"
        f"<p class=\"desc-sub\">{html.escape(str(details))}</p></td>"
        f"<td class=\"num\">{int(qty or 0)}</td>"
        f"<td class=\"num\">P{float(unit_price or 0):,.2f}</td>"
        f"<td class=\"num\">P{line_total:,.2f}</td>"
        "</tr>"
    )


def invoice_item_rows(order, unit_prices):
    """Build the item table rows for the invoice PDF from dynamic order data."""
    rows = []
    if int(order['cup_boxes'] or 0) > 0:
        rows.append(_invoice_row('Cups', order['cup_size'] or 'Selected size', order['cup_boxes'], unit_prices.get('cup', 0), stripe=len(rows) % 2 == 1))
    if int(order['lid_boxes'] or 0) > 0:
        rows.append(_invoice_row('Lids', order['lid_style'] or 'Selected style', order['lid_boxes'], unit_prices.get('lid', 0), stripe=len(rows) % 2 == 1))
    if int(order['microwavable_boxes'] or 0) > 0:
        rows.append(_invoice_row('Microwavable Containers', order['microwavable_size'] or 'Selected size', order['microwavable_boxes'], unit_prices.get('microwavable', MICROWAVABLE_PRICE_PER_BOX), stripe=len(rows) % 2 == 1))
    if not rows:
        rows.append('<tr><td colspan="4">No item details available.</td></tr>')
    return "".join(rows)


def _order_field_static(order, key, default=''):
    """Read order[key] safely for dicts and sqlite3.Row objects."""
    try:
        value = order[key]
        return default if value is None else value
    except Exception:
        try:
            getter = getattr(order, 'get', None)
            if callable(getter):
                value = getter(key, default)
                return default if value is None else value
        except Exception:
            pass
        return default


def render_invoice_html(order, unit_prices, upload_link=None, shipping_fee=None, tax_fee=0.0, shipping_label=None, is_dynamic_cod=False, delivery_method=None):
    """Render the inline invoice template using dynamic order data.

    subtotal is strictly the sum of items (quantity * unit_price, INCLUDING
    microwavables). shipping_fee defaults to the content-aware tier computed
    on CUPS + LIDS ONLY (microwavables excluded from vehicle assignment):
    1-3 boxes: Motorcycle P120 only for 12oz<=2 / 16oz-22oz<=1 / 1cup+1lid /
    lids-only<=3, else Sedan P250; 4-8: P250 Sedan; 9-18: P400 MPV/Small Van;
    19-40: P600 L300/Medium Truck; 41+: P1200 Large Truck);
    total_due = subtotal + shipping_fee + tax_fee.
    Payment breakdown:
      - Downpayment (50%): amount_due_now = (subtotal * 0.50) + FULL
        shipping_fee, remaining_balance = subtotal * 0.50.
      - Full payment: amount_due_now = subtotal + FULL shipping_fee (+ tax),
        remaining_balance = 0.00.
    Delivery Method (cart checkout flow):
      - 'standard'     -> Standard Delivery (Ship via Pack & Sip Courier): the
        content-aware box-tier shipping fee above applies.
      - 'self_booking' -> Customer Self-Booking / Warehouse Pick-up: the
        Shipping Fee is forced to P0.00 and the invoice renders
        'Shipping Fee | P0.00 (Customer Self-Booking)'.
    The template itself uses Jinja variables (no hardcoded summary values).
    """
    raw_created = str(order['created_at'] or '')
    try:
        order_date = datetime.datetime.fromisoformat(raw_created).strftime('%Y-%m-%d')
    except ValueError:
        order_date = raw_created[:10] if len(raw_created) >= 10 else raw_created
    items = []
    if int(order['cup_boxes'] or 0) > 0:
        unit_price = float(unit_prices.get('cup', 0) or 0)
        quantity = int(order['cup_boxes'] or 0)
        items.append({
            'name': 'Cups',
            'details': order['cup_size'] or 'Selected size',
            'quantity': quantity,
            'unit_price': unit_price,
            'line_total': round(quantity * unit_price, 2),
        })
    if int(order['lid_boxes'] or 0) > 0:
        unit_price = float(unit_prices.get('lid', 0) or 0)
        quantity = int(order['lid_boxes'] or 0)
        items.append({
            'name': 'Lids',
            'details': order['lid_style'] or 'Selected style',
            'quantity': quantity,
            'unit_price': unit_price,
            'line_total': round(quantity * unit_price, 2),
        })
    if int(order['microwavable_boxes'] or 0) > 0:
        unit_price = float(unit_prices.get('microwavable', MICROWAVABLE_PRICE_PER_BOX) or 0)
        quantity = int(order['microwavable_boxes'] or 0)
        items.append({
            'name': 'Microwavable Containers',
            'details': order['microwavable_size'] or 'Selected size',
            'quantity': quantity,
            'unit_price': unit_price,
            'line_total': round(quantity * unit_price, 2),
        })
    subtotal = round(sum(item['line_total'] for item in items), 2)
    total_boxes = sum(item['quantity'] for item in items)
    # Content-aware tier needs per-category boxes + cup sizeBulky signal.
    # Re-derive from the order row so invoice regeneration matches checkout.
    try:
        inv_cup_boxes = int(_order_field_static(order, 'cup_boxes', 0) or 0)
    except (TypeError, ValueError):
        inv_cup_boxes = 0
    try:
        inv_lid_boxes = int(_order_field_static(order, 'lid_boxes', 0) or 0)
    except (TypeError, ValueError):
        inv_lid_boxes = 0
    try:
        inv_micro_boxes = int(_order_field_static(order, 'microwavable_boxes', 0) or 0)
    except (TypeError, ValueError):
        inv_micro_boxes = 0
    inv_cup_size = _order_field_static(order, 'cup_size', '')
    # Cups + lids drive the vehicle tier; microwavables are excluded from the
    # tier decision (but still appear as invoice line items + in the subtotal).
    vehicle_boxes = inv_cup_boxes + inv_lid_boxes
    # Delivery Method for this invoice: an explicit argument (checkout flow) wins,
    # otherwise fall back to the value stored on the order row.
    if delivery_method is None:
        delivery_method = _order_field_static(order, 'delivery_method', '')
    delivery_method = normalize_delivery_method(delivery_method)
    self_booking = is_self_booking(delivery_method)
    if shipping_fee is None or shipping_label is None:
        tier_fee, tier_label, tier_dynamic = get_shipping_tier(
            vehicle_boxes,
            cup_boxes=inv_cup_boxes,
            lid_boxes=inv_lid_boxes,
            microwavable_boxes=inv_micro_boxes,
            has_large_cups=_is_large_cup_size(inv_cup_size),
        )
        if shipping_fee is None:
            shipping_fee = tier_fee
        if shipping_label is None:
            shipping_label = tier_label
            is_dynamic_cod = tier_dynamic
    # Customer Self-Booking / Warehouse Pick-up always ships at P0.00: the
    # customer books their own rider (Lalamove/Grab) once the order status is
    # updated to 'Ready for Pick-up'.
    shipping_fee, shipping_label, is_dynamic_cod = apply_delivery_method(
        shipping_fee, shipping_label, is_dynamic_cod, delivery_method
    )
    shipping_fee = round(float(shipping_fee or 0), 2)
    if is_dynamic_cod:
        # Legacy flag only — current tiers always prepay the full fee.
        shipping_label = shipping_label or 'Large Truck'
    else:
        shipping_label = shipping_label or 'Motorcycle'
    if self_booking:
        shipping_label = SELF_BOOKING_SHIPPING_LABEL
        is_dynamic_cod = False
        shipping_display = 'P0.00 (Customer Self-Booking)'
    else:
        shipping_display = 'P%.2f' % shipping_fee
    tax_fee = round(float(tax_fee or 0), 2)
    total_due = round(subtotal + shipping_fee + tax_fee, 2)
    # Payment breakdown — the FULL applicable tier shipping fee is always added
    # in full to the initial payment requirement.
    def _order_field(key, default=''):
        try:
            value = order[key]
            return default if value is None else value
        except Exception:
            try:
                getter = getattr(order, 'get', None)
                if callable(getter):
                    value = getter(key, default)
                    return default if value is None else value
            except Exception:
                pass
            return default
    payment_method_label = str(_order_field('payment_method', ''))
    try:
        stored_remaining = float(_order_field('remaining_balance', 0) or 0)
    except (TypeError, ValueError):
        stored_remaining = 0.0
    is_downpayment = 'downpayment' in payment_method_label.lower() or stored_remaining > 0
    if is_downpayment:
        payment_option = 'downpayment'
        downpayment_base = round(subtotal * 0.50, 2)
        amount_due_now = round(downpayment_base + shipping_fee + tax_fee, 2)
        remaining_balance = round(subtotal * 0.50, 2)
    else:
        payment_option = 'full'
        downpayment_base = round(subtotal, 2)
        amount_due_now = round(subtotal + shipping_fee + tax_fee, 2)
        remaining_balance = 0.0
    with app.app_context():
        return render_template_string(
            INVOICE_HTML_TEMPLATE,
            customer_name=order['customer_name'] or '',
            customer_email=order['email'] or '',
            customer_phone=order['customer_phone'] or '',
            order_id=order['id'],
            order_date=order_date,
            items=items,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            shipping_label=shipping_label,
            shipping_display=shipping_display,
            total_boxes=total_boxes,
            is_dynamic_cod=is_dynamic_cod,
            delivery_method=delivery_method,
            delivery_method_display=delivery_method_label(delivery_method),
            is_self_booking=self_booking,
            fulfillment_mode=(SELF_BOOKING_DELIVERY_LABEL if self_booking else 'Lalamove Local Courier'),
            delivery_note=(SELF_BOOKING_NOTE if self_booking else ''),
            tax_fee=tax_fee,
            total_due=total_due,
            payment_option=payment_option,
            downpayment_base=downpayment_base,
            amount_due_now=amount_due_now,
            remaining_balance=remaining_balance,
        )


def build_invoice_pdf(invoice_html):
    """Convert the rendered invoice HTML string into a PDF byte stream."""
    pdf_buffer = io.BytesIO()
    result = pisa.CreatePDF(io.StringIO(invoice_html), dest=pdf_buffer)
    if result.err:
        raise RuntimeError('Unable to generate the invoice PDF.')
    return pdf_buffer.getvalue()

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

    # Seed initial data if table is empty
    cursor.execute('SELECT COUNT(*) FROM products')
    if cursor.fetchone()[0] == 0:
        initial_products = [
            ('cup-12oz', 'cup', 'Cups — 12 oz (Box of 1,250)', '12oz', None, 1250, 45.0, 50, 'Durable 12oz disposable cups.'),
            ('cup-16oz', 'cup', 'Cups — 16 oz (Box of 1,250)', '16oz', None, 1250, 45.0, 40, 'Classic 16oz disposable cups.'),
            ('cup-22oz', 'cup', 'Cups — 22 oz (Box of 1,250)', '22oz', None, 1250, 45.0, 25, 'Large 22oz disposable cups.'),
            ('lid-strawless', 'lid', 'Lids — Strawless (Box of 1,250)', None, 'Strawless', 1250, 25.0, 60, 'Strawless lids — universal fit.'),
            ('lid-dome', 'lid', 'Lids — Dome (Box of 1,250)', None, 'Dome', 1250, 25.0, 30, 'Dome lids — universal fit.'),
            ('lid-flat', 'lid', 'Lids — Flat (Box of 1,250)', None, 'Flat', 1250, 25.0, 15, 'Flat lids — universal fit.')
        ]
        cursor.executemany('''
            INSERT INTO products (id, type, name, size, style, quantity_per_box, price_per_box, stock_boxes, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', initial_products)
        conn.commit()

    microwavable_products = [
        ('container-re-3200', 'microwavable', 'RE 3200 Rectangular Container (3,200ml)', '3,200ml', 'RE Series', 100, 1800.0, 20, 'Microwavable rectangular container with a 3,200ml capacity.'),
        ('container-re-2500', 'microwavable', 'RE 2500 Rectangular Container (2,500ml)', '2,500ml', 'RE Series', 100, 1600.0, 20, 'Microwavable rectangular container with a 2,500ml capacity.'),
        ('container-re-1600', 'microwavable', 'RE 1600 Rectangular Container (1,600ml)', '1,600ml', 'RE Series', 100, 1400.0, 20, 'Microwavable rectangular container with a 1,600ml capacity.'),
        ('container-re-1000', 'microwavable', 'RE 1000 Rectangular Container (1,000ml)', '1,000ml', 'RE Series', 100, 1200.0, 20, 'Microwavable rectangular container with a 1,000ml capacity.'),
        ('container-re-750', 'microwavable', 'RE 750 Rectangular Container (750ml)', '750ml', 'RE Series', 100, 950.0, 20, 'Microwavable rectangular container with a 750ml capacity.'),
        ('container-re-500', 'microwavable', 'RE 500 Rectangular Container (500ml)', '500ml', 'RE Series', 100, 800.0, 20, 'Microwavable rectangular container with a 500ml capacity.'),
        ('container-ro-30', 'microwavable', 'RO 30 Round Container (30 oz)', '30oz', 'RO Series', 100, 1100.0, 20, 'Microwavable round container with a 30oz capacity.'),
        ('container-ro-16', 'microwavable', 'RO 16 Round Container (16 oz)', '16oz', 'RO Series', 100, 900.0, 20, 'Microwavable round container with a 16oz capacity.'),
        ('container-ro-10', 'microwavable', 'RO 10 Round Container (10 oz)', '10oz', 'RO Series', 100, 750.0, 20, 'Microwavable round container with a 10oz capacity.')
    ]
    cursor.executemany('''
        INSERT OR IGNORE INTO products (id, type, name, size, style, quantity_per_box, price_per_box, stock_boxes, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', microwavable_products)
    conn.commit()

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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            customer_name TEXT NOT NULL,
            email TEXT,
            customer_address TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Cash on Delivery',
            delivery_method TEXT NOT NULL DEFAULT 'standard',
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
        # Delivery Method: 'standard' (Pack & Sip courier, box-tier fee) or
        # 'self_booking' (Customer Self-Booking / Warehouse Pick-up, P0.00).
        cursor.execute("ALTER TABLE orders ADD COLUMN delivery_method TEXT NOT NULL DEFAULT 'standard'")
    if 'user_id' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if 'total_amount' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN total_amount REAL NOT NULL DEFAULT 0")
    if 'created_at' not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN created_at TEXT")
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


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/api/products', methods=['GET'])
def get_products():
    """Fetch all products from SQLite database."""
    conn = get_db()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()

    result = []
    for p in products:
        item = dict(p)
        # Compatible sizes for universal lids
        if item['type'] == 'lid':
            item['compatible_sizes'] = ["12oz", "16oz", "22oz"]
        item['in_stock'] = item['stock_boxes'] > 0
        result.append(item)

    return jsonify({"products": result})


@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)


@app.route('/manage-orders-ps.html', methods=['GET'])
def admin_dashboard():
    """Render the order management dashboard."""
    return render_template('manage-orders-ps.html')


@app.route('/api/admin/orders', methods=['GET'])
def get_admin_orders():
    """Fetch all orders for the admin dashboard, newest first."""
    conn = get_db()
    orders = conn.execute('''
        SELECT
            id,
            customer_name AS full_name,
            email,
            customer_phone AS phone_number,
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
            COALESCE(delivery_method, 'standard') AS delivery_method
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
    previous_order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not previous_order:
        conn.close()
        return jsonify({"error": "Order not found."}), 404

    cursor = conn.execute(
        'UPDATE orders SET status = ? WHERE id = ?',
        (status, order_id)
    )
    conn.commit()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()

    if status in {'Shipping', 'Shipped'} and previous_order['status'] not in {'Shipping', 'Shipped'}:
        send_order_email(
            order['email'],
            f"Your Pack & Sip Order #{order_id} is On Its Way via Lalamove!",
            f"Hello {order['customer_name']},\n\n"
            f"We have confirmed receipt of your payment for Pack & Sip order #{order_id}. "
            "Your package has been booked and dispatched to your shipping address via a Lalamove driver delivery.\n\n"
            f"Shipping address:\n{order['customer_address']}\n\n"
            "Thank you for choosing Pack & Sip."
        )
    elif status == SELF_BOOKING_STATUS and previous_order['status'] != SELF_BOOKING_STATUS:
        # Customer Self-Booking / Warehouse Pick-up: no Pack & Sip courier is
        # booked, so the customer arranges their own rider (Lalamove/Grab).
        send_order_email(
            order['email'],
            f"Your Pack & Sip Order #{order_id} is {SELF_BOOKING_STATUS}!",
            f"Hello {order['customer_name']},\n\n"
            f"Pack & Sip order #{order_id} is now marked '{SELF_BOOKING_STATUS}'.\n\n"
            f"{SELF_BOOKING_NOTE}\n\n"
            f"Order Details:\n{order_items_text(order)}\n\n"
            f"Total Amount: ₱{float(order['total_amount'] or 0):.2f}\n\n"
            "Thank you for choosing Pack & Sip."
        )

    return jsonify({"order": dict(order)})


@app.route('/admin/ship-order/<int:order_id>', methods=['POST'])
def admin_ship_order(order_id):
    """Verify payment receipt and mark the order ready for fulfillment.

    Standard Delivery orders are marked 'Shipping'; Customer Self-Booking /
    Warehouse Pick-up orders are marked 'Ready for Pick-up' instead (no Pack &
    Sip courier is booked — the customer arranges their own rider).
    """
    conn = get_db()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "Order not found."}), 404

    self_booking = is_self_booking(_order_field_static(order, 'delivery_method', ''))
    new_status = SELF_BOOKING_STATUS if self_booking else 'Shipping'

    conn.execute(
        'UPDATE orders SET status = ?, payment_status = ? WHERE id = ?',
        (new_status, 'Verified', order_id)
    )
    conn.commit()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()

    if self_booking:
        email_subject = f"Payment Verified - Pack & Sip Order #{order_id} is {SELF_BOOKING_STATUS}"
        email_body = (
            f"Hello {order['customer_name']},\n\n"
            f"We have verified your payment proof for Pack & Sip order #{order_id}.\n"
            f"Your payment status is now Verified, and your order status is updated to {SELF_BOOKING_STATUS}.\n\n"
            f"{SELF_BOOKING_NOTE}\n\n"
            f"Order Details:\n"
            f"{order_items_text(order)}\n\n"
            f"Total Amount: ₱{order['total_amount']:.2f}\n"
            f"Shipping Fee: ₱0.00 (Customer Self-Booking)\n"
            f"Remaining Balance upon Pick-up: ₱{order['remaining_balance']:.2f}\n\n"
            "Thank you for choosing Pack & Sip."
        )
    else:
        email_subject = f"Payment Received & Order Shipped! - Pack & Sip (Order #{order_id})"
        email_body = (
            f"Hello {order['customer_name']},\n\n"
            f"We have verified your payment proof for Pack & Sip order #{order_id}.\n"
            f"Your payment status is now Verified, and your order status is updated to Shipping.\n\n"
            f"Your package has been prepared and dispatched to your shipping address via a Lalamove driver delivery.\n\n"
            f"Shipping address:\n{order['customer_address']}\n\n"
            f"Order Details:\n"
            f"{order_items_text(order)}\n\n"
            f"Total Amount: ₱{order['total_amount']:.2f}\n"
            f"Remaining Balance upon Delivery: ₱{order['remaining_balance']:.2f}\n\n"
            "Thank you for choosing Pack & Sip."
        )

    # Flask-Mail's mail.send() needs the Flask application context, which is not
    # available in a background thread by default.
    def send_fulfillment_email():
        with app.app_context():
            send_order_email(order['email'], email_subject, email_body)

    threading.Thread(target=send_fulfillment_email, daemon=True).start()

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

    # Delivery Method: 'standard' keeps the box tier (P120-P1200);
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
    # Content-aware tier: box breakdown + per-size 12oz vs 16oz/22oz split.
    # Vehicle assignment uses CUPS + LIDS ONLY — microwavables excluded.
    total_boxes = cup_boxes + lid_boxes + microwavable_boxes
    vehicle_boxes = cup_boxes + lid_boxes
    cup_row = None
    if cup_id and cup_boxes > 0:
        cup_row = conn.execute('SELECT size FROM products WHERE id = ?', (cup_id,)).fetchone()
    cup_size_db = cup_row['size'] if cup_row and cup_row['size'] else None
    has_large = (
        _is_large_cup_id(cup_id) if (cup_id and cup_boxes > 0)
        else False
    ) or (
        _is_large_cup_size(cup_size_db) if cup_size_db else False
    )
    if str(data.get('has_large_cups') or '').strip() != '':
        has_large = has_large or _normalize_has_large_cups(data.get('has_large_cups'))
    # Per-size split: explicit counts win; otherwise infer (a 16oz/22oz cup row
    # means ALL cup boxes are large, a 12oz row means ALL are small).
    small_split = _parse_large_cup_boxes(data.get('small_cup_boxes'))
    large_split = _parse_large_cup_boxes(data.get('large_cup_boxes'))
    if small_split is None and large_split is None and cup_boxes > 0:
        if _is_large_cup_size(cup_size_db) or _is_large_cup_id(cup_id):
            small_split, large_split = 0, cup_boxes
        elif not has_large:
            small_split, large_split = cup_boxes, 0
    shipping, shipping_label, is_dynamic_cod = get_shipping_tier(
        vehicle_boxes,
        cup_boxes=cup_boxes,
        lid_boxes=lid_boxes,
        microwavable_boxes=microwavable_boxes,
        has_large_cups=has_large,
        cup_id=cup_id if cup_boxes > 0 else None,
        cup_size=cup_size_db,
        small_cup_boxes=small_split,
        large_cup_boxes=large_split,
    )
    if subtotal <= 0:
        shipping, shipping_label, is_dynamic_cod = 0.0, '—', False
    # Delivery Method: Standard Delivery keeps the content-aware box tier;
    # Customer Self-Booking / Warehouse Pick-up always ships at P0.00.
    shipping, shipping_label, is_dynamic_cod = apply_delivery_method(
        shipping, shipping_label, is_dynamic_cod, delivery_method
    )
    shipping = round(shipping, 2)
    shipping_display = 'P%.2f' % shipping
    if is_self_booking(delivery_method):
        shipping_display = 'P0.00 (Customer Self-Booking)'
    total = round(subtotal + shipping, 2)

    # Close the read-only connection only after the per-size cup lookup above.
    conn.close()

    return jsonify({
        "items": items,
        "subtotal": subtotal,
        "shipping": shipping,
        "shipping_label": shipping_label,
        "shipping_display": shipping_display,
        "total_boxes": total_boxes,
        "is_dynamic_cod": is_dynamic_cod,
        "delivery_method": delivery_method,
        "delivery_method_label": delivery_method_label(delivery_method),
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

    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    address = (data.get('address') or '').strip()
    phone = (data.get('phone') or '').strip()
    payment_type = (data.get('payment_type') or '50_percent').strip()
    payment_method = (data.get('payment_method') or '').strip()
    if not payment_method:
        payment_method = 'GCash (50% Downpayment)' if payment_type == '50_percent' else 'GCash (Full Payment)'
    # Delivery Method radio group (defaults to Standard Delivery when absent).
    delivery_method = normalize_delivery_method(data.get('delivery_method'))
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

    if not name or not email or not address or not phone:
        return jsonify({"error": "Customer name, email, address and phone are required."}), 400

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
    subtotal += MICROWAVABLE_PRICE_PER_BOX * microwavable_boxes

    subtotal = round(subtotal, 2)
    # Content-aware shipping tier based on box breakdown + cup size.
    # FULL tier fee is always charged upfront, even for 50% downpayment:
    #   Initial Amount Due = (Subtotal * 0.50) + Full Shipping Fee.
    # Vehicle assignment uses CUPS + LIDS ONLY — microwavables excluded
    # (they still count in the order subtotal/total, just not the vehicle).
    total_boxes = cup_boxes + lid_boxes + microwavable_boxes
    vehicle_boxes = cup_boxes + lid_boxes
    checkout_large = (
        _is_large_cup_size(cup_size)
        or (_is_large_cup_id(cup_id) if cup_boxes > 0 else False)
        or _normalize_has_large_cups(data.get('has_large_cups'))
    )
    # Per-size split: explicit counts win; otherwise infer from the cup row
    # (legacy single-size orders carry one cup_size for all cup boxes).
    co_small = _parse_large_cup_boxes(data.get('small_cup_boxes'))
    co_large = _parse_large_cup_boxes(data.get('large_cup_boxes'))
    if co_small is None and co_large is None and cup_boxes > 0:
        if _is_large_cup_size(cup_size) or (_is_large_cup_id(cup_id) if cup_boxes > 0 else False):
            co_small, co_large = 0, cup_boxes
        elif not checkout_large:
            co_small, co_large = cup_boxes, 0
    shipping, shipping_label, is_dynamic_cod = get_shipping_tier(
        vehicle_boxes,
        cup_boxes=cup_boxes,
        lid_boxes=lid_boxes,
        microwavable_boxes=microwavable_boxes,
        has_large_cups=checkout_large,
        cup_size=cup_size,
        cup_id=cup_id if cup_boxes > 0 else None,
        small_cup_boxes=co_small,
        large_cup_boxes=co_large,
    )
    if subtotal <= 0:
        shipping, shipping_label, is_dynamic_cod = 0.0, '—', False
    # Delivery Method: Standard Delivery (Ship via Pack & Sip Courier) keeps the
    # content-aware box-tier fee; Customer Self-Booking / Warehouse Pick-up
    # always ships at P0.00 (no Pack & Sip courier is booked).
    shipping, shipping_label, is_dynamic_cod = apply_delivery_method(
        shipping, shipping_label, is_dynamic_cod, delivery_method
    )
    shipping = round(shipping, 2)
    total = round(subtotal + shipping, 2)
    if payment_type == 'full':
        # Full payment: everything (subtotal + FULL tier shipping) is due now.
        downpayment_amount = round(total, 2)
        remaining_balance = 0.0
        payment_status = 'Full Payment Pending'
    else:
        # Downpayment (50%): initial due = (subtotal * 50%) + FULL tier shipping;
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
            INSERT INTO orders (user_id, customer_name, email, customer_address, customer_phone, payment_method, delivery_method, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total_amount, downpayment_amount, remaining_balance, payment_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, name, email, address, phone, payment_method, delivery_method, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total, downpayment_amount, remaining_balance, payment_status, created_at))


        order_id = cursor.lastrowid
        conn.commit()
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": f"Failed to process order: {str(e)}"}), 500

    conn.close()

    email_subject = "Order Received - Pack & Sip"
    # Construct base URL for the receipt upload link
    base_url = request.host_url.rstrip('/')
    upload_link = f"{base_url}/upload-receipt?order_id={order_id}"

    # Render the official B2B invoice HTML from dynamic order data and
    # convert it into a PDF byte stream for the email attachment.
    # subtotal = sum(items); total_due = subtotal + tier shipping_fee.
    invoice_filename = f"PackAndSip_Invoice_Order_{order_id}.pdf"
    try:
        invoice_html = render_invoice_html(
            dict(order), unit_prices, upload_link,
            shipping_fee=shipping,
            shipping_label=shipping_label,
            is_dynamic_cod=is_dynamic_cod,
            delivery_method=delivery_method,
        )
        invoice_pdf_bytes = build_invoice_pdf(invoice_html)
    except Exception as e:
        print(f"Invoice PDF Error: {e}")
        invoice_pdf_bytes = None

    email_body = "Thank you for ordering from Pack & Sip. Your official order receipt is attached below as a PDF."

    # Send the order confirmation email asynchronously in a background thread.
    # This keeps the checkout response snappy: the DB insert commits and the
    # success JSON is returned immediately, without waiting for SMTP network
    # response times. Any mail error is still printed to the terminal.
    def send_confirmation_email():
        # Flask-Mail's mail.send() needs the Flask application context, which
        # is not available in this background thread by default.
        with app.app_context():
            try:
                msg = Message(
                    subject=email_subject,
                    recipients=[order['email']],
                    body=email_body
                )
                if invoice_pdf_bytes:
                    msg.attach(invoice_filename, 'application/pdf', invoice_pdf_bytes)
                mail.send(msg)
            except Exception as e:
                print(f"Mail Error: {e}")

    threading.Thread(target=send_confirmation_email, daemon=True).start()

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": "Order processed successfully!",
        "payment_method": payment_method,
        "delivery_method": delivery_method,
        "delivery_method_label": delivery_method_label(delivery_method),
        "shipping": shipping,
        "total": total,
        "downpayment_amount": downpayment_amount,
        "remaining_balance": remaining_balance,
        "payment_status": payment_status
    })


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
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4">
            <div class="bg-white p-8 rounded-xl shadow-lg max-w-md w-full">
                <h1 class="text-2xl font-bold mb-4 text-indigo-700">Upload Payment Receipt</h1>
                <p class="text-slate-600 mb-6 text-sm">Please upload your GCash/Maya screenshot for Order #{{ order_id }}</p>
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
    return jsonify({"inventory": [dict(p) for p in products]})


@app.route('/api/admin/update-stock', methods=['POST'])
def update_stock():
    """Update stock_boxes for a specific product."""
    data = request.get_json(force=True, silent=True) or {}
    product_id = data.get('product_id')
    try:
        new_stock = int(data.get('new_stock', 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid stock value"}), 400

    if not product_id:
        return jsonify({"error": "Product ID required"}), 400

    conn = get_db()
    cursor = conn.execute('UPDATE products SET stock_boxes = ? WHERE id = ?', (new_stock, product_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    if not success:
        return jsonify({"error": "Product not found"}), 404

    return jsonify({"success": True, "message": "Stock updated successfully"})


if __name__ == '__main__':

    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)