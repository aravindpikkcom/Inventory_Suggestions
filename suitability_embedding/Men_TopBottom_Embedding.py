"""
Smart Mirror - Outfit Pairing Generator
==========================================
Builds outfit_pairs.json by matching shirts (top wear) to trousers (bottom
wear) using formality and dominant color compatibility.

This script only reads shirt_metadata.json / pant_metadata.json (built by
index_inventory.py) - it does NOT use the FAISS .index files or any
FashionCLIP embedding similarity. Matching is entirely rule-based
(formality bucket + color bucket, both derived from metadata/image
pixels), so no index/embedding files are required here.

Run:
    pip install scikit-learn pillow numpy --break-system-packages
    python build_outfit_pairs.py
"""

import json
import os
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

# ----------------------------
# CONFIG - edit these
# ----------------------------
SHIRT_METADATA_PATH = "/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/indexing/shirt_new_metadata.json"
PANT_METADATA_PATH = "/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/indexing/trouser_metadata.json"

OUTPUT_PATH = "Mens_Suitability_Search/outfit_pairs.json"

TOP_K = 1                 # how many trouser matches to keep per shirt
BIDIRECTIONAL = True       # also generate pant -> top shirts

# ----------------------------
# FORMALITY - manual mapping (Option 1 from earlier discussion)
# ----------------------------
# Edit this to match how your inventory is actually organized.
# Simplest approach: base it on the category folder name (from metadata["category"]).
FORMAL_CATEGORIES = {"formal_shirts", "formal_trousers", "chinos"}
CASUAL_CATEGORIES = {"casual_shirts", "denim", "cotton", "printed_tshirts"}


def get_formality(category: str) -> str:
    category_lower = category.lower()
    if category_lower in FORMAL_CATEGORIES:
        return "formal"
    if category_lower in CASUAL_CATEGORIES:
        return "casual"
    return "unknown"  # falls back to "matches anything" during filtering


# ----------------------------
# COLOR COMPATIBILITY RULES
# ----------------------------
# Coarse color buckets - dominant RGB gets snapped to the nearest one.
COLOR_BUCKETS = {
    "white":  (255, 255, 255),
    "black":  (0, 0, 0),
    "navy":   (30, 40, 90),
    "beige":  (222, 202, 168),
    "grey":   (130, 130, 130),
    "brown":  (101, 67, 33),
    "blue":   (50, 90, 180),
    "red":    (180, 30, 30),
    "green":  (60, 110, 60),
    "yellow": (220, 200, 60),
    "pink":   (230, 150, 170),
}

# Which bottom colors are considered compatible with which top colors.
# Symmetric-ish, curated by hand rather than derived.
COLOR_COMPATIBILITY = {
    "white":  {"navy", "black", "beige", "grey", "blue", "brown"},
    "black":  {"white", "grey", "beige", "red", "pink"},
    "navy":   {"white", "beige", "grey"},
    "beige":  {"white", "navy", "black", "brown", "blue"},
    "grey":   {"white", "black", "navy", "blue"},
    "brown":  {"white", "beige", "blue"},
    "blue":   {"white", "beige", "grey", "brown"},
    "red":    {"black", "white", "grey"},
    "green":  {"beige", "white", "grey"},
    "yellow": {"navy", "grey", "white"},
    "pink":   {"white", "black", "grey"},
}


def nearest_color_bucket(rgb) -> str:
    r, g, b = rgb
    best_name, best_dist = None, float("inf")
    for name, (br, bg, bb) in COLOR_BUCKETS.items():
        dist = (r - br) ** 2 + (g - bg) ** 2 + (b - bb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


def get_dominant_color(image_path: str, k: int = 3) -> str:
    """Runs k-means on the (already garment-isolated) image to find the
    dominant non-white color, then snaps it to the nearest named bucket."""
    img = Image.open(image_path).convert("RGB").resize((100, 100))
    pixels = np.array(img).reshape(-1, 3).astype("float32")

    # drop near-white pixels (background fill from isolate_garment)
    non_white_mask = ~np.all(pixels > 240, axis=1)
    filtered = pixels[non_white_mask]

    if len(filtered) < k:
        filtered = pixels  # fallback if garment region was tiny/mostly white

    kmeans = KMeans(n_clusters=k, n_init=4, random_state=0).fit(filtered)
    counts = np.bincount(kmeans.labels_)
    dominant_rgb = kmeans.cluster_centers_[counts.argmax()]

    return nearest_color_bucket(dominant_rgb)


# ----------------------------
# BUILD PER-PRODUCT FEATURES
# ----------------------------
def build_product_features(metadata: list) -> dict:
    """Collapses per-image metadata entries into one feature record per
    unique product_id (color, formality, location), using the first
    available image."""
    products = {}
    for entry in metadata:
        pid = entry["id"]
        if pid in products:
            continue  # already processed this product

        try:
            color = get_dominant_color(entry["image_path"])
        except Exception as e:
            print(f"  [WARN] Could not extract color for {pid}: {e}")
            color = "unknown"

        # There's no separate "location" field in the source metadata - the
        # product's own folder (image_path minus the filename) is the
        # location, e.g.
        #   .../shirt/cotton_shirt/001_Light Khaki Twill Satin Solid Casual Shirt
        location = os.path.dirname(entry["image_path"])

        products[pid] = {
            "id": pid,
            "category": entry["category"],
            "formality": get_formality(entry["category"]),
            "color": color,
            "image_path": entry["image_path"],
            "location": location,
        }
    return products


# ----------------------------
# MATCHING LOGIC
# ----------------------------
def is_compatible(top_color: str, bottom_color: str) -> bool:
    if top_color == "unknown" or bottom_color == "unknown":
        return True  # don't block matches just because color extraction failed
    return bottom_color in COLOR_COMPATIBILITY.get(top_color, set())


def formality_matches(top_formality: str, bottom_formality: str) -> bool:
    if top_formality == "unknown" or bottom_formality == "unknown":
        return True  # unknown formality doesn't block a match
    return top_formality == bottom_formality


def rank_candidates(source_product: dict, candidate_products: dict) -> list:
    """Filters candidates by formality + color rules, returns ranked list
    of candidate records (color-compatible ones first). Each record now
    carries id + location so the mirror UI can point a customer to where
    a suggested pair actually sits in the store."""
    compatible = []
    fallback = []  # formality matches but color doesn't - kept as backup

    for cand in candidate_products.values():
        if not formality_matches(source_product["formality"], cand["formality"]):
            continue
        record = {"id": cand["id"], "location": cand["location"]}
        if is_compatible(source_product["color"], cand["color"]):
            compatible.append(record)
        else:
            fallback.append(record)

    ranked = compatible + fallback  # prefer color-compatible, pad with fallback
    return ranked[:TOP_K]


def main():
    print("Loading metadata...")
    with open(SHIRT_METADATA_PATH) as f:
        shirt_metadata = json.load(f)
    with open(PANT_METADATA_PATH) as f:
        pant_metadata = json.load(f)

    print("Extracting shirt features (color, formality, location)...")
    shirts = build_product_features(shirt_metadata)
    print(f"  {len(shirts)} unique shirts")

    print("Extracting pant features (color, formality, location)...")
    pants = build_product_features(pant_metadata)
    print(f"  {len(pants)} unique pants")

    outfit_pairs = {}

    print(f"\nMatching each shirt to top {TOP_K} pants...")
    for shirt_id, shirt in shirts.items():
        outfit_pairs[shirt_id] = {
            "location": shirt["location"],
            "matches": rank_candidates(shirt, pants),
        }

    if BIDIRECTIONAL:
        print(f"Matching each pant to top {TOP_K} shirts...")
        for pant_id, pant in pants.items():
            outfit_pairs[pant_id] = {
                "location": pant["location"],
                "matches": rank_candidates(pant, shirts),
            }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(outfit_pairs, f, indent=2)

    total_entries = sum(len(v["matches"]) for v in outfit_pairs.values())
    print(f"\n{'='*50}")
    print(f"Done.")
    print(f"  Shirts processed:   {len(shirts)}")
    print(f"  Pants processed:    {len(pants)}")
    print(f"  Total pair entries: {total_entries}")
    print(f"  Saved to:           {OUTPUT_PATH}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()