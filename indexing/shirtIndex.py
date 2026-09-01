"""
Smart Mirror - Inventory Indexing Script
==========================================
Scans an inventory folder structure, removes background/isolates garment,
generates embeddings using FashionCLIP, and builds a FAISS similarity index.

Expected folder structure:
    saree_inventory/
        banarasi/
            product_001/
                worn_front.jpg
                worn_back.jpg   (optional, multiple angles OK)
            product_002/
                ...
        kanjivaram/
            ...

Run:
    pip install faiss-cpu torch torchvision open_clip_torch pillow numpy rembg onnxruntime --break-system-packages
    python index_inventory.py
"""

import os
import glob
import json
import io

import numpy as np
import torch
import faiss
from PIL import Image
from rembg import remove
import open_clip

# ----------------------------
# CONFIG - edit these
# ----------------------------
INVENTORY_ROOT = "/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/indexing/shirt"      # path to your folder of category folders
INDEX_OUTPUT = "shirt_inventory.index"
METADATA_OUTPUT = "shirt_metadata.json"
USE_BACKGROUND_REMOVAL = True           # set False to skip segmentation and test raw images
VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


# ----------------------------
# Load model once
# ----------------------------
def load_model():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Loading FashionCLIP model on device: {device}")
    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:Marqo/marqo-fashionCLIP"
    )
    model = model.to(device).eval()
    return model, preprocess, device


def remove_background(image: Image.Image) -> Image.Image:
    """Removes background, keeps subject (person + garment) on transparent bg,
    then flattens onto white background for consistent embedding input."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    result_bytes = remove(buf.getvalue())
    result_img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")

    # flatten transparent background to white
    white_bg = Image.new("RGBA", result_img.size, (255, 255, 255, 255))
    flattened = Image.alpha_composite(white_bg, result_img).convert("RGB")
    return flattened


def get_embedding(model, preprocess, device, image: Image.Image) -> np.ndarray:
    img_tensor = preprocess(image).unsqueeze(0).to(device)
    with torch.no_grad():
        emb = model.encode_image(img_tensor)
        emb = emb / emb.norm(dim=-1, keepdim=True)  # L2 normalize for cosine similarity
    return emb.cpu().numpy().flatten().astype("float32")


def find_images(product_path: str):
    files = []
    for ext in VALID_EXTENSIONS:
        files.extend(glob.glob(os.path.join(product_path, f"*{ext}")))
        files.extend(glob.glob(os.path.join(product_path, f"*{ext.upper()}")))
    return sorted(files)


def main():
    model, preprocess, device = load_model()

    embeddings = []
    metadata = []
    skipped = []

    categories = sorted(
        d for d in os.listdir(INVENTORY_ROOT)
        if os.path.isdir(os.path.join(INVENTORY_ROOT, d))
    )
    print(f"Found {len(categories)} categories: {categories}\n")

    for category in categories:
        category_path = os.path.join(INVENTORY_ROOT, category)
        products = sorted(
            d for d in os.listdir(category_path)
            if os.path.isdir(os.path.join(category_path, d))
        )

        for product_folder in products:
            product_path = os.path.join(category_path, product_folder)
            image_paths = find_images(product_path)

            if not image_paths:
                print(f"  [!] No images found in {product_path}, skipping")
                continue

            for img_path in image_paths:
                try:
                    img = Image.open(img_path).convert("RGB")

                    if USE_BACKGROUND_REMOVAL:
                        img = remove_background(img)

                    emb = get_embedding(model, preprocess, device, img)

                    embeddings.append(emb)
                    metadata.append({
                        "id": product_folder,
                        "category": category,
                        "angle": os.path.splitext(os.path.basename(img_path))[0],
                        "image_path": img_path,
                    })
                    print(f"  Indexed: {img_path}")

                except Exception as e:
                    print(f"  [ERROR] Skipped {img_path}: {e}")
                    skipped.append(img_path)

    if not embeddings:
        print("\nNo embeddings generated. Check your folder structure and image files.")
        return

    embeddings_np = np.array(embeddings).astype("float32")

    # Inner product on normalized vectors = cosine similarity
    index = faiss.IndexFlatIP(embeddings_np.shape[1])
    index.add(embeddings_np)

    faiss.write_index(index, INDEX_OUTPUT)
    with open(METADATA_OUTPUT, "w") as f:
        json.dump(metadata, f, indent=2)

    unique_products = len(set(m["id"] for m in metadata))
    print(f"\n{'='*50}")
    print(f"Done.")
    print(f"  Total images indexed: {len(metadata)}")
    print(f"  Unique products:      {unique_products}")
    print(f"  Categories:           {len(categories)}")
    print(f"  Skipped (errors):     {len(skipped)}")
    print(f"  Index saved to:       {INDEX_OUTPUT}")
    print(f"  Metadata saved to:    {METADATA_OUTPUT}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()