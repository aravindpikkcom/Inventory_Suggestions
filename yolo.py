import cv2
import time
import mediapipe as mp
from ultralytics import YOLO
import numpy as np

# Load YOLOv8 model
model = YOLO("yolov8n.pt")  # person detection

# Mediapipe Pose
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5)

# Open camera
camera = cv2.VideoCapture(0)
if not camera.isOpened():
    print("Error: Camera not accessible")
    exit()

last_capture_time = 0
capture_interval = 5  # seconds
prev_centroid = None

print("Camera running... detecting full body with face, hands, and legs visible.")

while True:
    ret, frame = camera.read()
    if not ret:
        break

    h, w = frame.shape[:2]
    results = model(frame, verbose=False)

    for r in results:
        boxes = r.boxes
        for box in boxes:
            cls = int(box.cls[0])  # class ID
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            box_h = y2 - y1

            # Only consider "person"
            if cls == 0 and conf > 0.6 and box_h >= 0.6 * h:
                person_crop = frame[y1:y2, x1:x2]

                # Run Mediapipe pose on the cropped person
                rgb_crop = cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB)
                pose_results = pose.process(rgb_crop)

                if pose_results.pose_landmarks:
                    landmarks = pose_results.pose_landmarks.landmark

                    # Key points: Nose (face), wrists, ankles
                    face = landmarks[0]
                    lwrist = landmarks[15]
                    rwrist = landmarks[16]
                    lankle = landmarks[27]
                    rankle = landmarks[28]

                    def visible(lm):
                        return lm.visibility > 0.6

                    if visible(face) and visible(lwrist) and visible(rwrist) and visible(lankle) and visible(rankle):
                        # Compute centroid of bounding box
                        centroid = np.array([(x1 + x2) / 2, (y1 + y2) / 2])

                        # Check if person is still
                        still = True
                        if prev_centroid is not None:
                            dist = np.linalg.norm(centroid - prev_centroid)
                            if dist > 10:  # movement threshold
                                still = False
                        prev_centroid = centroid

                        if still and (time.time() - last_capture_time > capture_interval):
                            filename = f"person_fullbody_{int(time.time())}.jpg"
                            cv2.imwrite(filename, frame)
                            print(f"✅ Full body (face+hands+legs visible & still) — saved {filename}")
                            last_capture_time = time.time()

                # Draw detection box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, "Person", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.imshow("YOLOv8 + Mediapipe Full Body Detector", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
