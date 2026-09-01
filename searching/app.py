import os
import io
import json
import base64

import torch
import open_clip
import faiss
from PIL import Image
from rembg import remove
from flask import Flask, request, jsonify, render_template

# ============================================================
# CONFIGURATION
# (override any of these with environment variables so you
# don't have to edit the file for different machines/paths)
# ============================================================

INDEX_PATH = os.environ.get(
    "SHIRT_INDEX_PATH",
    "/Users/aravindg/PycharmProjects/ReactJS/"
    "CameraAutomation/indexing/shirt_inventory.index",
)

METADATA_PATH = os.environ.get(
    "SHIRT_METADATA_PATH",
    "/Users/aravindg/PycharmProjects/ReactJS/"
    "CameraAutomation/indexing/shirt_metadata.json",
)

TOP_K = int(os.environ.get("SHIRT_TOP_K", 5))

app = Flask(__name__)

# Everything expensive (model, index, metadata) is loaded once,
# lazily, on first request, and kept here.
_state = {
    "model": None,
    "preprocess": None,
    "device": None,
    "index": None,
    "metadata": None,
}


def load_resources():
    """Load the FAISS index, metadata and FashionCLIP model once."""

    if _state["index"] is None:
        print("Loading FAISS index...")
        _state["index"] = faiss.read_index(INDEX_PATH)
        print(f"FAISS index contains {_state['index'].ntotal} vectors.")

    if _state["metadata"] is None:
        print("Loading metadata...")
        with open(METADATA_PATH, "r") as file:
            _state["metadata"] = json.load(file)
        print(f"Metadata contains {len(_state['metadata'])} entries.")

    if _state["model"] is None:
        print("Loading FashionCLIP...")

        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

        print(f"Using device: {device}")

        model, _, preprocess = open_clip.create_model_and_transforms(
            "hf-hub:Marqo/marqo-fashionCLIP"
        )
        model = model.to(device).eval()

        _state["model"] = model
        _state["preprocess"] = preprocess
        _state["device"] = device

        print("FashionCLIP loaded.")

    return _state


def remove_background(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    result_bytes = remove(buf.getvalue())
    result_img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")

    # FashionCLIP works better with a normal background
    # than with transparent pixels.
    white_bg = Image.new("RGBA", result_img.size, (255, 255, 255, 255))
    result_img = Image.alpha_composite(white_bg, result_img)

    return result_img.convert("RGB")


def get_embedding(model, preprocess, device, image):
    img_tensor = preprocess(image).unsqueeze(0).to(device)

    with torch.no_grad():
        embedding = model.encode_image(img_tensor)
        embedding = embedding / embedding.norm(dim=-1, keepdim=True)

    return embedding.cpu().numpy().flatten().astype("float32")


def search_similar_products(index, metadata, query_embedding, top_k=5):
    # Search more than top_k because the same product ID
    # may appear multiple times in the index.
    search_k = min(top_k * 5, index.ntotal)

    distances, indices = index.search(query_embedding.reshape(1, -1), k=search_k)

    results = []
    seen_ids = set()

    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0:
            continue

        item = metadata[idx]
        product_id = item["id"]

        if product_id in seen_ids:
            continue

        seen_ids.add(product_id)

        results.append({
            "id": product_id,
            "category": item.get("category", "Unknown"),
            "image_path": item["image_path"],
            "score": float(dist),
        })

        if len(results) >= top_k:
            break

    return results


def image_to_data_uri(image):
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def path_to_data_uri(path):
    with Image.open(path) as img:
        return image_to_data_uri(img.convert("RGB"))


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def api_search():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded."}), 400

    uploaded = request.files["image"]

    try:
        original_image = Image.open(uploaded.stream).convert("RGB")
    except Exception:
        return jsonify({"error": "Could not read the uploaded image."}), 400

    remove_bg = request.form.get("remove_background", "true").lower() != "false"

    try:
        state = load_resources()
    except Exception as exc:
        return jsonify({"error": f"Could not load model or index: {exc}"}), 500

    processed_image = (
        remove_background(original_image) if remove_bg else original_image
    )

    query_embedding = get_embedding(
        state["model"], state["preprocess"], state["device"], processed_image
    )

    results = search_similar_products(
        state["index"], state["metadata"], query_embedding, TOP_K
    )

    payload_results = []
    for rank, result in enumerate(results, start=1):
        try:
            image_data = path_to_data_uri(result["image_path"])
        except Exception as exc:
            image_data = None
            print(f"Could not load image {result['image_path']}: {exc}")

        payload_results.append({
            "rank": rank,
            "id": result["id"],
            "category": result["category"],
            "score": result["score"],
            "image": image_data,
        })

    return jsonify({
        "query_image": image_to_data_uri(processed_image),
        "results": payload_results,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001)
