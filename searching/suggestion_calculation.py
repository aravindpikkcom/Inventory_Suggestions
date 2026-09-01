import torch
import open_clip
import faiss, json
import numpy as np
from PIL import Image
from rembg import remove
import io

def load_model():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:Marqo/marqo-fashionCLIP"
    )
    model = model.to(device).eval()
    return model, preprocess, device

def remove_background(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    result_bytes = remove(buf.getvalue())
    result_img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
    white_bg = Image.new("RGBA", result_img.size, (255, 255, 255, 255))
    return Image.alpha_composite(white_bg, result_img).convert("RGB")

def get_embedding(model, preprocess, device, image):
    img_tensor = preprocess(image).unsqueeze(0).to(device)
    with torch.no_grad():
        emb = model.encode_image(img_tensor)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb.cpu().numpy().flatten().astype("float32")

USE_BACKGROUND_REMOVAL = True

# --- now your actual query logic ---
index = faiss.read_index("/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/indexing/shirt_inventory.index")
metadata = json.load(open("/Users/aravindg/PycharmProjects/ReactJS/CameraAutomation/indexing/shirt_metadata.json"))
model, preprocess, device = load_model()

query_img = Image.open("img_1.png").convert("RGB")
if USE_BACKGROUND_REMOVAL:
    query_img = remove_background(query_img)
query_emb = get_embedding(model, preprocess, device, query_img).reshape(1, -1)

distances, indices = index.search(query_emb, k=10)
seen_ids = set()
for dist, i in zip(distances[0], indices[0]):
    m = metadata[i]
    if m["id"] not in seen_ids:
        print(f"{m['category']} / {m['id']} - score: {dist:.3f} - {m['image_path']}")
        seen_ids.add(m["id"])