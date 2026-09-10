import sqlite3
import os
import datetime
import threading
from flask import Flask, jsonify, render_template, request, send_from_directory, session, render_template_string
from werkzeug.utils import secure_filename

from flask_cors import CORS
from flask_mail import Mail, Message
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, template_folder='.')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'pack-sip-development-secret')
CORS(app, supports_credentials=True)

app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.getenv('MAIL_USERNAME'),
    MAIL_PASSWORD=os.getenv('MAIL_PASSWORD'),
    MAIL_DEFAULT_SENDER=os.getenv('MAIL_USERNAME'),
    UPLOAD_FOLDER='static/uploads'
)
mail = Mail(app)

DB_FILE = 'app.db'
MICROWAVABLE_PRICE_PER_BOX = 1500.0


def send_order_email(recipient, subject, body):
    """Send an order notification when SMTP credentials are configured."""
    if not recipient or not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        app.logger.warning('Order email skipped: MAIL_USERNAME/MAIL_PASSWORD is not configured.')
        return
    try:
        mail.send(Message(subject=subject, recipients=[recipient], body=body))
    except Exception:
        app.logger.exception('Unable to send order email to %s', recipient)


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
            ('cup-12oz', 'cup', 'Cups — 12 oz (Box of 1,000)', '12oz', None, 1000, 45.0, 50, 'Durable 12oz disposable cups.'),
            ('cup-16oz', 'cup', 'Cups — 16 oz (Box of 1,000)', '16oz', None, 1000, 45.0, 40, 'Classic 16oz disposable cups.'),
            ('cup-22oz', 'cup', 'Cups — 22 oz (Box of 1,000)', '22oz', None, 1000, 45.0, 25, 'Large 22oz disposable cups.'),
            ('lid-strawless', 'lid', 'Lids — Strawless (Box of 1,000)', None, 'Strawless', 1000, 25.0, 60, 'Strawless lids — universal fit.'),
            ('lid-dome', 'lid', 'Lids — Dome (Box of 1,000)', None, 'Dome', 1000, 25.0, 30, 'Dome lids — universal fit.'),
            ('lid-flat', 'lid', 'Lids — Flat (Box of 1,000)', None, 'Flat', 1000, 25.0, 15, 'Flat lids — universal fit.')
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            customer_name TEXT NOT NULL,
            email TEXT,
            customer_address TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Cash on Delivery',
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
            status
        FROM orders
        ORDER BY created_at DESC, id DESC
    ''').fetchall()
    conn.close()
    return jsonify({"orders": [dict(order) for order in orders]})


@app.route('/api/admin/orders/<int:order_id>/status', methods=['PATCH', 'PUT'])
@app.route('/api/orders/<int:order_id>/status', methods=['PUT', 'PATCH'])
def update_order_status(order_id):
    """Update an order's fulfillment status."""
    allowed_statuses = {'Pending', 'Paid', 'Shipping', 'Shipped', 'Completed'}
    data = request.get_json(force=True, silent=True) or {}
    status = data.get('status')

    if status not in allowed_statuses:
        return jsonify({
            "error": "Status must be Pending, Paid, Shipped, or Completed."
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

    return jsonify({"order": dict(order)})


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

    conn.close()

    subtotal = round(subtotal, 2)
    shipping = 15.0 if subtotal > 0 else 0.0
    total = round(subtotal + shipping, 2)

    return jsonify({
        "items": items,
        "subtotal": subtotal,
        "shipping": shipping,
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
    if cup_id and cup_boxes > 0:
        cup = cursor.execute('SELECT price_per_box FROM products WHERE id = ?', (cup_id,)).fetchone()
        subtotal += cup['price_per_box'] * cup_boxes
    if lid_id and lid_boxes > 0:
        lid = cursor.execute('SELECT price_per_box FROM products WHERE id = ?', (lid_id,)).fetchone()
        subtotal += lid['price_per_box'] * lid_boxes
    subtotal += MICROWAVABLE_PRICE_PER_BOX * microwavable_boxes

    subtotal = round(subtotal, 2)
    shipping = 15.0 if subtotal > 0 else 0.0
    total = round(subtotal + shipping, 2)
    if payment_type == 'full':
        downpayment_amount = round(total, 2)
        remaining_balance = 0.0
        payment_status = 'Full Payment Pending'
    else:
        downpayment_amount = round(total * 0.5, 2)
        remaining_balance = round(total - downpayment_amount, 2)
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
            INSERT INTO orders (user_id, customer_name, email, customer_address, customer_phone, payment_method, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total_amount, downpayment_amount, remaining_balance, payment_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, name, email, address, phone, payment_method, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total, downpayment_amount, remaining_balance, payment_status, created_at))


        order_id = cursor.lastrowid
        conn.commit()
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": f"Failed to process order: {str(e)}"}), 500

    conn.close()

    email_subject = f"Order Received & Payment Confirmation - Pack & Sip Order #{order_id}"
    # Construct base URL for the receipt upload link
    base_url = request.host_url.rstrip('/')
    upload_link = f"{base_url}/upload-receipt?order_id={order_id}"

    if payment_type == 'full':
        email_body = (
            f"Hello {order['customer_name']},\n\n"
            "Thank you for ordering from Pack & Sip. We have received your order and its status is Pending.\n\n"
            "Items:\n"
            f"{order_items_text(order)}\n\n"
            f"Total Amount: ₱{order['total_amount']:.2f}\n"
            "Payment Required: Full payment of the total above is required to confirm your order.\n\n"
            "Payment Instructions:\n"
            f"Please send your full payment of ₱{order['total_amount']:.2f} to confirm your order:\n"
            "• GCash: 0912 345 6789 (Pack & Sip)\n"
            "• Maya: 0912 345 6789\n"
            "• Bank Transfer (BDO): 0012 3456 7890\n\n"
            f"Please upload your payment receipt screenshot here: {upload_link}\n\n"
            "Once verified, your order will be prepared and dispatched via Lalamove."
        )
    else:
        email_body = (
            f"Hello {order['customer_name']},\n\n"
            "Thank you for ordering from Pack & Sip. We have received your order and its status is Pending.\n\n"
            "Items:\n"
            f"{order_items_text(order)}\n\n"
            f"Total Amount: ₱{order['total_amount']:.2f}\n"
            f"Required 50% Downpayment: ₱{order['downpayment_amount']:.2f}\n"
            f"Remaining Balance upon Delivery: ₱{order['remaining_balance']:.2f}\n\n"
            "Payment Instructions:\n"
            f"Please send your 50% downpayment of ₱{order['downpayment_amount']:.2f} to confirm your order:\n"
            "• GCash: 0912 345 6789 (Pack & Sip)\n"
            "• Maya: 0912 345 6789\n"
            "• Bank Transfer (BDO): 0012 3456 7890\n\n"
            f"Please upload your payment receipt screenshot here: {upload_link}\n\n"
            "Once verified, your order will be prepared and dispatched via Lalamove. "
            f"Pay the remaining balance of ₱{order['remaining_balance']:.2f} upon delivery."
        )

    # Send the SMTP email in a background thread so the HTTP response
    # returns immediately without waiting for network completion.
    threading.Thread(
        target=send_order_email,
        args=(order['email'], email_subject, email_body),
        daemon=True
    ).start()

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": "Order processed successfully!",
        "payment_method": payment_method,
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


@app.route('/api/orders/delete/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    """Delete an order only if its status is 'Completed'."""
    conn = get_db()
    order = conn.execute('SELECT status FROM orders WHERE id = ?', (order_id,)).fetchone()
    
    if not order:
        conn.close()
        return jsonify({"error": "Order not found."}), 404
        
    if order['status'] != 'Completed':
        conn.close()
        return jsonify({"error": "Only completed orders can be deleted."}), 400

    conn.execute('DELETE FROM orders WHERE id = ?', (order_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Order #{order_id} deleted successfully."})


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)