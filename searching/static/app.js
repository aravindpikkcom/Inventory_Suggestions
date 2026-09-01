const fileInput = document.getElementById("file-input");
const uploadLabel = document.getElementById("upload-label");
const hint = document.getElementById("hint");
const heroWrap = document.getElementById("hero-wrap");
const heroImage = document.getElementById("hero-image");
const heroCategory = document.getElementById("hero-category");
const heroScore = document.getElementById("hero-score");
const filmstrip = document.getElementById("filmstrip");
const thumbsEl = document.getElementById("thumbs");
const progressFill = document.getElementById("progress-fill");

const ROTATE_MS = 4500;

let results = [];
let activeIndex = 0;
let rotateTimer = null;

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  if (rotateTimer) clearInterval(rotateTimer);

  uploadLabel.textContent = "Searching…";
  hint.hidden = false;
  hint.textContent = "Matching against the inventory…";
  heroWrap.hidden = true;
  filmstrip.hidden = true;

  const formData = new FormData();
  formData.append("image", file);

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.error || "Search failed.");
    }

    const data = await response.json();
    results = (data.results || []).filter((r) => r.image);

    if (results.length === 0) {
      hint.textContent = "No matches were found for that photo.";
      uploadLabel.textContent = "Choose a photo";
      return;
    }

    renderThumbs();
    selectResult(0, true);

    hint.hidden = true;
    heroWrap.hidden = false;
    filmstrip.hidden = false;
    uploadLabel.textContent = "Choose another photo";

    startRotation();
  } catch (err) {
    hint.hidden = false;
    hint.textContent = err.message || "Something went wrong.";
    uploadLabel.textContent = "Choose a photo";
  }
});

function renderThumbs() {
  thumbsEl.innerHTML = "";

  results.forEach((result, i) => {
    const button = document.createElement("button");
    button.className = "thumb";
    button.setAttribute(
      "aria-label",
      `${result.category}, similarity ${result.score.toFixed(3)}`
    );

    const img = document.createElement("img");
    img.src = result.image;
    img.alt = "";
    button.appendChild(img);

    button.addEventListener("click", () => {
      selectResult(i, true);
      startRotation();
    });

    thumbsEl.appendChild(button);
  });
}

function selectResult(index, immediate) {
  activeIndex = index;
  const result = results[index];

  heroImage.classList.remove("visible");

  const swap = () => {
    heroImage.src = result.image;
    heroImage.classList.add("visible");
  };

  if (immediate) {
    swap();
  } else {
    setTimeout(swap, 150);
  }

  heroCategory.textContent = result.category;
  heroScore.textContent = `Similarity ${result.score.toFixed(3)}`;

  [...thumbsEl.children].forEach((el, i) => {
    el.classList.toggle("active", i === index);
  });
}

function restartProgressBar() {
  progressFill.classList.remove("animate");
  // Force reflow so the animation restarts from 0 each time.
  void progressFill.offsetWidth;
  progressFill.style.animationDuration = `${ROTATE_MS}ms`;
  progressFill.classList.add("animate");
}

function startRotation() {
  if (rotateTimer) clearInterval(rotateTimer);

  restartProgressBar();

  rotateTimer = setInterval(() => {
    const next = (activeIndex + 1) % results.length;
    selectResult(next, false);
    restartProgressBar();
  }, ROTATE_MS);
}
