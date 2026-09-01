import os
import re
import time
import requests

# Shopify store + collection handle
BASE_URL = "https://www.ottostore.com"
COLLECTION_HANDLE = "casual-core"

OUTPUT_DIR = "shirt"
os.makedirs(OUTPUT_DIR, exist_ok=True)

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE_URL}/collections/{COLLECTION_HANDLE}",
}

session = requests.Session()
session.headers.update(headers)


def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()[:150]


def fetch_all_products(collection_handle):
    """Paginate through Shopify's public products.json for a collection."""
    products = []
    page = 1
    while True:
        url = f"{BASE_URL}/collections/{collection_handle}/products.json"
        resp = session.get(url, params={"limit": 250, "page": page}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("products", [])
        if not batch:
            break
        products.extend(batch)
        print(f"Page {page}: {len(batch)} products (total so far: {len(products)})")
        page += 1
        time.sleep(0.5)  # be polite
    return products


products = fetch_all_products(COLLECTION_HANDLE)
print("\nTotal products found:", len(products))

for index, product in enumerate(products, 1):
    title = product.get("title", f"product_{index}")
    images = product.get("images", [])

    print(f"\n[{index}/{len(products)}] {title} ({len(images)} images)")

    product_dir = os.path.join(
        OUTPUT_DIR,
        f"{index:03d}_{clean_filename(title)}"
    )
    os.makedirs(product_dir, exist_ok=True)

    for img_index, image in enumerate(images, 1):
        image_url = image.get("src")
        if not image_url:
            continue

        # Shopify src urls sometimes come without a scheme
        if image_url.startswith("//"):
            image_url = "https:" + image_url

        try:
            image_response = session.get(image_url, timeout=30)
            image_response.raise_for_status()

            content_type = image_response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                continue

            extension = ".jpg"
            if "png" in content_type:
                extension = ".png"
            elif "webp" in content_type:
                extension = ".webp"

            filename = os.path.join(product_dir, f"image_{img_index}{extension}")
            with open(filename, "wb") as f:
                f.write(image_response.content)

            print("   Downloaded:", filename)

        except Exception as e:
            print("   Image failed:", image_url, e)

print("\nDONE")