"""
Requires curl_cffi instead of requests, since maxfashion.in returns 403 on
every request (even the homepage) with plain requests - that's TLS/JA3
fingerprint-level bot protection (Akamai-style), not a header problem.
curl_cffi impersonates a real browser's TLS handshake, which plain
requests/urllib3 cannot do no matter what headers are set.

Run:
    pip install curl_cffi beautifulsoup4 --break-system-packages
    python scrape_maxfashion_polo.py
"""

import os
import re
from io import BytesIO
from curl_cffi import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from PIL import Image, UnidentifiedImageError

URL = "https://www.maxfashion.in/in/en/c/maxmen-tops-tshirts"
OUTPUT_DIR = "polotshirt"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# curl_cffi's `impersonate` param spoofs the TLS fingerprint (JA3) of a
# real Chrome build, not just the User-Agent header. This is what actually
# gets past Akamai/Cloudflare/Imperva/DataDome-style bot checks that plain
# requests can't - the block happens at the network handshake, before any
# HTTP header is ever inspected.
IMPERSONATE = "chrome120"

session = requests.Session(impersonate=IMPERSONATE)

# Warm up the session: visit the homepage first to pick up cookies before
# hitting the category page directly. Some WAFs specifically flag "cold"
# deep links that arrive with zero prior cookies/session history.
try:
    warmup = session.get("https://www.maxfashion.in/in/en", timeout=30)
    print("Homepage warm-up status:", warmup.status_code)
except Exception as e:
    print("Homepage warm-up failed:", e)

response = session.get(URL, timeout=30)
print("Category page status:", response.status_code)

if response.status_code != 200:
    print(
        "\nStill blocked even with curl_cffi TLS impersonation. Next options:\n"
        "  (1) Try a different --impersonate target, e.g. 'chrome124', 'safari17_0',\n"
        "      'firefox133' - different fingerprints get through different WAF rules.\n"
        "  (2) Use a real headless browser via Playwright instead - slower, but runs\n"
        "      an actual browser engine so there's no fingerprint to spoof at all.\n"
        "  (3) Fall back to manually saving product images for now."
    )
    raise SystemExit(1)

response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")

products = {}
for a in soup.find_all("a", href=True):
    href = a["href"]
    if "/products/" not in href and "/p/" not in href:
        continue
    product_url = urljoin(URL, href)
    name = a.get_text(" ", strip=True)
    if not name:
        img = a.find("img")
        if img:
            name = img.get("alt", "").strip()
    if name:
        products[product_url] = name

print("Products found:", len(products))

if not products:
    with open("debug_category_page.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    print(
        "0 products found even though the page loaded (status 200) - the page "
        "might be rendered client-side by JS (React/Vue), in which case the "
        "product links simply aren't in the raw HTML requests/curl_cffi fetches. "
        "Check debug_category_page.html - if it has no '/products/' or '/p/' "
        "links anywhere, this needs Playwright (a real browser engine) instead."
    )


MIN_IMAGE_BYTES = 8_000  # icons, sprites, and lazy-load placeholders are
                          # almost always smaller than this; real product
                          # photos are not - tune up/down if you see either
                          # real photos getting skipped or junk getting through

def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()[:150]


def is_valid_image(content: bytes) -> bool:
    """Returns True only if PIL can fully decode the bytes as an image.
    Catches truncated downloads and any non-image content a WAF/CDN might
    have served with an image/* Content-Type header."""
    try:
        img = Image.open(BytesIO(content))
        img.verify()  # checks structural integrity without fully decoding pixels
        return True
    except (UnidentifiedImageError, OSError):
        return False


for index, (product_url, product_name) in enumerate(products.items(), 1):
    print(f"\n[{index}/{len(products)}] {product_name}")
    try:
        product_response = session.get(product_url, timeout=30)
        product_response.raise_for_status()
        product_soup = BeautifulSoup(product_response.text, "html.parser")

        images = product_soup.find_all("img")
        product_dir = os.path.join(OUTPUT_DIR, f"{index:03d}_{clean_filename(product_name)}")
        os.makedirs(product_dir, exist_ok=True)

        downloaded = set()
        image_count = 0

        for img in images:
            image_url = img.get("src") or img.get("data-src") or img.get("data-original")
            if not image_url:
                continue
            image_url = urljoin(product_url, image_url)
            if image_url in downloaded:
                continue
            downloaded.add(image_url)

            try:
                image_response = session.get(image_url, timeout=30)
                image_response.raise_for_status()
                content_type = image_response.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    continue

                content = image_response.content

                if len(content) < MIN_IMAGE_BYTES:
                    print(f"   Skipped (too small, likely icon/placeholder, {len(content)} bytes):", image_url)
                    continue

                if not is_valid_image(content):
                    print("   Skipped (corrupted/unreadable image data):", image_url)
                    continue

                extension = ".jpg"
                if "png" in content_type:
                    extension = ".png"
                elif "webp" in content_type:
                    extension = ".webp"

                image_count += 1
                filename = os.path.join(product_dir, f"image_{image_count}{extension}")
                with open(filename, "wb") as f:
                    f.write(content)
                print("   Downloaded:", filename)

            except Exception as e:
                print("   Image failed:", image_url, e)

        print("   Images:", image_count)

    except Exception as e:
        print("   Product failed:", e)

print("\nDONE")