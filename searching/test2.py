import torch
import open_clip
import faiss
import json
from PIL import Image
from rembg import remove
import io
import os

from flask import Flask, jsonify, send_file, render_template_string
from flask_cors import CORS


# ============================================================
# CONFIG
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
TOP_K = 5


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)
CORS(app)


# ============================================================
# LOAD FASHIONCLIP
# ============================================================

def load_model():

    if torch.backends.mps.is_available():
        device = "mps"

    elif torch.cuda.is_available():
        device = "cuda"

    else:
        device = "cpu"

    print("Using device:", device)

    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:Marqo/marqo-fashionCLIP"
    )

    model = model.to(device).eval()

    return model, preprocess, device


# ============================================================
# BACKGROUND REMOVAL
# ============================================================

def remove_background(image):

    buf = io.BytesIO()

    image.save(buf, format="PNG")

    result_bytes = remove(buf.getvalue())

    result_img = Image.open(
        io.BytesIO(result_bytes)
    ).convert("RGBA")

    white_bg = Image.new(
        "RGBA",
        result_img.size,
        (255, 255, 255, 255)
    )

    return Image.alpha_composite(
        white_bg,
        result_img
    ).convert("RGB")


# ============================================================
# IMAGE EMBEDDING
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

        emb = model.encode_image(
            img_tensor
        )

        emb = emb / emb.norm(
            dim=-1,
            keepdim=True
        )

    return (
        emb
        .cpu()
        .numpy()
        .flatten()
        .astype("float32")
    )


# ============================================================
# LOAD INDEX + METADATA + MODEL
# ============================================================

print("Loading FAISS index...")

index = faiss.read_index(
    INDEX_PATH
)


print("Loading metadata...")

with open(
    METADATA_PATH,
    "r"
) as file:

    metadata = json.load(file)


print("Loading FashionCLIP...")

model, preprocess, device = load_model()

print("FashionCLIP ready.")


# ============================================================
# GET TOP 5 SIMILAR PRODUCTS
# ============================================================

def get_similar_products():

    query_img = Image.open(
        QUERY_IMAGE_PATH
    ).convert("RGB")


    if USE_BACKGROUND_REMOVAL:

        query_img = remove_background(
            query_img
        )


    query_emb = get_embedding(
        model,
        preprocess,
        device,
        query_img
    ).reshape(1, -1)


    search_k = min(
        50,
        index.ntotal
    )


    distances, indices = index.search(
        query_emb,
        k=search_k
    )


    results = []

    seen_ids = set()


    for dist, idx in zip(
        distances[0],
        indices[0]
    ):

        if idx < 0:
            continue


        item = metadata[idx]

        product_id = item["id"]


        if product_id in seen_ids:
            continue


        seen_ids.add(
            product_id
        )


        results.append({

            "id": product_id,

            "category": item.get(
                "category",
                "shirt"
            ),

            "score": float(dist),

            "image_url":
                f"/product-image/{idx}"

        })


        if len(results) == TOP_K:
            break


    return results


# ============================================================
# WEB APPLICATION
# ============================================================

HTML_PAGE = """
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Fashion Suggestions</title>


<style>

* {
    box-sizing: border-box;
}


body {

    margin: 0;

    min-height: 100vh;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    background:
        #f5f5f3;

    color: #111;

}


/* ==========================================================
   MAIN APPLICATION
========================================================== */

.app {

    min-height: 100vh;

    display: flex;

    flex-direction: column;

}


/* ==========================================================
   HEADER
========================================================== */

.header {

    height: 70px;

    display: flex;

    align-items: center;

    justify-content: center;

    font-size: 14px;

    letter-spacing: 4px;

    font-weight: 600;

}


.header span {

    color: #777;

}


/* ==========================================================
   MAIN DISPLAY AREA
========================================================== */

.main-area {

    flex: 1;

    display: flex;

    justify-content: center;

    align-items: center;

    padding:

        10px
        20px
        20px;

}


/* ==========================================================
   MAIN PRODUCT
========================================================== */

.main-product {

    position: relative;

    width: min(
        430px,
        85vw
    );

    height: 540px;

    display: flex;

    justify-content: center;

    align-items: center;

}


.main-product img {

    max-width: 100%;

    max-height: 100%;

    object-fit: contain;

    opacity: 1;

    transform: scale(1);

    transition:

        opacity
        0.35s
        ease,

        transform
        0.45s
        ease;

}


.main-product img.fade {

    opacity: 0;

    transform: scale(
        0.97
    );

}


/* ==========================================================
   LOADING
========================================================== */

.loading {

    position: absolute;

    font-size: 13px;

    letter-spacing: 2px;

    color: #777;

}


/* ==========================================================
   BOTTOM SECTION
========================================================== */

.bottom {

    padding:

        10px
        20px
        40px;

}


/* ==========================================================
   SUGGESTION LABEL
========================================================== */

.suggestion-label {

    text-align: center;

    margin-bottom: 18px;

    font-size: 11px;

    letter-spacing: 3px;

    color: #777;

}


/* ==========================================================
   CAROUSEL
========================================================== */

.carousel {

    display: flex;

    justify-content: center;

    align-items: center;

    gap: 18px;

}


/* ==========================================================
   THUMBNAIL
========================================================== */

.thumbnail {

    position: relative;

    width: 82px;

    height: 105px;

    padding: 0;

    border: 1px solid transparent;

    background: white;

    cursor: pointer;

    opacity: 0.42;

    overflow: hidden;

    transition:

        opacity
        0.35s
        ease,

        transform
        0.35s
        ease,

        border
        0.35s
        ease;

}


.thumbnail img {

    width: 100%;

    height: 100%;

    object-fit: cover;

}


/* ==========================================================
   ACTIVE PRODUCT
========================================================== */

.thumbnail.active {

    opacity: 1;

    transform: scale(
        1.12
    );

    border: 2px solid #111;

}


/* ==========================================================
   PRODUCT DOT
========================================================== */

.thumbnail::after {

    content: "";

    position: absolute;

    left: 50%;

    bottom: 5px;

    transform:
        translateX(-50%);

    width: 4px;

    height: 4px;

    border-radius: 50%;

    background: transparent;

}


.thumbnail.active::after {

    background: #111;

}


/* ==========================================================
   ERROR
========================================================== */

.error {

    text-align: center;

    color: #777;

    padding: 40px;

}


/* ==========================================================
   MOBILE
========================================================== */

@media (
    max-width: 600px
) {

    .main-product {

        height: 430px;

    }


    .carousel {

        gap: 8px;

    }


    .thumbnail {

        width: 58px;

        height: 78px;

    }


    .bottom {

        padding-left: 10px;

        padding-right: 10px;

    }

}

</style>

</head>



<body>


<div class="app">


    <!-- ==============================================
         HEADER
    =============================================== -->

    <div class="header">

        STYLE

        <span>
            &nbsp;SUGGESTIONS
        </span>

    </div>



    <!-- ==============================================
         LARGE SELECTED IMAGE
    =============================================== -->

    <div class="main-area">


        <div class="main-product">


            <div
                id="loading"
                class="loading"
            >

                FINDING YOUR STYLE...

            </div>


            <img
                id="mainImage"
                alt="Selected fashion suggestion"
                style="display:none;"
            >


        </div>


    </div>



    <!-- ==============================================
         BOTTOM 5 PRODUCTS
    =============================================== -->

    <div class="bottom">


        <div class="suggestion-label">

            SIMILAR STYLES

        </div>


        <div
            id="carousel"
            class="carousel"
        >

        </div>


    </div>


</div>



<script>

/* ==========================================================
   VARIABLES
========================================================== */

let products = [];

let currentIndex = 0;

let timer = null;


/*
 * Change this if you want
 * faster/slower rotation.
 *
 * 3000 = 3 seconds
 */

const ROTATION_TIME = 3000;



/* ==========================================================
   LOAD TOP 5 FROM FASHIONCLIP
========================================================== */

async function loadRecommendations() {

    try {

        const response =
            await fetch(
                "/recommendations"
            );


        if (!response.ok) {

            throw new Error(
                "Recommendation API failed"
            );

        }


        products =
            await response.json();


        console.log(
            "FashionCLIP recommendations:",
            products
        );


        if (
            !products ||
            products.length === 0
        ) {

            showError(
                "No suggestions found"
            );

            return;

        }


        createCarousel();


        selectProduct(
            0,
            false
        );


        startRotation();

    }

    catch (error) {

        console.error(
            error
        );


        showError(
            "Unable to load suggestions"
        );

    }

}



/* ==========================================================
   CREATE 5 BOTTOM IMAGES
========================================================== */

function createCarousel() {

    const carousel =
        document.getElementById(
            "carousel"
        );


    carousel.innerHTML = "";


    products.forEach(
        (product, index) => {


            const button =
                document.createElement(
                    "button"
                );


            button.type =
                "button";


            button.className =
                "thumbnail";


            button.setAttribute(
                "aria-label",
                "Suggestion " + (index + 1)
            );


            const image =
                document.createElement(
                    "img"
                );


            image.src =
                product.image_url;


            image.alt =
                product.id;


            button.appendChild(
                image
            );


            /*
             * CLICK PRODUCT
             */

            button.addEventListener(
                "click",
                function () {


                    selectProduct(
                        index,
                        true
                    );


                }
            );


            carousel.appendChild(
                button
            );

        }
    );

}



/* ==========================================================
   SELECT PRODUCT
========================================================== */

function selectProduct(
    index,
    restartTimer
) {

    currentIndex = index;


    const mainImage =
        document.getElementById(
            "mainImage"
        );


    const loading =
        document.getElementById(
            "loading"
        );


    const product =
        products[
            currentIndex
        ];


    /*
     * FADE OUT
     */

    mainImage.classList.add(
        "fade"
    );


    /*
     * Preload next image
     */

    const preload =
        new Image();


    preload.onload =
        function () {


            mainImage.src =
                product.image_url;


            mainImage.alt =
                product.id;


            loading.style.display =
                "none";


            mainImage.style.display =
                "block";


            /*
             * Small delay lets browser
             * render fade correctly
             */

            requestAnimationFrame(
                function () {


                    mainImage.classList.remove(
                        "fade"
                    );


                }
            );

        };


    preload.onerror =
        function () {


            console.error(
                "Could not load image:",
                product.image_url
            );


        };


    preload.src =
        product.image_url;


    updateActiveThumbnail();


    if (restartTimer) {

        restartRotation();

    }

}



/* ==========================================================
   HIGHLIGHT BOTTOM PRODUCT
========================================================== */

function updateActiveThumbnail() {

    const thumbnails =
        document.querySelectorAll(
            ".thumbnail"
        );


    thumbnails.forEach(
        function (
            thumbnail,
            index
        ) {


            if (
                index ===
                currentIndex
            ) {

                thumbnail.classList.add(
                    "active"
                );

            }

            else {

                thumbnail.classList.remove(
                    "active"
                );

            }


        }
    );

}



/* ==========================================================
   NEXT PRODUCT
========================================================== */

function nextProduct() {


    currentIndex++;


    if (
        currentIndex >=
        products.length
    ) {

        currentIndex = 0;

    }


    selectProduct(
        currentIndex,
        false
    );

}



/* ==========================================================
   AUTO ROTATION
========================================================== */

function startRotation() {


    if (
        products.length <= 1
    ) {

        return;

    }


    timer =
        setInterval(
            nextProduct,
            ROTATION_TIME
        );

}



/* ==========================================================
   RESTART ROTATION AFTER CLICK
========================================================== */

function restartRotation() {


    if (timer) {

        clearInterval(
            timer
        );

    }


    startRotation();

}



/* ==========================================================
   ERROR
========================================================== */

function showError(
    message
) {


    document.getElementById(
        "loading"
    ).innerHTML =
        message;


}



/* ==========================================================
   START
========================================================== */

loadRecommendations();

</script>


</body>

</html>
"""


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HTML_PAGE
    )


# ============================================================
# RECOMMENDATIONS API
# ============================================================

@app.route(
    "/recommendations",
    methods=["GET"]
)
def recommendations():

    results = get_similar_products()

    return jsonify(
        results
    )


# ============================================================
# SERVE INVENTORY IMAGE
# ============================================================

@app.route(
    "/product-image/<int:index_id>",
    methods=["GET"]
)
def product_image(index_id):


    if (
        index_id < 0
        or
        index_id >= len(metadata)
    ):

        return {
            "error":
                "Invalid image index"
        }, 404


    image_path = metadata[
        index_id
    ]["image_path"]


    if not os.path.exists(
        image_path
    ):

        print(
            "IMAGE NOT FOUND:",
            image_path
        )

        return {
            "error":
                "Image not found"
        }, 404


    return send_file(
        image_path
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print()
    print("==============================")
    print("Fashion Recommendation App")
    print("==============================")
    print()
    print(
        "Open:"
    )
    print(
        "http://127.0.0.1:6000/"
    )
    print()

    app.run(
        host="127.0.0.1",
        port=6000,
        debug=False
    )