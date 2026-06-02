"""
Seed Legacy Database Generator
===============================
Creates a realistic "undocumented" legacy e-commerce database with:
- customers, products, categories, orders, order_items, reviews
- Foreign key relationships for the MCP server to discover
- Sample data for testing CRUD operations

Usage:
    python sample_data/seed_legacy_db.py [output_path]
"""

import sqlite3
import os
import sys
import random
from datetime import datetime, timedelta

# Default database path
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "legacy_store.db")


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables with foreign key relationships."""
    conn.executescript("""
        -- Enable foreign keys
        PRAGMA foreign_keys = ON;

        -- Categories table
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Customers table
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT,
            address TEXT,
            city TEXT,
            country TEXT DEFAULT 'US',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        );

        -- Products table
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL CHECK(price >= 0),
            category_id INTEGER,
            stock_qty INTEGER DEFAULT 0,
            sku TEXT UNIQUE,
            is_available INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );

        -- Orders table
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')),
            total_amount REAL DEFAULT 0,
            shipping_address TEXT,
            notes TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        -- Order Items (junction table — many-to-many between orders and products)
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            unit_price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        -- Reviews table
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            title TEXT,
            comment TEXT,
            review_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        -- Indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_customer ON reviews(customer_id);
    """)


def seed_data(conn: sqlite3.Connection) -> None:
    """Insert realistic sample data."""
    cursor = conn.cursor()

    # --- Categories ---
    categories = [
        ("Electronics", "Gadgets, devices, and electronic accessories"),
        ("Clothing", "Apparel and fashion items"),
        ("Books", "Physical and digital books"),
        ("Home & Garden", "Furniture, decor, and garden supplies"),
        ("Sports", "Sports equipment and outdoor gear"),
    ]
    cursor.executemany(
        "INSERT INTO categories (name, description) VALUES (?, ?)", categories
    )

    # --- Customers ---
    customers = [
        ("Alice", "Johnson", "alice.johnson@email.com", "+1-555-0101", "123 Oak St", "Portland", "US"),
        ("Bob", "Smith", "bob.smith@email.com", "+1-555-0102", "456 Maple Ave", "Seattle", "US"),
        ("Carol", "Williams", "carol.w@email.com", "+1-555-0103", "789 Pine Rd", "Denver", "US"),
        ("David", "Brown", "david.b@email.com", "+1-555-0104", "321 Elm Blvd", "Austin", "US"),
        ("Eve", "Davis", "eve.davis@email.com", "+1-555-0105", "654 Cedar Ln", "Chicago", "US"),
        ("Frank", "Miller", "frank.m@email.com", "+1-555-0106", "987 Birch Way", "Boston", "US"),
        ("Grace", "Wilson", "grace.w@email.com", "+1-555-0107", "147 Walnut Dr", "Miami", "US"),
        ("Henry", "Moore", "henry.m@email.com", "+1-555-0108", "258 Spruce Ct", "Phoenix", "US"),
    ]
    cursor.executemany(
        "INSERT INTO customers (first_name, last_name, email, phone, address, city, country) VALUES (?, ?, ?, ?, ?, ?, ?)",
        customers,
    )

    # --- Products ---
    products = [
        ("Wireless Headphones", "Noise-cancelling Bluetooth headphones", 79.99, 1, 150, "SKU-ELEC-001"),
        ("USB-C Hub", "7-in-1 USB-C docking station", 49.99, 1, 200, "SKU-ELEC-002"),
        ("Mechanical Keyboard", "Cherry MX Blue switches, RGB backlit", 129.99, 1, 75, "SKU-ELEC-003"),
        ("Cotton T-Shirt", "100% organic cotton, unisex", 24.99, 2, 500, "SKU-CLTH-001"),
        ("Denim Jacket", "Classic fit denim jacket", 89.99, 2, 120, "SKU-CLTH-002"),
        ("Running Shoes", "Lightweight trail running shoes", 119.99, 5, 90, "SKU-SPRT-001"),
        ("Python Programming", "Learn Python the Hard Way, 5th Edition", 39.99, 3, 300, "SKU-BOOK-001"),
        ("Data Science Handbook", "Comprehensive guide to data science", 54.99, 3, 180, "SKU-BOOK-002"),
        ("Garden Tool Set", "5-piece stainless steel garden tools", 34.99, 4, 60, "SKU-HOME-001"),
        ("LED Desk Lamp", "Adjustable brightness, USB charging port", 45.99, 4, 100, "SKU-HOME-002"),
        ("Yoga Mat", "Non-slip, eco-friendly yoga mat", 29.99, 5, 200, "SKU-SPRT-002"),
        ("Smart Watch", "Fitness tracker with heart rate monitor", 199.99, 1, 80, "SKU-ELEC-004"),
    ]
    cursor.executemany(
        "INSERT INTO products (name, description, price, category_id, stock_qty, sku) VALUES (?, ?, ?, ?, ?, ?)",
        products,
    )

    # --- Orders ---
    random.seed(42)
    statuses = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
    base_date = datetime(2024, 1, 1)
    orders_data = []
    for i in range(20):
        customer_id = random.randint(1, 8)
        order_date = base_date + timedelta(days=random.randint(0, 365))
        status = random.choice(statuses)
        orders_data.append((customer_id, order_date.isoformat(), status, f"{random.randint(1, 8)} Main St"))

    cursor.executemany(
        "INSERT INTO orders (customer_id, order_date, status, shipping_address) VALUES (?, ?, ?, ?)",
        orders_data,
    )

    # --- Order Items ---
    order_items_data = []
    for order_id in range(1, 21):
        num_items = random.randint(1, 4)
        product_ids = random.sample(range(1, 13), num_items)
        for product_id in product_ids:
            qty = random.randint(1, 5)
            # Look up price
            cursor.execute("SELECT price FROM products WHERE id = ?", (product_id,))
            price = cursor.fetchone()[0]
            order_items_data.append((order_id, product_id, qty, price))

    cursor.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
        order_items_data,
    )

    # Update order totals
    cursor.execute("""
        UPDATE orders SET total_amount = (
            SELECT COALESCE(SUM(quantity * unit_price), 0) 
            FROM order_items WHERE order_items.order_id = orders.id
        )
    """)

    # --- Reviews ---
    review_comments = [
        ("Great product!", "Exceeded my expectations. Highly recommend."),
        ("Good value", "Works as described, good for the price."),
        ("Decent", "Average quality, nothing special."),
        ("Not impressed", "Below expectations. Packaging was damaged."),
        ("Excellent!", "Best purchase I've made this year!"),
        ("Solid choice", "Reliable and well-made product."),
        ("Pretty good", "Minor issues but overall satisfied."),
        ("Amazing quality", "Premium feel and excellent build quality."),
    ]

    reviews_data = []
    for _ in range(25):
        product_id = random.randint(1, 12)
        customer_id = random.randint(1, 8)
        rating = random.randint(1, 5)
        title, comment = random.choice(review_comments)
        review_date = base_date + timedelta(days=random.randint(0, 365))
        reviews_data.append((product_id, customer_id, rating, title, comment, review_date.isoformat()))

    cursor.executemany(
        "INSERT INTO reviews (product_id, customer_id, rating, title, comment, review_date) VALUES (?, ?, ?, ?, ?, ?)",
        reviews_data,
    )

    conn.commit()


def seed_database(db_path: str = DEFAULT_DB_PATH) -> str:
    """Create and seed the legacy database. Returns the database path."""
    # Remove existing database if present
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        seed_data(conn)
        
        # Verify
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"[OK] Legacy database created at: {db_path}")
        print(f"   Tables: {', '.join(tables)}")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
            count = cursor.fetchone()[0]
            print(f"   - {table}: {count} rows")
    finally:
        conn.close()

    return db_path


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    seed_database(path)
