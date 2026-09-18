"""
Gesture Control Demo v2 (Python / OpenCV / MediaPipe)
------------------------------------------------------
10 buttons in a horizontally scrollable strip.
- Move your OPEN hand left/right (index fingertip) to scroll the strip ("wave" to scroll).
- PINCH (thumb tip + index tip together) while over a button to select/click it.
Press 'q' or ESC to quit, 'r' to reset counts.

Install dependencies first (in PyCharm's terminal or a venv):
    pip install opencv-python mediapipe

Run:
    python gesture_control_demo.py
"""

import time
import cv2
import mediapipe as mp

# ---------- Config ----------
CAM_INDEX = 0
FRAME_W, FRAME_H = 960, 720
NUM_BUTTONS = 10
BTN_W, BTN_H = 130, 150
BTN_GAP = 20
STRIP_MARGIN_BOTTOM = 40
MAX_HANDS = 1
DETECTION_CONF = 0.6
TRACKING_CONF = 0.6

PINCH_THRESHOLD_RATIO = 0.45   # pinch if thumb-index distance < this * hand size
SCROLL_SENSITIVITY = 1.6       # multiplier on finger pixel movement -> scroll pixels
SMOOTHING = 0.35               # 0 = no smoothing, closer to 1 = more smoothing


def build_buttons():
    buttons = []
    for i in range(NUM_BUTTONS):
        x = i * (BTN_W + BTN_GAP)
        buttons.append({"x": x, "label": str(i + 1), "count": 0})
    return buttons


def total_strip_width():
    return NUM_BUTTONS * BTN_W + (NUM_BUTTONS - 1) * BTN_GAP


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def draw_ui(frame, buttons, scroll_x, hover_index, pinching):
    h, w = frame.shape[:2]
    y2 = h - STRIP_MARGIN_BOTTOM
    y1 = y2 - BTN_H

    overlay = frame.copy()
    for i, btn in enumerate(buttons):
        bx1 = int(btn["x"] - scroll_x)
        bx2 = bx1 + BTN_W
        if bx2 < 0 or bx1 > w:
            continue  # off-screen, skip drawing for performance
        is_hover = (i == hover_index)
        color = (255, 200, 90) if (is_hover and pinching) else (255, 220, 120) if is_hover else (55, 55, 55)
        cv2.rectangle(overlay, (bx1, y1), (bx2, y2), color, -1)

    frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)

    for i, btn in enumerate(buttons):
        bx1 = int(btn["x"] - scroll_x)
        bx2 = bx1 + BTN_W
        if bx2 < 0 or bx1 > w:
            continue
        is_hover = (i == hover_index)
        border = (255, 220, 120) if is_hover else (255, 255, 255)
        cv2.rectangle(frame, (bx1, y1), (bx2, y2), border, 2)
        cv2.putText(frame, btn["label"], (bx1 + 15, y1 + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, str(btn["count"]), (bx1 + 15, y1 + 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.3, (120, 230, 255), 3, cv2.LINE_AA)

    # scrollbar indicator
    max_scroll = max(1, total_strip_width() - w)
    bar_w = w - 40
    bar_x = 20
    bar_y = y1 - 20
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 6), (70, 70, 70), -1)
    thumb_w = max(20, int(bar_w * (w / total_strip_width())))
    thumb_x = bar_x + int((bar_w - thumb_w) * (scroll_x / max_scroll))
    cv2.rectangle(frame, (thumb_x, bar_y), (thumb_x + thumb_w, bar_y + 6), (120, 230, 255), -1)

    return frame


def hand_size(landmarks, w, h):
    # distance between wrist (0) and index finger MCP (5) as a rough hand-scale reference
    wrist = landmarks[0]
    mcp = landmarks[5]
    dx = (wrist.x - mcp.x) * w
    dy = (wrist.y - mcp.y) * h
    return max(1.0, (dx ** 2 + dy ** 2) ** 0.5)


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

    buttons = build_buttons()
    scroll_x = 0.0
    smooth_px = None
    prev_px = None
    was_pinching = False

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
            max_scroll = max(0, total_strip_width() - w)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb)

            hover_index = -1
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
                px, py = index_tip.x * w, index_tip.y * h
                tx, ty = thumb_tip.x * w, thumb_tip.y * h

                pinch_dist = ((px - tx) ** 2 + (py - ty) ** 2) ** 0.5
                hsize = hand_size(lm, w, h)
                pinching = pinch_dist < PINCH_THRESHOLD_RATIO * hsize

                # smooth the fingertip position to reduce jitter
                if smooth_px is None:
                    smooth_px = px
                else:
                    smooth_px = smooth_px * SMOOTHING + px * (1 - SMOOTHING)

                if pinching:
                    # freeze scrolling while pinching; reset drag baseline
                    prev_px = None
                    cursor_x = int(smooth_px)
                    strip_x = cursor_x + scroll_x
                    idx = int(strip_x // (BTN_W + BTN_GAP))
                    if 0 <= idx < NUM_BUTTONS:
                        local_x = strip_x - buttons[idx]["x"]
                        if 0 <= local_x <= BTN_W:
                            hover_index = idx
                    if hover_index != -1 and not was_pinching:
                        buttons[hover_index]["count"] += 1  # fire on pinch-down edge only
                else:
                    if prev_px is not None:
                        delta = (smooth_px - prev_px) * SCROLL_SENSITIVITY
                        scroll_x = clamp(scroll_x - delta, 0, max_scroll)
                    prev_px = smooth_px

                    cursor_x = int(smooth_px)
                    strip_x = cursor_x + scroll_x
                    idx = int(strip_x // (BTN_W + BTN_GAP))
                    if 0 <= idx < NUM_BUTTONS:
                        local_x = strip_x - buttons[idx]["x"]
                        if 0 <= local_x <= BTN_W:
                            hover_index = idx

                cursor_y = int(index_tip.y * h)
                color = (120, 230, 255) if not pinching else (100, 255, 150)
                cv2.circle(frame, (int(smooth_px), cursor_y), 14, color, -1)
                cv2.circle(frame, (int(smooth_px), cursor_y), 16, (255, 255, 255), 2)
                if pinching:
                    cv2.putText(frame, "PINCH", (int(smooth_px) - 30, cursor_y - 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 255, 150), 2, cv2.LINE_AA)
            else:
                prev_px = None
                smooth_px = None

            was_pinching = pinching

            frame = draw_ui(frame, buttons, scroll_x, hover_index, pinching)

            cv2.putText(frame, "Open hand: swipe to scroll   Pinch: select   q/ESC: quit   r: reset",
                        (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

            cv2.imshow("Gesture Control Demo", frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('r'):
                for btn in buttons:
                    btn["count"] = 0

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()