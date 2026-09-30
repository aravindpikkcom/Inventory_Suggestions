import sqlite3

rows = [
    ("Kanjivaram Silk Saree", "Saree", "Edappally", 12, 84000, "2026-08-02"),
    ("Banarasi Silk Saree", "Saree", "Edappally", 8, 56000, "2026-08-04"),
    ("Cotton Saree", "Saree", "Kakkanad", 15, 45000, "2026-08-05"),

    ("Kanjivaram Silk Saree", "Saree", "Kakkanad", 20, 140000, "2026-08-08"),
    ("Banarasi Silk Saree", "Saree", "Edappally", 18, 126000, "2026-08-10"),
    ("Designer Saree", "Saree", "Kakkanad", 10, 90000, "2026-08-12"),

    ("Kanjivaram Silk Saree", "Saree", "Edappally", 25, 175000, "2026-08-15"),
    ("Cotton Saree", "Saree", "Edappally", 30, 90000, "2026-08-18"),

    ("Designer Saree", "Saree", "Edappally", 16, 144000, "2026-08-20"),
    ("Banarasi Silk Saree", "Saree", "Kakkanad", 14, 98000, "2026-08-22"),

    ("Kanjivaram Silk Saree", "Saree", "Edappally", 10, 70000, "2026-07-02"),
    ("Banarasi Silk Saree", "Saree", "Kakkanad", 9, 63000, "2026-07-05"),
    ("Cotton Saree", "Saree", "Edappally", 20, 60000, "2026-07-08"),

    ("Designer Saree", "Saree", "Kakkanad", 7, 63000, "2026-07-12"),
]

connection = sqlite3.connect("retail.db")

cursor = connection.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    store TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    amount REAL NOT NULL,
    sale_date TEXT NOT NULL
)
""")

cursor.execute("DELETE FROM sales")

cursor.executemany("""
INSERT INTO sales (
    product_name,
    category,
    store,
    quantity,
    amount,
    sale_date
)
VALUES (?, ?, ?, ?, ?, ?)
""", rows)

connection.commit()

connection.close()

print("retail.db created successfully")