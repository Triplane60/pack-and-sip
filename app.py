import sqlite3
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__, template_folder='.')
CORS(app)

DB_FILE = 'app.db'
MICROWAVABLE_PRICE_PER_BOX = 1500.0

def get_db():
    """Establish and return a database connection with dict-like row access."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database schema and seed initial inventory if empty."""
    conn = get_db()
    cursor = conn.cursor()

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

    # Create Orders Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            email TEXT,
            customer_address TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Cash on Delivery',
            cup_id TEXT,
            cup_size TEXT,
            cup_boxes INTEGER,
            lid_id TEXT,
            lid_style TEXT,
            lid_boxes INTEGER,
            microwavable_size TEXT,
            microwavable_boxes INTEGER NOT NULL DEFAULT 0,
            total_amount REAL NOT NULL,
            created_at TEXT NOT NULL
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
    conn.commit()

    conn.close()


init_db()


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


@app.route('/api/admin/orders/<int:order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    """Update an order's fulfillment status."""
    allowed_statuses = {'Pending', 'Paid', 'Shipped', 'Completed'}
    data = request.get_json(force=True, silent=True) or {}
    status = data.get('status')

    if status not in allowed_statuses:
        return jsonify({
            "error": "Status must be Pending, Paid, Shipped, or Completed."
        }), 400

    conn = get_db()
    cursor = conn.execute(
        'UPDATE orders SET status = ? WHERE id = ?',
        (status, order_id)
    )
    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Order not found."}), 404
    conn.commit()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()
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


@app.route('/api/checkout', methods=['POST'])
@app.route('/api/orders', methods=['POST'])
def process_checkout():
    """Deduct stock from SQLite database when an order is submitted."""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    address = (data.get('address') or '').strip()
    phone = (data.get('phone') or '').strip()
    payment_method = (data.get('payment_method') or 'Cash on Delivery').strip() or 'Cash on Delivery'
    cup_id = data.get('cup_id')
    lid_id = data.get('lid_id')
    microwavable_id = data.get('microwavable_id')
    cup_size = (data.get('cup_size') or '').strip() or None
    lid_style = (data.get('lid_style') or '').strip() or None
    microwavable_size = (data.get('microwavable_size') or '').strip() or None

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

    # Deduct stock and insert order within a transaction
    try:
        for pid, requested_qty in orders_to_process:
            cursor.execute(
                # This app stores available inventory in stock_boxes.
                'UPDATE products SET stock_boxes = stock_boxes - ? WHERE id = ?',
                (requested_qty, pid)
            )

        import datetime
        created_at = datetime.datetime.utcnow().isoformat()

        cursor.execute('''
            INSERT INTO orders (customer_name, email, customer_address, customer_phone, payment_method, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total_amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, email, address, phone, payment_method, cup_id, cup_size, cup_boxes, lid_id, lid_style, lid_boxes, microwavable_size, microwavable_boxes, total, created_at))

        order_id = cursor.lastrowid
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": f"Failed to process order: {str(e)}"}), 500

    conn.close()

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": "Order processed successfully!",
        "payment_method": payment_method,
        "total": total
    })


if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=5000, debug=True)