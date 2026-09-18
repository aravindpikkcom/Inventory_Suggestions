# import os
# import re
# import requests
# from bs4 import BeautifulSoup
# from urllib.parse import urljoin, urlparse
#
# #URL = "https://thehouseofrare.com/collections/rr-men-polo-t-shirts"
# #shirt
# URL = "https://www.maxfashion.in/in/en/c/maxmen-bottoms-trousers"
#
# OUTPUT_DIR = "trouser"
# os.makedirs(OUTPUT_DIR, exist_ok=True)
#
# headers = {
#     "User-Agent": (
#         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
#         "AppleWebKit/537.36 (KHTML, like Gecko) "
#         "Chrome/150.0.0.0 Safari/537.36"
#     )
# }
#
# session = requests.Session()
# session.headers.update(headers)
#
# # Get collection page
# response = session.get(URL, timeout=30)
# response.raise_for_status()
#
# soup = BeautifulSoup(response.text, "html.parser")
#
# # Find product links
# products = {}
#
# for a in soup.find_all("a", href=True):
#
#     href = a["href"]
#
#     if "/products/" not in href:
#         continue
#
#     product_url = urljoin(URL, href)
#
#     # Product name
#     name = a.get_text(" ", strip=True)
#
#     if not name:
#         img = a.find("img")
#         if img:
#             name = img.get("alt", "").strip()
#
#     if name:
#         products[product_url] = name
#
#
# print("Products found:", len(products))
#
#
# def clean_filename(name):
#     name = re.sub(r'[<>:"/\\|?*]', "", name)
#     name = re.sub(r"\s+", " ", name)
#     return name.strip()[:150]
#
#
# # Download images from each product page
# for index, (product_url, product_name) in enumerate(products.items(), 1):
#
#     print(f"\n[{index}/{len(products)}] {product_name}")
#
#     try:
#         product_response = session.get(product_url, timeout=30)
#         product_response.raise_for_status()
#
#         product_soup = BeautifulSoup(
#             product_response.text,
#             "html.parser"
#         )
#
#         # Product images
#         images = product_soup.find_all("img")
#
#         product_dir = os.path.join(
#             OUTPUT_DIR,
#             f"{index:03d}_{clean_filename(product_name)}"
#         )
#
#         os.makedirs(product_dir, exist_ok=True)
#
#         downloaded = set()
#         image_count = 0
#
#         for img in images:
#
#             image_url = (
#                 img.get("src")
#                 or img.get("data-src")
#                 or img.get("data-original")
#             )
#
#             if not image_url:
#                 continue
#
#             image_url = urljoin(product_url, image_url)
#
#             # Avoid downloading same image twice
#             if image_url in downloaded:
#                 continue
#
#             downloaded.add(image_url)
#
#             try:
#
#                 image_response = session.get(
#                     image_url,
#                     timeout=30
#                 )
#
#                 image_response.raise_for_status()
#
#                 content_type = image_response.headers.get(
#                     "Content-Type",
#                     ""
#                 )
#
#                 if not content_type.startswith("image/"):
#                     continue
#
#                 extension = ".jpg"
#
#                 if "png" in content_type:
#                     extension = ".png"
#                 elif "webp" in content_type:
#                     extension = ".webp"
#                 elif "jpeg" in content_type:
#                     extension = ".jpg"
#
#                 image_count += 1
#
#                 filename = os.path.join(
#                     product_dir,
#                     f"image_{image_count}{extension}"
#                 )
#
#                 with open(filename, "wb") as f:
#                     f.write(image_response.content)
#
#                 print("   Downloaded:", filename)
#
#             except Exception as e:
#                 print("   Image failed:", image_url, e)
#
#         print("   Images:", image_count)
#
#     except Exception as e:
#         print("   Product failed:", e)
#
# print("\nDONE")


import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

URL = "https://www.maxfashion.in/in/en/c/maxmen-bottoms-trousers"
OUTPUT_DIR = "trouser"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# A fuller, more browser-realistic header set. A bare User-Agent alone is
# an easy tell for WAFs (Cloudflare/Akamai/Imperva/DataDome) - real browsers
# always send Accept, Accept-Language, Accept-Encoding, sec-fetch-* etc.
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

session = requests.Session()
session.headers.update(headers)

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
        "\nStill blocked. This usually means the block isn't about headers at "
        "all - it's TLS/JS-challenge level bot protection (Akamai/Cloudflare/"
        "Imperva/DataDome), which the 'requests' library cannot get past no "
        "matter what headers you send, because it's fingerprinting the TLS "
        "handshake itself, not just HTTP headers.\n"
        "Next options: (1) try 'curl_cffi' (pip install curl_cffi) which can "
        "impersonate real browser TLS fingerprints, (2) use a real headless "
        "browser via Playwright/Selenium instead of requests, or (3) fall "
        "back to manually saving product images for now."
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


def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()[:150]


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

                extension = ".jpg"
                if "png" in content_type:
                    extension = ".png"
                elif "webp" in content_type:
                    extension = ".webp"

                image_count += 1
                filename = os.path.join(product_dir, f"image_{image_count}{extension}")
                with open(filename, "wb") as f:
                    f.write(image_response.content)
                print("   Downloaded:", filename)

            except Exception as e:
                print("   Image failed:", image_url, e)

        print("   Images:", image_count)

    except Exception as e:
        print("   Product failed:", e)

print("\nDONE")