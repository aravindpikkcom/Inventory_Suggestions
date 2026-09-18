"""
Smart Mirror - Identify + Outfit Pair Lookup
==============================================
Full runtime flow:
    1. Take a live customer photo.
    2. Embed it with FashionCLIP and search the shirt FAISS index to
       identify the closest matching catalog shirt(s).
    3. Look up each identified shirt's precomputed pairing entry in
       outfit_pairs.json (built offline by build_outfit_pairs.py) to get
       its store location and its top pant matches (with their locations).

This intentionally does NO color/formality computation or embedding
similarity between shirt and pant here - all of that was already baked
into outfit_pairs.json ahead of time. This script only does identification
(shirt in photo -> catalog shirt ID) and a dictionary lookup.

Run:
    pip install torch open_clip_torch faiss-cpu rembg pillow numpy --break-system-packages
    python identify_and_pair.py --image img_1.png
"""

import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # must be set before faiss/torch/onnxruntime import
                                                          # avoids the macOS OpenMP-conflict SIGSEGV when
                                                          # faiss + torch + rembg's onnxruntime all load
                                                          # their own copies of libomp into the same process
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
# The above forces every native library (faiss, torch, onnxruntime) to run
# single-threaded. With two different OpenMP runtimes loaded in the same
# process, letting each spin up its own multi-threaded pool is what causes
# real memory corruption (crashes on a background thread, not the main
# thread) even after KMP_DUPLICATE_LIB_OK silences the abort message.

import io
import json

import faiss
faiss.omp_set_num_threads(1)
import numpy as np
import torch
import open_clip
from PIL import Image
from rembg import remove

# ----------------------------
# CONFIG - edit these
# ----------------------------
SHIRT_INDEX_PATH = "/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/indexing/shirt_inventory.index"
SHIRT_METADATA_PATH = "/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/indexing/shirt_metadata.json"
OUTFIT_PAIRS_PATH = "outfit_pairs.json"  # produced by build_outfit_pairs.py
RESULT_OUTPUT_PATH = "identification_result.json"  # final output written each run

# Path to the customer's captured shirt photo - edit this directly and hit
# Run in PyCharm, no CLI args needed.
QUERY_IMAGE_PATH = "/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/suitability_embedding/img_1.png"

TOP_K_SEARCH = 10      # how many raw FAISS hits to pull before dedup
TOP_N_SHIRTS = 5       # how many unique identified shirts to report
USE_BACKGROUND_REMOVAL = True


# ----------------------------
# MODEL / EMBEDDING
# ----------------------------
def load_model():
    device = "cpu"  # temporarily forced to rule out an MPS-related segfault;
                     # once stable, you can try:
                     # device = "mps" if torch.backends.mps.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:Marqo/marqo-fashionCLIP"
    )
    model = model.to(device).eval()
    return model, preprocess, device


def remove_background(image: Image.Image) -> Image.Image:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    result_bytes = remove(buf.getvalue())
    result_img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
    white_bg = Image.new("RGBA", result_img.size, (255, 255, 255, 255))
    return Image.alpha_composite(white_bg, result_img).convert("RGB")


def get_embedding(model, preprocess, device, image: Image.Image) -> np.ndarray:
    img_tensor = preprocess(image).unsqueeze(0).to(device)
    with torch.no_grad():
        emb = model.encode_image(img_tensor)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb.cpu().numpy().flatten().astype("float32")


# ----------------------------
# IDENTIFICATION
# ----------------------------
def identify_top_shirts(query_image_path: str) -> list:
    """Returns a list of dicts (deduped by product id, ranked by FAISS
    score) for the top matching catalog shirts.

    NOTE: this assumes shirt_metadata.json is in the exact same row order
    as the vectors in shirt_inventory.index (i.e. metadata[i] corresponds
    to the i-th vector added to the index). If index_inventory.py ever
    reorders, filters, or dedupes between building the metadata list and
    building the index, this lookup will silently return the wrong
    product - verify that invariant holds before trusting this in
    production.
    """
    index = faiss.read_index(SHIRT_INDEX_PATH)
    metadata = json.load(open(SHIRT_METADATA_PATH))
    model, preprocess, device = load_model()

    query_img = Image.open(query_image_path).convert("RGB")
    if USE_BACKGROUND_REMOVAL:
        query_img = remove_background(query_img)
    query_emb = get_embedding(model, preprocess, device, query_img).reshape(1, -1)

    distances, indices = index.search(query_emb, k=TOP_K_SEARCH)

    results = []
    seen_ids = set()
    for dist, i in zip(distances[0], indices[0]):
        if i < 0 or i >= len(metadata):
            continue  # FAISS pads with -1 if fewer than k vectors exist
        m = metadata[i]
        if m["id"] in seen_ids:
            continue
        seen_ids.add(m["id"])
        results.append({
            "id": m["id"],
            "category": m["category"],
            "score": float(dist),
            "image_path": m["image_path"],
        })
        if len(results) == TOP_N_SHIRTS:
            break

    return results


# ----------------------------
# OUTFIT PAIR LOOKUP
# ----------------------------
def lookup_pairings(shirt_ids: list, outfit_pairs_path: str = OUTFIT_PAIRS_PATH) -> dict:
    """Looks up each identified shirt id in the precomputed outfit_pairs.json.
    Returns {shirt_id: {"location": ..., "matches": [...]} } for shirts
    that have a precomputed entry. Shirts with no entry (e.g. added to the
    catalog after outfit_pairs.json was last built) are skipped with a
    warning."""
    with open(outfit_pairs_path) as f:
        outfit_pairs = json.load(f)

    resolved = {}
    for shirt_id in shirt_ids:
        entry = outfit_pairs.get(shirt_id)
        if entry is None:
            print(f"  [WARN] No precomputed pairing for '{shirt_id}' "
                  f"- outfit_pairs.json may need to be rebuilt.")
            continue
        resolved[shirt_id] = entry

    return resolved


# ----------------------------
# BUILD FINAL RESULT
# ----------------------------
def build_result(top_shirts: list, pairings: dict) -> dict:
    """Merges each identified shirt's FAISS score with its precomputed
    location + pant matches into one final structure, ready to write out
    as JSON. Shape mirrors outfit_pairs.json but scoped to this single
    query, with 'score' added per shirt."""
    shirts_out = {}
    for s in top_shirts:
        entry = pairings.get(s["id"])
        shirts_out[s["id"]] = {
            "score": s["score"],
            "category": s["category"],
            "image_path": s["image_path"],
            "location": entry["location"] if entry else None,
            "matches": entry["matches"] if entry else [],
        }

    return {
        "query_image": QUERY_IMAGE_PATH,
        "shirts": shirts_out,
    }


# ----------------------------
# MAIN
# ----------------------------
def main():
    print(f"Identifying shirt from '{QUERY_IMAGE_PATH}'...")
    top_shirts = identify_top_shirts(QUERY_IMAGE_PATH)

    if not top_shirts:
        print("No matches found.")
        return

    print(f"\nTop {len(top_shirts)} identified shirt(s):")
    for s in top_shirts:
        print(f"  {s['id']}  (category={s['category']}, score={s['score']:.3f})")
        print(f"    image: {s['image_path']}")

    shirt_ids = [s["id"] for s in top_shirts]

    print("\nLooking up precomputed outfit pairings...")
    pairings = lookup_pairings(shirt_ids)

    print(f"\n{'='*60}")
    for shirt_id, entry in pairings.items():
        print(f"Shirt: {shirt_id}")
        print(f"  Location: {entry['location']}")
        if not entry["matches"]:
            print("  No pant matches found for this shirt.")
        for pant in entry["matches"]:
            print(f"  Pant match: {pant['id']}")
            print(f"    Location: {pant['location']}")
        print(f"{'-'*60}")

    result = build_result(top_shirts, pairings)
    with open(RESULT_OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nWrote final result to '{RESULT_OUTPUT_PATH}'")


if __name__ == "__main__":
    main()