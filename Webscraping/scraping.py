import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

#URL = "https://thehouseofrare.com/collections/rr-men-polo-t-shirts"
#shirt
URL = "https://www.ottostore.com/collections/casual-core"

OUTPUT_DIR = "shirt"
os.makedirs(OUTPUT_DIR, exist_ok=True)

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    )
}

session = requests.Session()
session.headers.update(headers)

# Get collection page
response = session.get(URL, timeout=30)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# Find product links
products = {}

for a in soup.find_all("a", href=True):

    href = a["href"]

    if "/products/" not in href:
        continue

    product_url = urljoin(URL, href)

    # Product name
    name = a.get_text(" ", strip=True)

    if not name:
        img = a.find("img")
        if img:
            name = img.get("alt", "").strip()

    if name:
        products[product_url] = name


print("Products found:", len(products))


def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()[:150]


# Download images from each product page
for index, (product_url, product_name) in enumerate(products.items(), 1):

    print(f"\n[{index}/{len(products)}] {product_name}")

    try:
        product_response = session.get(product_url, timeout=30)
        product_response.raise_for_status()

        product_soup = BeautifulSoup(
            product_response.text,
            "html.parser"
        )

        # Product images
        images = product_soup.find_all("img")

        product_dir = os.path.join(
            OUTPUT_DIR,
            f"{index:03d}_{clean_filename(product_name)}"
        )

        os.makedirs(product_dir, exist_ok=True)

        downloaded = set()
        image_count = 0

        for img in images:

            image_url = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-original")
            )

            if not image_url:
                continue

            image_url = urljoin(product_url, image_url)

            # Avoid downloading same image twice
            if image_url in downloaded:
                continue

            downloaded.add(image_url)

            try:

                image_response = session.get(
                    image_url,
                    timeout=30
                )

                image_response.raise_for_status()

                content_type = image_response.headers.get(
                    "Content-Type",
                    ""
                )

                if not content_type.startswith("image/"):
                    continue

                extension = ".jpg"

                if "png" in content_type:
                    extension = ".png"
                elif "webp" in content_type:
                    extension = ".webp"
                elif "jpeg" in content_type:
                    extension = ".jpg"

                image_count += 1

                filename = os.path.join(
                    product_dir,
                    f"image_{image_count}{extension}"
                )

                with open(filename, "wb") as f:
                    f.write(image_response.content)

                print("   Downloaded:", filename)

            except Exception as e:
                print("   Image failed:", image_url, e)

        print("   Images:", image_count)

    except Exception as e:
        print("   Product failed:", e)

print("\nDONE")