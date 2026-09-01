import os
import time
import subprocess
import cv2
import mediapipe as mp
import numpy as np
from ultralytics import YOLO
from datetime import datetime

# =======================
# Config
# =======================
CAPTURE_INTERVAL_SEC = 20  # wait this long between saved images
SAVE_DIR = "./captures"    # local folder to save before scp (will be created)

# Remote SCP details
REMOTE_USER = "xyz"
REMOTE_HOST = "abc.local"
REMOTE_DIR  = "/home/xyz/reflexn/bundle/automation/artifacts/captures/"
SSH_KEY_PATH = None  # e.g. "/home/xyz/.ssh/id_rsa" or keep None to use your default ssh config

os.makedirs(SAVE_DIR, exist_ok=True)

def scp_upload(local_path: str) -> None:
    """Upload the captured file via scp with IdentitiesOnly=yes."""
    cmd = ["scp", "-o", "IdentitiesOnly=yes"]
    if SSH_KEY_PATH:
        cmd += ["-i", SSH_KEY_PATH]
    cmd += [local_path, f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_DIR}"]

    try:
        # capture_output to log stdout/stderr on error
        res = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"📤 SCP OK: {os.path.basename(local_path)} -> {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_DIR}")
    except subprocess.CalledProcessError as e:
        print("❌ SCP failed")
        print("stdout:", e.stdout)
        print("stderr:", e.stderr)

# =======================
# Models
# =======================
model = YOLO("yolov8n.pt")  # person detection

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=False,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# =======================
# Camera
# =======================
camera = cv2.VideoCapture(0)
if not camera.isOpened():
    print("Error: Camera not accessible")
    raise SystemExit(1)

last_capture_time = 0.0
prev_centroid = None

print("Camera running... detecting full body with face, hands, and legs visible.")
print("Press 'q' to quit.")

def landmark_visible(lm):
    return lm.visibility > 0.6

while True:
    ret, frame = camera.read()
    if not ret:
        break

    h, w = frame.shape[:2]
    results = model(frame, verbose=False)

    now = time.time()
    for r in results:
        boxes = r.boxes
        for box in boxes:
            cls = int(box.cls[0])  # class ID
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            box_h = y2 - y1

            # Only consider "person" (COCO class 0)
            if cls == 0 and conf > 0.6 and box_h >= 0.6 * h:
                person_crop = frame[y1:y2, x1:x2]

                # Mediapipe pose
                rgb_crop = cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB)
                pose_results = pose.process(rgb_crop)

                if pose_results.pose_landmarks:
                    lms = pose_results.pose_landmarks.landmark
                    face   = lms[0]
                    lwrist = lms[15]
                    rwrist = lms[16]
                    lankle = lms[27]
                    rankle = lms[28]

                    if (landmark_visible(face) and landmark_visible(lwrist) and
                        landmark_visible(rwrist) and landmark_visible(lankle) and landmark_visible(rankle)):

                        # Centroid to check stillness
                        centroid = np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0])
                        still = True
                        if prev_centroid is not None:
                            dist = np.linalg.norm(centroid - prev_centroid)
                            if dist > 10:  # movement threshold (pixels)
                                still = False
                        prev_centroid = centroid

                        # Rate-limit captures: only once every CAPTURE_INTERVAL_SEC
                        if still and (now - last_capture_time >= CAPTURE_INTERVAL_SEC):
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"person_fullbody_{ts}.jpg"
                            local_path = os.path.join(SAVE_DIR, filename)

                            # Save full frame (you can save the crop if preferred)
                            cv2.imwrite(local_path, frame)
                            print(f"✅ Saved {local_path}")

                            # SCP upload
                            scp_upload(local_path)

                            # Update cooldown
                            last_capture_time = now


                # Draw detection box (for preview)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"Person {conf:.2f}", (x1, max(y1-10, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    # Comment these lines if running headless
    cv2.imshow("YOLOv8 + Mediapipe Full Body Detector", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
