"""
Gesture Mouse Control (Python / OpenCV / MediaPipe / PyAutoGUI)
-----------------------------------------------------------------
Moves your REAL mouse cursor with your index fingertip and performs a real
click when you pinch (thumb tip + index tip together). This lets you control
ANY on-screen window — including gesture-target-app.html open in your browser —
without that page needing any camera/gesture code itself.

Install dependencies first (in PyCharm's terminal or a venv):
    pip install opencv-python mediapipe pyautogui

Setup:
    1. Open gesture-target-app.html in your browser (double-click it, or serve
       it with `python -m http.server` and visit http://localhost:8000/).
    2. Arrange the browser window and this script's small camera preview
       window so both are visible (e.g. side by side).
    3. Run this script:  python gesture_mouse_control.py
    4. Move your hand in front of the camera. The system mouse cursor follows
       your index fingertip. Pinch to click.

Safety:
    PyAutoGUI's fail-safe is left ON: slam the mouse into a screen corner
    (drag it there yourself) to instantly abort if gesture control misbehaves.

Press 'q' or ESC in the camera preview window to quit.
"""

import time
import cv2
import mediapipe as mp
import pyautogui

# ---------- Config ----------
CAM_INDEX = 0
FRAME_W, FRAME_H = 640, 480
MAX_HANDS = 1
DETECTION_CONF = 0.6
TRACKING_CONF = 0.6

PINCH_THRESHOLD_RATIO = 0.45   # pinch if thumb-index distance < this * hand size
SMOOTHING = 0.5                # 0 = no smoothing (jittery), closer to 1 = smoother but laggier
CLICK_COOLDOWN_S = 0.6         # minimum time between clicks to avoid double-firing

# Active tracking region within the camera frame (as a fraction of frame size).
# Keeping your hand within this box maps to the FULL screen, so you don't have
# to reach to the physical edges of the camera view to hit screen edges.
ACTIVE_MARGIN_X = 0.15
ACTIVE_MARGIN_Y = 0.15

pyautogui.FAILSAFE = True   # move mouse to a screen corner to abort
pyautogui.PAUSE = 0         # no artificial delay between pyautogui calls

screen_w, screen_h = pyautogui.size()


def hand_size(landmarks, w, h):
    wrist = landmarks[0]
    mcp = landmarks[5]
    dx = (wrist.x - mcp.x) * w
    dy = (wrist.y - mcp.y) * h
    return max(1.0, (dx ** 2 + dy ** 2) ** 0.5)


def map_to_screen(x_norm, y_norm):
    """Map a 0..1 fingertip position (within the active region) to screen pixels."""
    ax0, ax1 = ACTIVE_MARGIN_X, 1 - ACTIVE_MARGIN_X
    ay0, ay1 = ACTIVE_MARGIN_Y, 1 - ACTIVE_MARGIN_Y

    x_clamped = min(max(x_norm, ax0), ax1)
    y_clamped = min(max(y_norm, ay0), ay1)

    x_pct = (x_clamped - ax0) / (ax1 - ax0)
    y_pct = (y_clamped - ay0) / (ay1 - ay0)

    return x_pct * screen_w, y_pct * screen_h


def main():
    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_styles = mp.solutions.drawing_styles

    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

    if not cap.isOpened():
        print("Could not open webcam. Check CAM_INDEX or camera permissions.")
        return

    smooth_x, smooth_y = None, None
    was_pinching = False
    last_click_time = 0.0

    print(f"Screen resolution detected: {screen_w}x{screen_h}")
    print("Move your hand in front of the camera. Pinch to click. 'q'/ESC to quit.")

    with mp_hands.Hands(
        max_num_hands=MAX_HANDS,
        min_detection_confidence=DETECTION_CONF,
        min_tracking_confidence=TRACKING_CONF,
    ) as hands:

        while True:
            ok, frame = cap.read()
            if not ok:
                print("Failed to read frame from webcam.")
                break

            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb)

            pinching = False

            if results.multi_hand_landmarks:
                lm = results.multi_hand_landmarks[0].landmark
                mp_drawing.draw_landmarks(
                    frame, results.multi_hand_landmarks[0], mp_hands.HAND_CONNECTIONS,
                    mp_styles.get_default_hand_landmarks_style(),
                    mp_styles.get_default_hand_connections_style(),
                )

                index_tip = lm[8]
                thumb_tip = lm[4]

                x_norm = index_tip.x  # already mirrored by cv2.flip
                y_norm = index_tip.y

                if smooth_x is None:
                    smooth_x, smooth_y = x_norm, y_norm
                else:
                    smooth_x = smooth_x * SMOOTHING + x_norm * (1 - SMOOTHING)
                    smooth_y = smooth_y * SMOOTHING + y_norm * (1 - SMOOTHING)

                pinch_dist = ((index_tip.x - thumb_tip.x) ** 2 + (index_tip.y - thumb_tip.y) ** 2) ** 0.5
                hsize_norm = ((lm[0].x - lm[5].x) ** 2 + (lm[0].y - lm[5].y) ** 2) ** 0.5 or 0.001
                pinching = pinch_dist < PINCH_THRESHOLD_RATIO * hsize_norm

                sx, sy = map_to_screen(smooth_x, smooth_y)
                pyautogui.moveTo(sx, sy)

                now = time.time()
                if pinching and not was_pinching and (now - last_click_time) > CLICK_COOLDOWN_S:
                    pyautogui.click()
                    last_click_time = now

                cursor_color = (100, 255, 150) if pinching else (120, 230, 255)
                cx, cy = int(smooth_x * w), int(smooth_y * h)
                cv2.circle(frame, (cx, cy), 12, cursor_color, -1)
                if pinching:
                    cv2.putText(frame, "CLICK", (cx - 25, cy - 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 255, 150), 2, cv2.LINE_AA)
            else:
                smooth_x, smooth_y = None, None

            was_pinching = pinching

            # draw the active tracking region for reference
            ax0, ay0 = int(ACTIVE_MARGIN_X * w), int(ACTIVE_MARGIN_Y * h)
            ax1, ay1 = int((1 - ACTIVE_MARGIN_X) * w), int((1 - ACTIVE_MARGIN_Y) * h)
            cv2.rectangle(frame, (ax0, ay0), (ax1, ay1), (80, 80, 80), 1)

            cv2.putText(frame, "This window is just a preview — your real mouse is being moved.",
                        (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.putText(frame, "q/ESC: quit", (10, h - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

            cv2.imshow("Gesture Mouse Control (preview)", frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()