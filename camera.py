import cv2
import time

# Load Haar Cascade face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# Open laptop camera
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("Error: Camera not accessible")
    exit()

last_capture_time = 0
capture_interval = 15  # seconds between captures to avoid duplicates

print("Camera running... waiting for faces.")

while True:
    ret, frame = camera.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

    if len(faces) > 0:
        # Check time gap so it doesn’t capture too many frames
        if time.time() - last_capture_time > capture_interval:
            filename = f"face_{int(time.time())}.jpg"
            cv2.imwrite(filename, frame)
            print(f"✅ Face detected — saved {filename}")
            last_capture_time = time.time()

    # OPTIONAL: Show preview (comment out if you don’t want window)
    cv2.imshow("Auto Face Capture", frame)

    # Exit gracefully if 'q' is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
