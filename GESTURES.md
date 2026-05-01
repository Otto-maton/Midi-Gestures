# Midi Gestures — Gesture Manual

All gestures are detected from a webcam feed and translated to MIDI or OSC output in real time. Both hands are tracked independently. The **left hand** acts as a modifier/control hand; the **right hand** is the primary performance hand.

---

## Modifier Gestures

### Shift (Left Hand)
**How to perform:** Close your left hand into a fist.  
**What it does:** Activates the *shift layer*. While shift is active, the right hand's XY position maps to a different set of CC numbers (CC 48/49 instead of CC 16/17), allowing a second set of parameters to be controlled without changing hand position.  
**Output:** CC 26 snaps to 127 when active, 0 when released.  
**Threshold:** Fingers must curl to roughly 70% fist closure to activate; releases at 45%.

---

## Continuous Control Gestures

### XY Position (Both Hands)
**How to perform:** Hold your hand open in front of the camera and move it left/right and up/down.  
**What it does:** Tracks the palm center in 2D space and outputs two independent continuous CC values — one for horizontal position, one for vertical.  
**Output:**
- Right hand (no shift): CC 16 (X), CC 17 (Y)
- Left hand: CC 22 (X), CC 23 (Y)
- Right hand (shift active): CC 48 (X), CC 49 (Y)

**Notes:** A dead zone near the edges and slew limiting prevent jitter. Supports an optional relative mode where movement accumulates from where the hand first appears.

---

### Pinch (Both Hands)
**How to perform:** Bring your thumb and index finger together.  
**What it does:** Measures the distance between thumb tip and index finger tip and outputs a continuous CC value (0 = open, 127 = fully pinched).  
**Output:**
- Right hand: CC 18
- Left hand: CC 24

**Notes:** Uses hysteresis (activates at 60% closure, deactivates at 40%) and median filtering to reduce noise.

---

### Pitch Pinch (Both Hands)
**How to perform:** Bring your thumb and index finger together while varying the height of your hand.  
**What it does:** Detects a pinch and simultaneously calculates a MIDI note from the hand's vertical position. While the pinch is held, a note plays. Moving the hand up or down changes the pitch in real time.
- **One hand visible:** Pitch is derived from the absolute Y height of the pinching hand's wrist (higher = higher note).
- **Both hands visible:** Pitch is derived from the relative vertical distance between the two wrists, making pitch control more sensitive and independent of overall hand height.

**Output:** Dynamic MIDI note on Channel 10, note range C3–C6 (MIDI 48–84) by default. Note-off is sent automatically when the pinch releases.

**Notes:** The pitch is smoothed to prevent stepping. Note range, sensitivity, and smoothing are all configurable.

---

### Roll (Both Hands)
**How to perform:** Rotate your hand clockwise or counter-clockwise (like turning a dial).  
**What it does:** Measures the angle of the knuckle line (from index MCP to pinky MCP) and outputs it as a continuous CC.  
**Output:**
- Right hand: CC 19
- Left hand: CC 105

---

### Depth (Both Hands)
**How to perform:** Push your hand toward or pull it away from the camera.  
**What it does:** Tracks the Z (depth) coordinate of the wrist landmark and outputs a continuous CC. Closer to camera = higher value.  
**Output:**
- Right hand: CC 21
- Left hand: CC 107

---

### Speed (Both Hands)
**How to perform:** Move your hand faster or slower.  
**What it does:** Calculates the frame-to-frame movement speed of the palm center and outputs it as a continuous CC. Faster motion = higher value; the value decays back toward zero when the hand is still.  
**Output:**
- Right hand: CC 20
- Left hand: CC 106

---

## Tap Gestures (Right Hand)

**How to perform:** Flick a finger downward with a snapping motion (like tapping a table). Tapping while pinching is ignored.  
**What it does:** Detects the downward velocity of individual finger tips and fires a short drum note on each detected tap.

| Finger | MIDI Note | Default drum sound |
|---|---|---|
| Index | 36 | Kick drum |
| Middle | 38 | Snare |
| Ring | 42 | Closed hi-hat |

**Notes:** Each finger has an independent cooldown (default 250 ms) to prevent double-triggers.

---

## Static Gesture Recognition (Both Hands)

**How to perform:** Hold one of the recognized hand shapes clearly in view. The gesture must be held for at least 2 frames to confirm.  
**What it does:** Classifies the hand shape using the MediaPipe gesture recognizer and fires a gate note while the gesture is held. The note turns off when the hand returns to a neutral or different pose.

| Gesture | Right Hand Note | Left Hand Note |
|---|---|---|
| Thumb Up | 60 | 67 |
| Thumb Down | 61 | 68 |
| Open Palm | 62 | 69 |
| Closed Fist | 63 | 70 |
| Victory (✌️) | 64 | 71 |
| Pointing Up | 65 | 72 |
| ILoveYou (🤟) | 66 | 73 |

All gesture notes are sent on MIDI Channel 1, velocity 100.

---

## System Events

### Mode Switching
The system supports up to 4 modes (0–3). Modes can be used in mappings to activate different parameter sets.  
**Bus path:** `/event/mode/next` advances to the next mode; `/event/mode/set` jumps to a specific mode.  
**Output:** CC 25 on Channel 1, scaled across 0–127.

### Panic
**Bus path:** `/event/panic`  
**What it does:** Sends a MIDI All Notes Off / All Sound Off message on all channels. Use this if notes get stuck.

### Stop
**Bus path:** `/event/stop`  
**What it does:** Fires MIDI note 41 on Channel 10 (short pulse, 80 ms).

---

## Default CC/Note Assignment Summary

| Signal | Condition | CC / Note | Channel |
|---|---|---|---|
| Right XY X | no shift | CC 16 | 1 |
| Right XY Y | no shift | CC 17 | 1 |
| Right Pinch | — | CC 18 | 1 |
| Right Roll | — | CC 19 | 1 |
| Right Speed | — | CC 20 | 1 |
| Right Depth | — | CC 21 | 1 |
| Left XY X | — | CC 22 | 1 |
| Left XY Y | — | CC 23 | 1 |
| Left Pinch | — | CC 24 | 1 |
| Mode Index | — | CC 25 | 1 |
| Shift State | — | CC 26 | 1 |
| Right XY X | shift | CC 48 | 1 |
| Right XY Y | shift | CC 49 | 1 |
| Right/Left Pitch Pinch | — | Note 48–84 (dynamic) | 10 |
| Right tap index | — | Note 36 | 10 |
| Right tap middle | — | Note 38 | 10 |
| Right tap ring | — | Note 42 | 10 |
| Right gestures | — | Notes 60–66 | 1 |
| Left gestures | — | Notes 67–73 | 1 |
