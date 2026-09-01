import torch
import open_clip
import faiss
import json
import numpy as np
from PIL import Image
from rembg import remove
import io
import matplotlib.pyplot as plt


# ============================================================
# CONFIGURATION
# ============================================================

INDEX_PATH = (
    "/Users/aravindg/PycharmProjects/ReactJS/"
    "CameraAutomation/indexing/shirt_inventory.index"
)

METADATA_PATH = (
    "/Users/aravindg/PycharmProjects/ReactJS/"
    "CameraAutomation/indexing/shirt_metadata.json"
)

QUERY_IMAGE_PATH = "img_1.png"

USE_BACKGROUND_REMOVAL = True

TOP_K = 10


# ============================================================
# LOAD FASHIONCLIP MODEL
# ============================================================

def load_model():

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

    return model, preprocess, device


# ============================================================
# REMOVE IMAGE BACKGROUND
# ============================================================

def remove_background(image):

    buf = io.BytesIO()

    image.save(
        buf,
        format="PNG"
    )

    result_bytes = remove(
        buf.getvalue()
    )

    result_img = Image.open(
        io.BytesIO(result_bytes)
    ).convert("RGBA")

    # FashionCLIP works better with a normal background
    # than with transparent pixels.
    white_bg = Image.new(
        "RGBA",
        result_img.size,
        (255, 255, 255, 255)
    )

    result_img = Image.alpha_composite(
        white_bg,
        result_img
    )

    return result_img.convert("RGB")


# ============================================================
# CREATE FASHIONCLIP EMBEDDING
# ============================================================

def get_embedding(
        model,
        preprocess,
        device,
        image
):

    img_tensor = (
        preprocess(image)
        .unsqueeze(0)
        .to(device)
    )

    with torch.no_grad():

        embedding = model.encode_image(
            img_tensor
        )

        # Normalize embedding
        embedding = embedding / embedding.norm(
            dim=-1,
            keepdim=True
        )

    embedding = (
        embedding
        .cpu()
        .numpy()
        .flatten()
        .astype("float32")
    )

    return embedding


# ============================================================
# SEARCH FAISS
# ============================================================

def search_similar_products(
        index,
        metadata,
        query_embedding,
        top_k=10
):

    # Search more than TOP_K because the same product ID
    # may appear multiple times in the index.
    search_k = min(
        top_k * 5,
        index.ntotal
    )

    distances, indices = index.search(
        query_embedding.reshape(1, -1),
        k=search_k
    )

    results = []

    seen_ids = set()

    for dist, idx in zip(
            distances[0],
            indices[0]
    ):

        # FAISS can return -1 if there aren't enough results
        if idx < 0:
            continue

        item = metadata[idx]

        product_id = item["id"]

        # Avoid showing same product multiple times
        if product_id in seen_ids:
            continue

        seen_ids.add(product_id)

        results.append({
            "id": product_id,
            "category": item.get(
                "category",
                "Unknown"
            ),
            "image_path": item["image_path"],
            "score": float(dist)
        })

        if len(results) >= top_k:
            break

    return results


# ============================================================
# DISPLAY QUERY + RESULTS
# ============================================================

def display_results(
        query_image,
        results
):

    total_images = len(results) + 1

    # 4 images per row
    columns = 4

    rows = int(
        np.ceil(
            total_images / columns
        )
    )

    fig, axes = plt.subplots(
        rows,
        columns,
        figsize=(16, rows * 5)
    )

    # Flatten axes so they're easier to work with
    axes = np.array(axes).reshape(-1)

    # --------------------------------------------------------
    # QUERY IMAGE
    # --------------------------------------------------------

    axes[0].imshow(
        query_image
    )

    axes[0].set_title(
        "QUERY IMAGE",
        fontsize=14,
        fontweight="bold"
    )

    axes[0].axis("off")


    # --------------------------------------------------------
    # SEARCH RESULTS
    # --------------------------------------------------------

    for position, result in enumerate(
            results,
            start=1
    ):

        ax = axes[position]

        try:

            result_image = Image.open(
                result["image_path"]
            ).convert("RGB")

            ax.imshow(
                result_image
            )

            ax.set_title(
                f"Rank {position}\n"
                f"{result['category']}\n"
                f"ID: {result['id']}\n"
                f"Score: {result['score']:.3f}",
                fontsize=10
            )

        except Exception as e:

            ax.text(
                0.5,
                0.5,
                "Image could not\nbe loaded",
                horizontalalignment="center",
                verticalalignment="center"
            )

            print(
                f"Could not load image "
                f"{result['image_path']}: {e}"
            )

        ax.axis("off")


    # --------------------------------------------------------
    # HIDE UNUSED CELLS
    # --------------------------------------------------------

    for i in range(
            total_images,
            len(axes)
    ):

        axes[i].axis("off")


    plt.suptitle(
        "FashionCLIP - Similar Product Search",
        fontsize=18,
        fontweight="bold"
    )

    plt.tight_layout()

    plt.show()


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n===================================")
    print("FashionCLIP Similar Product Search")
    print("===================================\n")


    # --------------------------------------------------------
    # 1. LOAD FAISS INDEX
    # --------------------------------------------------------

    print("Loading FAISS index...")

    index = faiss.read_index(
        INDEX_PATH
    )

    print(
        f"FAISS index contains "
        f"{index.ntotal} vectors."
    )


    # --------------------------------------------------------
    # 2. LOAD METADATA
    # --------------------------------------------------------

    print("Loading metadata...")

    with open(
            METADATA_PATH,
            "r"
    ) as file:

        metadata = json.load(
            file
        )

    print(
        f"Metadata contains "
        f"{len(metadata)} entries."
    )


    # --------------------------------------------------------
    # 3. LOAD MODEL
    # --------------------------------------------------------

    print("Loading FashionCLIP...")

    model, preprocess, device = load_model()

    print("FashionCLIP loaded.")


    # --------------------------------------------------------
    # 4. LOAD QUERY IMAGE
    # --------------------------------------------------------

    print(
        f"Loading query image: "
        f"{QUERY_IMAGE_PATH}"
    )

    original_query_image = Image.open(
        QUERY_IMAGE_PATH
    ).convert("RGB")


    # --------------------------------------------------------
    # 5. BACKGROUND REMOVAL
    # --------------------------------------------------------

    if USE_BACKGROUND_REMOVAL:

        print(
            "Removing query image background..."
        )

        processed_query_image = remove_background(
            original_query_image
        )

    else:

        processed_query_image = (
            original_query_image
        )


    # --------------------------------------------------------
    # 6. CREATE EMBEDDING
    # --------------------------------------------------------

    print(
        "Generating FashionCLIP embedding..."
    )

    query_embedding = get_embedding(
        model,
        preprocess,
        device,
        processed_query_image
    )

    print(
        f"Embedding dimensions: "
        f"{query_embedding.shape[0]}"
    )


    # --------------------------------------------------------
    # 7. SEARCH SIMILAR PRODUCTS
    # --------------------------------------------------------

    print(
        f"\nSearching for top "
        f"{TOP_K} similar products..."
    )

    results = search_similar_products(
        index,
        metadata,
        query_embedding,
        TOP_K
    )


    # --------------------------------------------------------
    # 8. PRINT BASIC RESULT INFO
    # --------------------------------------------------------

    print(
        "\n----- SEARCH RESULTS -----\n"
    )

    for rank, result in enumerate(
            results,
            start=1
    ):

        print(
            f"Rank {rank}: "
            f"{result['category']} / "
            f"{result['id']} "
            f"- score: "
            f"{result['score']:.3f}"
        )


    # --------------------------------------------------------
    # 9. DISPLAY IMAGES
    # --------------------------------------------------------

    print(
        "\nDisplaying results..."
    )

    display_results(
        processed_query_image,
        results
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()