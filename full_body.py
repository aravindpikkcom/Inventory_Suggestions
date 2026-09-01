import cv2
import time

# Load Haar Cascade full body detector
body_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_fullbody.xml")

# Open laptop camera
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("Error: Camera not accessible")
    exit()

last_capture_time = 0
capture_interval = 5  # seconds between captures

print("Camera running... waiting for full body.")

while True:
    ret, frame = camera.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bodies = body_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3)

    # If at least one full body detected
    if len(bodies) > 0:
        if time.time() - last_capture_time > capture_interval:
            filename = f"fullbody_{int(time.time())}.jpg"
            cv2.imwrite(filename, frame)
            print(f"✅ Full body detected — saved {filename}")
            last_capture_time = time.time()

        # Draw rectangles around detected bodies
        for (x, y, w, h) in bodies:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)

    # Show live preview
    cv2.imshow("Full Body Detector", frame)

    # Exit on pressing 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
