# import sqlite3
#
# rows = [
#     ("Kanjivaram Silk Saree", "Saree", "Edappally", 12, 84000, "2026-08-02"),
#     ("Banarasi Silk Saree", "Saree", "Edappally", 8, 56000, "2026-08-04"),
#     ("Cotton Saree", "Saree", "Kakkanad", 15, 45000, "2026-08-05"),
#
#     ("Kanjivaram Silk Saree", "Saree", "Kakkanad", 20, 140000, "2026-08-08"),
#     ("Banarasi Silk Saree", "Saree", "Edappally", 18, 126000, "2026-08-10"),
#     ("Designer Saree", "Saree", "Kakkanad", 10, 90000, "2026-08-12"),
#
#     ("Kanjivaram Silk Saree", "Saree", "Edappally", 25, 175000, "2026-08-15"),
#     ("Cotton Saree", "Saree", "Edappally", 30, 90000, "2026-08-18"),
#
#     ("Designer Saree", "Saree", "Edappally", 16, 144000, "2026-08-20"),
#     ("Banarasi Silk Saree", "Saree", "Kakkanad", 14, 98000, "2026-08-22"),
#
#     ("Kanjivaram Silk Saree", "Saree", "Edappally", 10, 70000, "2026-07-02"),
#     ("Banarasi Silk Saree", "Saree", "Kakkanad", 9, 63000, "2026-07-05"),
#     ("Cotton Saree", "Saree", "Edappally", 20, 60000, "2026-07-08"),
#
#     ("Designer Saree", "Saree", "Kakkanad", 7, 63000, "2026-07-12"),
# ]
#
# connection = sqlite3.connect("retail.db")
#
# cursor = connection.cursor()
#
# cursor.execute("""
# CREATE TABLE IF NOT EXISTS sales (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     product_name TEXT NOT NULL,
#     category TEXT NOT NULL,
#     store TEXT NOT NULL,
#     quantity INTEGER NOT NULL,
#     amount REAL NOT NULL,
#     sale_date TEXT NOT NULL
# )
# """)
#
# cursor.execute("DELETE FROM sales")
#
# cursor.executemany("""
# INSERT INTO sales (
#     product_name,
#     category,
#     store,
#     quantity,
#     amount,
#     sale_date
# )
# VALUES (?, ?, ?, ?, ?, ?)
# """, rows)
#
# connection.commit()
#
# connection.close()
#
# print("retail.db created successfully")


#!/usr/bin/env python3
"""
create_retail_db.py - builds retail.db for the Reflexn insight reports.

    python create_retail_db.py                 # writes retail.db to DB_PATH (below)
    python create_retail_db.py --db demo.db    # somewhere else

Tables
    Master data   stores, vendors, products, product_pairs, inventory, customers
    Mirror logs   mirror_sessions, session_events   (viewed / tried / selected at the mirror)
    Sales         bills, sales                      (sales = line items: the original columns plus ids)
    insights      one row per business point (scenario 1, 2 and the 12 operational insights),
                  each mapped to a report in generate_reports.py
    meta          marks the data as synthetic so the reports say so

The sample data is generated, not real. Patterns are built in (Onam and wedding
seasonality, a saree with high interest but low conversion, stock-outs, a rising
colour, the same stock plan in every store) so every report has something to show.
When real data is available, keep the schema and replace the generate_* part with
loaders from the POS, the inventory system and the kiosk logs.

Standard library only.
"""
import argparse
import math
import os
import random
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import accumulate

HISTORY_START = date(2024, 10, 1)   # two years of sales history
AS_OF = date(2026, 9, 27)           # last day of data
MIRROR_LIVE = date(2026, 7, 1)      # mirror pilot go-live in all four stores
SEED = 42

# Where retail.db is written; generate_reports.py reads from the same place
DB_PATH = "/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/pikkcom_insight/retail.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS sales_flat;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS bills;
DROP TABLE IF EXISTS session_events;
DROP TABLE IF EXISTS mirror_sessions;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS product_pairs;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS vendors;
DROP TABLE IF EXISTS stores;
DROP TABLE IF EXISTS insights;
DROP TABLE IF EXISTS meta;

CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- The business points, one row each. report_key names the report in generate_reports.py.
CREATE TABLE insights (
    insight_id  INTEGER PRIMARY KEY,
    scenario    TEXT NOT NULL,
    title       TEXT NOT NULL,
    reveals     TEXT NOT NULL,
    benefit     TEXT NOT NULL,
    report_key  TEXT NOT NULL UNIQUE
);

CREATE TABLE stores (
    store_id          INTEGER PRIMARY KEY,
    store_name        TEXT NOT NULL,
    city              TEXT NOT NULL,
    region            TEXT NOT NULL,
    mirror_live_from  TEXT                -- NULL = no mirror in this store
);

CREATE TABLE vendors (
    vendor_id    INTEGER PRIMARY KEY,
    vendor_name  TEXT NOT NULL,
    brand        TEXT NOT NULL
);

CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    sku           TEXT NOT NULL UNIQUE,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL,          -- Saree, Top, Bottom, Dress, Kurta, Shirt, Mundu
    gender        TEXT NOT NULL,          -- Women / Men
    style         TEXT NOT NULL,          -- Traditional / Western / Fusion
    color         TEXT NOT NULL,
    fabric        TEXT NOT NULL,
    vendor_id     INTEGER NOT NULL REFERENCES vendors(vendor_id),
    price         REAL NOT NULL
);

-- Cross-sell rules the mirror uses: top + bottom, kurta + bottom, mundu + shirt, ...
CREATE TABLE product_pairs (
    product_id         INTEGER NOT NULL REFERENCES products(product_id),   -- the main item
    paired_product_id  INTEGER NOT NULL REFERENCES products(product_id),   -- what is suggested with it
    pair_type          TEXT NOT NULL,
    PRIMARY KEY (product_id, paired_product_id)
);

-- Current stock snapshot per store
CREATE TABLE inventory (
    store_id       INTEGER NOT NULL REFERENCES stores(store_id),
    product_id     INTEGER NOT NULL REFERENCES products(product_id),
    stock_qty      INTEGER NOT NULL,
    reorder_level  INTEGER NOT NULL,
    PRIMARY KEY (store_id, product_id)
);

-- Gender and age group come from the loyalty / billing profile the customer gives,
-- never inferred from the camera.
CREATE TABLE customers (
    customer_id       INTEGER PRIMARY KEY,
    customer_code     TEXT NOT NULL UNIQUE,
    gender            TEXT NOT NULL,
    age_group         TEXT NOT NULL,
    home_city         TEXT NOT NULL,
    marketing_opt_in  INTEGER NOT NULL DEFAULT 0
);

-- One row per shopper session at the mirror
CREATE TABLE mirror_sessions (
    session_id    INTEGER PRIMARY KEY,
    store_id      INTEGER NOT NULL REFERENCES stores(store_id),
    customer_id   INTEGER REFERENCES customers(customer_id),     -- NULL = anonymous shopper
    started_at    TEXT NOT NULL,
    duration_sec  INTEGER NOT NULL
);

-- What happened in the session: product shown (viewed), rendered on the shopper (tried),
-- pinch-finalised (selected)
CREATE TABLE session_events (
    event_id           INTEGER PRIMARY KEY,
    session_id         INTEGER NOT NULL REFERENCES mirror_sessions(session_id),
    product_id         INTEGER NOT NULL REFERENCES products(product_id),
    event_type         TEXT NOT NULL CHECK (event_type IN ('viewed', 'tried', 'selected')),
    source             TEXT NOT NULL CHECK (source IN ('recommendation', 'catalog', 'pair_suggestion')),
    anchor_product_id  INTEGER REFERENCES products(product_id),  -- pair suggestions: the item it was paired with
    in_stock           INTEGER NOT NULL                          -- 1 if the store had stock at that moment
);

CREATE TABLE bills (
    bill_id      INTEGER PRIMARY KEY,
    store_id     INTEGER NOT NULL REFERENCES stores(store_id),
    customer_id  INTEGER REFERENCES customers(customer_id),        -- NULL = walk-in, not identified
    session_id   INTEGER REFERENCES mirror_sessions(session_id),   -- set when the purchase followed a mirror session
    bill_date    TEXT NOT NULL
);

-- Line items. Same columns as the original sales table, with ids instead of names.
CREATE TABLE sales (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id     INTEGER NOT NULL REFERENCES bills(bill_id),
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    store_id    INTEGER NOT NULL REFERENCES stores(store_id),
    quantity    INTEGER NOT NULL,
    amount      REAL NOT NULL,
    sale_date   TEXT NOT NULL
);

CREATE INDEX idx_sales_date        ON sales(sale_date);
CREATE INDEX idx_sales_bill        ON sales(bill_id);
CREATE INDEX idx_sales_product     ON sales(product_id, sale_date);
CREATE INDEX idx_bills_date        ON bills(bill_date);
CREATE INDEX idx_bills_session     ON bills(session_id);
CREATE INDEX idx_bills_customer    ON bills(customer_id);
CREATE INDEX idx_sessions_started  ON mirror_sessions(started_at);
CREATE INDEX idx_sessions_customer ON mirror_sessions(customer_id);
CREATE INDEX idx_events_session    ON session_events(session_id, event_type);
CREATE INDEX idx_events_product    ON session_events(product_id, event_type);

-- The original flat shape (product_name, category, store, quantity, amount, sale_date),
-- so queries written against the first version of the sales table still work.
CREATE VIEW sales_flat AS
SELECT s.id, p.product_name, p.category, st.store_name AS store,
       s.quantity, s.amount, s.sale_date
FROM sales s
JOIN products p ON p.product_id = s.product_id
JOIN stores  st ON st.store_id  = s.store_id;
"""

# ---------------------------------------------------------------------------
# The business points (your list), stored as a table
# ---------------------------------------------------------------------------
S1 = "1. Customer experience & revenue"
S2 = "2. Cross-selling"
S3 = "3. Operational insights"

INSIGHTS = [
    # report_key, scenario, title, reveals, benefit
    ("revenue_impact", S1, "Mirror impact on revenue",
     "Whether shoppers use the mirror, how many outfits they try, how often a session ends in a purchase, "
     "and how mirror-assisted bills compare with other bills",
     "Puts a number on the revenue lift from trying more outfits virtually"),
    ("brand_attachment", S1, "Personalisation & repeat visits ('the brand understands me')",
     "How often personalised suggestions are tried and bought, and whether mirror users come back more often",
     "Evidence for brand attachment and repeat footfall"),
    ("cross_sell", S2, "Cross-selling: suggested pairs",
     "How often a suggested pair (top + bottom, kurta + bottom, mundu + shirt) is tried and bought together",
     "Higher order value per bill"),
    ("product_interest", S3, "Product interest (even without purchase)",
     "Viewed, tried and purchased for every product; high interest but low conversion",
     "Spots products needing a price change or with sizing / quality issues"),
    ("inventory", S3, "Inventory optimisation",
     "High-demand and slow-moving products, and products customers want that are out of stock",
     "Less overstock, fewer stock-outs, better inventory turnover"),
    ("store_demand", S3, "Store-wise demand analysis",
     "Customer preferences by store, and where each store's stock doesn't match its demand",
     "Inventory customised per store instead of the same assortment everywhere"),
    ("segmentation", S3, "Customer segmentation",
     "Interest and buying by gender, age group, and new vs returning customers",
     "More targeted products and marketing"),
    ("trends", S3, "Trend identification",
     "Rising and falling colours, fabrics and styles in try-ons; seasonal demand by category",
     "Stays ahead of changing customer preferences"),
    ("forecast", S3, "Demand forecasting",
     "Next month's units per category from last year's same month and current growth",
     "Better procurement planning and lower inventory cost"),
    ("marketing", S3, "Personalised marketing",
     "Opted-in customers who tried but did not buy, grouped into campaign audiences",
     "More relevant promotions and offers, higher engagement and conversion"),
    ("product_performance", S3, "Product performance analysis",
     "Revenue and growth by product, and interest rank vs sales rank",
     "Informed decisions to introduce, promote or discontinue products"),
    ("regional", S3, "Regional market insights",
     "Demand, growth and category mix by city and region",
     "Supports expansion planning and localised merchandising"),
    ("opportunities", S3, "Sales opportunity identification",
     "Categories and products with high interest but low sales, with the likely cause",
     "Fix pricing, merchandising or availability to convert more"),
    ("vendor_performance", S3, "Vendor & brand performance",
     "Revenue, growth, conversion and sell-through by vendor / brand, and where each sells best",
     "Better vendor negotiation and brand mix"),
    ("strategic_summary", S3, "Strategic decision support",
     "Headline numbers and the top actions from all the reports",
     "Assortment, store planning, marketing, pricing and expansion decisions with less guesswork"),
]

# ---------------------------------------------------------------------------
# Sample master data
# ---------------------------------------------------------------------------
STORES = [
    # name, city, region, ordinary bills per day, mirror sessions per day, style preference
    ("Edappally", "Kochi", "Central Kerala", 22, 11, {"Traditional": 1.35, "Western": 0.85, "Fusion": 1.0}),
    ("Kakkanad", "Kochi", "Central Kerala", 16, 8, {"Traditional": 1.25, "Western": 1.0, "Fusion": 0.95}),
    ("Pattom", "Thiruvananthapuram", "South Kerala", 18, 9, {"Traditional": 0.75, "Western": 1.55, "Fusion": 1.1}),
    ("Kozhikode", "Kozhikode", "North Kerala", 14, 7, {"Traditional": 1.1, "Western": 0.85, "Fusion": 1.4}),
]

VENDORS = [
    ("Kanchi Silk Weavers", "Kanchi Heritage"),
    ("Varanasi Loom House", "Kashi Looms"),
    ("Kasavu Craft Collective", "Kasavu Craft"),
    ("Studio Mehr", "Mehr"),
    ("UrbanThread Apparel", "UrbanThread"),
    ("Northline Menswear", "Northline"),
    ("Nila Ethnic Wear", "Nila"),
]

# sku, name, category, gender, style, colour, fabric, vendor index, price,
# pop (weight in ordinary sales), appeal (weight in mirror views),
# try_p (chance a viewed item is tried), buy_p (chance a tried item is bought), tags
PRODUCTS = [
    ("SR-KAN-BLU", "Kanjivaram Silk Saree - Royal Blue", "Saree", "Women", "Traditional", "Blue", "Silk", 0, 14500, 0.70, 2.4, 0.75, 0.10, ""),
    ("SR-BAN-RED", "Banarasi Silk Saree - Crimson", "Saree", "Women", "Traditional", "Red", "Silk", 1, 7800, 1.20, 0.9, 0.85, 0.60, "wedding"),
    ("SR-KAS-OFW", "Kasavu Saree - Off-white & Gold", "Saree", "Women", "Traditional", "Off-white", "Cotton", 2, 3200, 1.10, 1.2, 0.65, 0.45, "onam"),
    ("SR-LIN-SAG", "Linen Saree - Sage Green", "Saree", "Women", "Traditional", "Green", "Linen", 6, 4200, 0.80, 0.8, 0.60, 0.40, "trend"),
    ("SR-DES-PNK", "Designer Saree - Blush Pink", "Saree", "Women", "Traditional", "Pink", "Georgette", 3, 9500, 0.35, 1.0, 0.50, 0.15, ""),
    ("SR-ORG-MUS", "Organza Saree - Mustard", "Saree", "Women", "Traditional", "Yellow", "Organza", 3, 5400, 0.60, 0.8, 0.55, 0.30, ""),
    ("SR-KAN-MAR", "Kanjivaram Silk Saree - Maroon", "Saree", "Women", "Traditional", "Maroon", "Silk", 0, 12900, 0.90, 1.4, 0.75, 0.45, "wedding"),
    ("WW-TOP-WHT", "Linen Top - White", "Top", "Women", "Western", "White", "Linen", 4, 1499, 1.00, 1.0, 0.70, 0.40, ""),
    ("WW-TOP-BLK", "Crop Top - Black", "Top", "Women", "Western", "Black", "Cotton", 4, 999, 0.90, 0.9, 0.65, 0.38, ""),
    ("WW-DRS-NAV", "Midi Dress - Navy", "Dress", "Women", "Western", "Navy", "Crepe", 4, 2799, 0.70, 1.2, 0.70, 0.28, ""),
    ("WW-DRS-SAG", "Maxi Dress - Sage Green", "Dress", "Women", "Western", "Green", "Rayon", 4, 2299, 0.50, 0.8, 0.70, 0.38, "trend"),
    ("WW-BTM-DEN", "Wide-leg Jeans - Mid Blue", "Bottom", "Women", "Western", "Blue", "Denim", 4, 1999, 0.90, 0.7, 0.60, 0.40, ""),
    ("WW-BTM-BEI", "Tailored Trousers - Beige", "Bottom", "Women", "Western", "Beige", "Poly-viscose", 4, 1699, 0.60, 0.6, 0.55, 0.35, ""),
    ("WF-KUR-TEA", "Cotton Kurta - Teal", "Kurta", "Women", "Fusion", "Teal", "Cotton", 6, 1299, 1.30, 1.0, 0.65, 0.45, ""),
    ("WF-KUR-MUS", "Anarkali Kurta - Mustard", "Kurta", "Women", "Fusion", "Yellow", "Rayon", 6, 2499, 0.70, 1.1, 0.60, 0.30, ""),
    ("WF-BTM-PAL", "Palazzo - Off-white", "Bottom", "Women", "Fusion", "Off-white", "Cotton", 6, 799, 0.90, 0.5, 0.50, 0.40, ""),
    ("MW-SHT-WHT", "Linen Shirt - White", "Shirt", "Men", "Western", "White", "Linen", 5, 1799, 1.10, 1.0, 0.65, 0.42, ""),
    ("MW-SHT-SKY", "Oxford Shirt - Sky Blue", "Shirt", "Men", "Western", "Blue", "Cotton", 5, 1499, 0.90, 0.9, 0.60, 0.40, ""),
    ("MW-TSH-OLV", "Polo T-shirt - Olive", "Top", "Men", "Western", "Olive", "Pique cotton", 5, 1299, 0.90, 0.8, 0.55, 0.45, "trend"),
    ("MW-BTM-CHI", "Chinos - Khaki", "Bottom", "Men", "Western", "Khaki", "Cotton twill", 5, 1899, 0.80, 0.8, 0.55, 0.40, ""),
    ("MW-BTM-DEN", "Slim Jeans - Indigo", "Bottom", "Men", "Western", "Indigo", "Denim", 5, 2199, 0.90, 0.8, 0.55, 0.38, ""),
    ("MT-KUR-CRM", "Cotton Kurta - Cream", "Kurta", "Men", "Traditional", "Cream", "Cotton", 6, 1599, 0.70, 0.9, 0.60, 0.35, "wedding"),
    ("MT-MUN-KAS", "Kasavu Mundu - Off-white & Gold", "Mundu", "Men", "Traditional", "Off-white", "Cotton", 2, 1200, 0.90, 1.0, 0.55, 0.50, "onam"),
]

PAIRS = [
    ("WW-TOP-WHT", "WW-BTM-DEN", "Top + bottom"),
    ("WW-TOP-WHT", "WW-BTM-BEI", "Top + bottom"),
    ("WW-TOP-BLK", "WW-BTM-DEN", "Top + bottom"),
    ("WW-TOP-BLK", "WF-BTM-PAL", "Top + bottom"),
    ("WF-KUR-TEA", "WF-BTM-PAL", "Kurta + bottom"),
    ("WF-KUR-MUS", "WF-BTM-PAL", "Kurta + bottom"),
    ("MW-SHT-WHT", "MW-BTM-CHI", "Top + bottom"),
    ("MW-SHT-WHT", "MW-BTM-DEN", "Top + bottom"),
    ("MW-SHT-SKY", "MW-BTM-CHI", "Top + bottom"),
    ("MW-SHT-SKY", "MW-BTM-DEN", "Top + bottom"),
    ("MW-TSH-OLV", "MW-BTM-DEN", "Top + bottom"),
    ("MT-MUN-KAS", "MW-SHT-WHT", "Mundu + shirt"),
    ("MT-KUR-CRM", "MT-MUN-KAS", "Kurta + mundu"),
]

# Out of stock from this date until the end of the data
STOCKOUTS = {
    ("SR-KAN-MAR", "Edappally"): date(2026, 8, 22),
    ("SR-KAN-MAR", "Pattom"): date(2026, 9, 3),
    ("WW-DRS-SAG", "Pattom"): date(2026, 8, 12),
    ("MT-MUN-KAS", "Kozhikode"): date(2026, 9, 1),
}

# Days of stock held under the chain-wide stock plan (default: random 30-75).
# The same plan applies to every store, which is what the store-demand report exposes.
COVER_DAYS = {"SR-KAN-BLU": 210, "SR-DES-PNK": 240, "WF-KUR-TEA": 9, "WW-TOP-WHT": 12}

AGE_GROUPS = ["18-24", "25-34", "35-44", "45-54", "55+"]
AGE_WEIGHTS = [0.18, 0.32, 0.25, 0.15, 0.10]
AGE_STYLE = {
    "18-24": {"Traditional": 0.55, "Western": 1.70, "Fusion": 1.25},
    "25-34": {"Traditional": 0.85, "Western": 1.35, "Fusion": 1.15},
    "35-44": {"Traditional": 1.20, "Western": 0.90, "Fusion": 1.05},
    "45-54": {"Traditional": 1.55, "Western": 0.55, "Fusion": 0.90},
    "55+":   {"Traditional": 1.80, "Western": 0.35, "Fusion": 0.75},
}

N_CUSTOMERS = 12000
IDENTIFIED_BILL = 0.70      # ordinary bills with a known customer
IDENTIFIED_SESSION = 0.60   # mirror sessions where the shopper logs in / gives their number
RETURN_AFTER_MIRROR = 0.22  # identified mirror users who come back for another session
BUY_SCALE = 0.40            # overall purchase propensity at the mirror


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
class Generator:
    def __init__(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)

    # -- helpers ------------------------------------------------------------
    def poisson(self, lam):
        if lam <= 0:
            return 0
        if lam > 30:
            return max(0, int(round(self.rng.gauss(lam, math.sqrt(lam)))))
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= limit:
                return k
            k += 1

    def weighted_sample(self, items, weights, k):
        """k distinct items, drawn by weight."""
        items, weights = list(items), list(weights)
        picked = []
        while items and len(picked) < k and sum(weights) > 0:
            i = self.rng.choices(range(len(items)), weights)[0]
            picked.append(items.pop(i))
            weights.pop(i)
        return picked

    @staticmethod
    def is_onam(d):
        return date(d.year, 8, 15) <= d <= date(d.year, 9, 10)

    def traffic(self, d):
        m = 1.0
        if d.weekday() >= 5:
            m *= 1.3
        if self.is_onam(d):
            m *= 1.7
        elif d.month == 8:
            m *= 1.2
        if d.month in (11, 12, 1):
            m *= 1.15                                   # wedding season
        if date(d.year, 4, 8) <= d <= date(d.year, 4, 15):
            m *= 1.3                                    # Vishu
        return m * (1 + 0.08 * (d - HISTORY_START).days / 365)   # ~8% yearly growth

    def season(self, p, d):
        m = 1.0
        if "onam" in p["tags"]:
            m *= 3.0 if self.is_onam(d) else (1.4 if d.month == 8 else 0.8)
        if "wedding" in p["tags"] and d.month in (11, 12, 1, 2):
            m *= 1.6
        if p["category"] == "Saree" and self.is_onam(d):
            m *= 1.4
        if "trend" in p["tags"]:
            span = (AS_OF - HISTORY_START).days
            m *= 0.6 + 0.4 * (d - HISTORY_START).days / span
            if d >= MIRROR_LIVE:                         # takes off during the pilot
                m *= 1 + 1.2 * (d - MIRROR_LIVE).days / (AS_OF - MIRROR_LIVE).days
        return m

    # -- build --------------------------------------------------------------
    def build(self, con):
        rng = self.rng
        con.executescript(SCHEMA)

        con.executemany("INSERT INTO insights (scenario, title, reveals, benefit, report_key) VALUES (?,?,?,?,?)",
                        [(s, t, r, b, k) for k, s, t, r, b in INSIGHTS])

        stores = []
        for i, (name, city, region, bills, sessions, pref) in enumerate(STORES, start=1):
            stores.append(dict(id=i, name=name, city=city, bills=bills, sessions=sessions, pref=pref))
            con.execute("INSERT INTO stores VALUES (?,?,?,?,?)", (i, name, city, region, MIRROR_LIVE.isoformat()))

        con.executemany("INSERT INTO vendors VALUES (?,?,?)",
                        [(i, v, b) for i, (v, b) in enumerate(VENDORS, start=1)])

        products = []
        for i, row in enumerate(PRODUCTS, start=1):
            sku, name, cat, gender, style, color, fabric, vend, price, pop, appeal, try_p, buy_p, tags = row
            products.append(dict(id=i, sku=sku, name=name, category=cat, gender=gender, style=style, price=price,
                                 pop=pop, appeal=appeal, try_p=try_p, buy_p=buy_p, tags=tags))
            con.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (i, sku, name, cat, gender, style, color, fabric, vend + 1, price))
        by_sku = {p["sku"]: p for p in products}

        pairs_of = defaultdict(list)
        for a, b, pair_type in PAIRS:
            pairs_of[by_sku[a]["id"]].append((by_sku[b], pair_type))
            con.execute("INSERT INTO product_pairs VALUES (?,?,?)", (by_sku[a]["id"], by_sku[b]["id"], pair_type))

        store_by_name = {s["name"]: s for s in stores}
        stockout_from = {(by_sku[sku]["id"], store_by_name[st]["id"]): d for (sku, st), d in STOCKOUTS.items()}

        def in_stock(pid, sid, d):
            start = stockout_from.get((pid, sid))
            return not (start and d >= start)

        pool = {g: [p for p in products if p["gender"] == g]
                for g in ("Women", "Men")}

        # customers
        cities = sorted({s["city"] for s in stores})
        city_weight = {c: sum(s["bills"] for s in stores if s["city"] == c) for c in cities}
        cust = {}
        by_city = defaultdict(lambda: ([], []))
        all_ids, all_w = [], []
        for cid in range(1, N_CUSTOMERS + 1):
            gender = "Women" if rng.random() < 0.68 else "Men"
            age = rng.choices(AGE_GROUPS, AGE_WEIGHTS)[0]
            city = rng.choices(cities, [city_weight[c] for c in cities])[0]
            opt_in = 1 if rng.random() < 0.55 else 0
            loyalty = rng.paretovariate(1.8)             # a few very loyal customers
            cust[cid] = (gender, age)
            by_city[city][0].append(cid)
            by_city[city][1].append(loyalty)
            all_ids.append(cid)
            all_w.append(loyalty)
            con.execute("INSERT INTO customers VALUES (?,?,?,?,?,?)",
                        (cid, f"C{cid:05d}", gender, age, city, opt_in))
        city_pool = {c: (ids, list(accumulate(w))) for c, (ids, w) in by_city.items()}
        all_pool = (all_ids, list(accumulate(all_w)))

        def pick_customer(city):
            ids, cum = city_pool[city] if rng.random() < 0.85 else all_pool
            return rng.choices(ids, cum_weights=cum)[0]

        def random_shopper():
            return ("Women" if rng.random() < 0.68 else "Men"), rng.choices(AGE_GROUPS, AGE_WEIGHTS)[0]

        bills, sales, sessions, events = [], [], [], []
        ids = {"bill": 0, "session": 0}
        returns = defaultdict(list)                      # (date, store id) -> [customer ids]

        def add_bill(store, cid, session_id, d, items):
            ids["bill"] += 1
            bills.append((ids["bill"], store["id"], cid, session_id, d.isoformat()))
            for p in items:
                qty = 2 if p["category"] in ("Top", "Bottom") and rng.random() < 0.1 else 1
                sales.append((ids["bill"], p["id"], store["id"], qty, p["price"] * qty, d.isoformat()))

        d = HISTORY_START
        while d <= AS_OF:
            traffic = self.traffic(d)
            pilot = d >= MIRROR_LIVE
            cache = {}

            def weights(store, gender, age, kind):
                key = (store["id"], gender, age, kind)
                if key not in cache:
                    w = []
                    for p in pool[gender]:
                        base = p["pop"] if kind == "sale" else p["appeal"]
                        x = base * store["pref"][p["style"]] * AGE_STYLE[age][p["style"]] * self.season(p, d)
                        if kind == "sale" and not in_stock(p["id"], store["id"], d):
                            x = 0.0
                        w.append(x)
                    cache[key] = w
                return cache[key]

            for store in stores:
                # 1) ordinary bills (during the pilot some of these shoppers buy through the mirror instead)
                for _ in range(self.poisson(store["bills"] * traffic * (0.79 if pilot else 1.0))):
                    if rng.random() < IDENTIFIED_BILL:
                        cid = pick_customer(store["city"])
                        gender, age = cust[cid]
                    else:
                        cid = None
                        gender, age = random_shopper()
                    w = weights(store, gender, age, "sale")
                    if sum(w) == 0:
                        continue
                    items = []
                    for _ in range(1 + (rng.random() < 0.25) + (rng.random() < 0.06)):
                        p = rng.choices(pool[gender], w)[0]
                        if p in items:
                            continue
                        items.append(p)
                        if pairs_of[p["id"]] and rng.random() < 0.10:         # cross-sell without the mirror
                            q = rng.choice(pairs_of[p["id"]])[0]
                            if q not in items and in_stock(q["id"], store["id"], d):
                                items.append(q)
                    add_bill(store, cid, None, d, items)

                # 2) mirror sessions
                if not pilot:
                    continue
                visitors = [None] * self.poisson(store["sessions"] * traffic) + returns.pop((d, store["id"]), [])
                for cid in visitors:
                    if cid is None and rng.random() < IDENTIFIED_SESSION:
                        cid = pick_customer(store["city"])
                    gender, age = cust[cid] if cid else random_shopper()

                    ids["session"] += 1
                    sid = ids["session"]
                    k = rng.randint(4, 7) if gender == "Women" else rng.randint(3, 5)
                    shown = self.weighted_sample(pool[gender], weights(store, gender, age, "view"), k)
                    shown_ids = {p["id"] for p in shown}

                    tried = []                                   # (product, source, stock)
                    first = None
                    for p in shown:
                        src = "recommendation" if rng.random() < 0.8 else "catalog"
                        stock = in_stock(p["id"], store["id"], d)
                        events.append((sid, p["id"], "viewed", src, None, int(stock)))
                        first = first or (p, src, stock)
                        if rng.random() < p["try_p"] * (1.1 if src == "recommendation" else 0.85):
                            events.append((sid, p["id"], "tried", src, None, int(stock)))
                            tried.append((p, src, stock))
                    if not tried and first and rng.random() < 0.85:
                        p, src, stock = first
                        events.append((sid, p["id"], "tried", src, None, int(stock)))
                        tried.append((p, src, stock))

                    pair_tried, pair_shown = [], []              # (pair, anchor, stock)
                    for p, _, _ in tried:
                        options = [(q, t) for q, t in pairs_of[p["id"]] if q["id"] not in shown_ids]
                        if not options:
                            continue
                        q, _ = rng.choice(options)
                        shown_ids.add(q["id"])
                        stock = in_stock(q["id"], store["id"], d)
                        events.append((sid, q["id"], "viewed", "pair_suggestion", p["id"], int(stock)))
                        if rng.random() < 0.45:
                            events.append((sid, q["id"], "tried", "pair_suggestion", p["id"], int(stock)))
                            pair_tried.append((q, p, stock))
                        else:
                            pair_shown.append((q, p, stock))

                    selected = set()
                    for p, src, stock in tried + [(q, "pair_suggestion", s) for q, _, s in pair_tried]:
                        if rng.random() < 0.35:
                            events.append((sid, p["id"], "selected", src, None, int(stock)))
                            selected.add(p["id"])

                    bought = []
                    for p, _, stock in tried:
                        if stock and rng.random() < min(0.95, p["buy_p"] * BUY_SCALE * (1.5 if p["id"] in selected else 0.75)):
                            bought.append(p)
                    bought_ids = {p["id"] for p in bought}
                    for q, anchor, stock in pair_tried:
                        if stock and q["id"] not in bought_ids:
                            prob = (0.50 if anchor["id"] in bought_ids else 0.06) * (1.2 if q["id"] in selected else 1.0)
                            if rng.random() < prob:
                                bought.append(q)
                                bought_ids.add(q["id"])
                    for q, anchor, stock in pair_shown:
                        if stock and anchor["id"] in bought_ids and q["id"] not in bought_ids and rng.random() < 0.12:
                            bought.append(q)
                            bought_ids.add(q["id"])

                    started = datetime(d.year, d.month, d.day, rng.randint(10, 20), rng.randint(0, 59))
                    duration = max(30, int(40 + 10 * len(shown_ids) + 35 * (len(tried) + len(pair_tried)) + rng.gauss(0, 20)))
                    sessions.append((sid, store["id"], cid, started.isoformat(sep=" "), duration))
                    if bought:
                        add_bill(store, cid, sid, d, bought)
                    if cid and rng.random() < RETURN_AFTER_MIRROR:
                        back = d + timedelta(days=rng.randint(7, 45))
                        if back <= AS_OF:
                            returns[(back, store["id"])].append(cid)
            d += timedelta(days=1)

        # bills reference sessions, so sessions go in first
        con.executemany("INSERT INTO mirror_sessions VALUES (?,?,?,?,?)", sessions)
        con.executemany("INSERT INTO session_events (session_id, product_id, event_type, source, anchor_product_id, in_stock) "
                        "VALUES (?,?,?,?,?,?)", events)
        con.executemany("INSERT INTO bills VALUES (?,?,?,?,?)", bills)
        con.executemany("INSERT INTO sales (bill_id, product_id, store_id, quantity, amount, sale_date) "
                        "VALUES (?,?,?,?,?,?)", sales)

        # inventory: one chain-wide stock plan, scaled by store size
        since = (AS_OF - timedelta(days=89)).isoformat()
        units = defaultdict(int)
        store_units = defaultdict(int)
        for _, pid, sid, qty, _, sd in sales:
            if sd >= since:
                units[pid] += qty
                store_units[sid] += qty
        total = sum(store_units.values())
        cover = {p["id"]: COVER_DAYS.get(p["sku"], rng.randint(30, 75)) for p in products}
        for s in stores:
            share = store_units[s["id"]] / total
            for p in products:
                rate = units[p["id"]] / 90 * share
                stock = 0 if not in_stock(p["id"], s["id"], AS_OF) else round(rate * cover[p["id"]] * rng.uniform(0.85, 1.15))
                con.execute("INSERT INTO inventory VALUES (?,?,?,?)",
                            (s["id"], p["id"], stock, max(2, math.ceil(rate * 14))))

        con.executemany("INSERT INTO meta VALUES (?,?)", [
            ("data_source", "synthetic sample (create_retail_db.py, seed %d)" % self.seed),
            ("generated_on", date.today().isoformat()),
        ])
        con.commit()
        return {"bills": len(bills), "sales lines": len(sales), "mirror sessions": len(sessions),
                "session events": len(events), "customers": N_CUSTOMERS, "products": len(products)}


def main():
    ap = argparse.ArgumentParser(description="Create retail.db with synthetic sample data for the Reflexn reports.")
    ap.add_argument("--db", default=DB_PATH, help=f"database file to create (default: {DB_PATH})")
    ap.add_argument("--seed", type=int, default=SEED, help="random seed (default: 42)")
    args = ap.parse_args()

    folder = os.path.dirname(os.path.abspath(args.db))
    os.makedirs(folder, exist_ok=True)
    con = sqlite3.connect(args.db)
    try:
        counts = Generator(args.seed).build(con)
    finally:
        con.close()
    print(f"{args.db} created successfully")
    for k, v in counts.items():
        print(f"  {k:<16} {v:>8,}")
    print(f"  data covers      {HISTORY_START} to {AS_OF} (mirror live from {MIRROR_LIVE})")


if __name__ == "__main__":
    main()