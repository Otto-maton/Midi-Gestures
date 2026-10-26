# Midi Gestures

Turn your hands into a MIDI controller using a webcam.

Midi Gestures watches your hands through any standard webcam, runs them through MediaPipe hand tracking, and translates poses and motions into MIDI CC and note messages — sent to a DAW (Ableton, FL Studio, Reaper, Bitwig, etc.) over a virtual MIDI port. Two hands are tracked independently, with a left-hand modifier layer, four mode pages, and a panic key for stuck notes. OSC output is supported as an alternative to MIDI.

There is also an alternate mode (`run_mouse.py`) that drives the OS mouse cursor from hand gestures instead of MIDI.

---

## What you can do with it

- **XY pads** from palm position on each hand. Holding a left-hand fist activates a *shift layer* that remaps the right hand to a second pair of CCs — six independent XY axes total.
- **Pinch** (thumb + index distance) as a continuous CC, or **pitch-pinch** as a held MIDI note whose pitch follows hand height.
- **Tap** your index, middle, or ring finger downward in the air to fire drum notes (kick / snare / hi-hat by default).
- **Roll, depth, and speed** — hand rotation, distance from camera, and palm velocity each map to their own continuous CC.
- **Static shapes** (thumbs up, fist, open palm, victory, point, ILoveYou, thumbs down) fire gate notes while the shape is held.

---

## Requirements

- Windows 10 / 11 (64-bit)
- Python 3.10, 3.11, or 3.12
- A webcam (built-in or USB)
- A virtual MIDI port — [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) is recommended
- A DAW or any MIDI-capable software

Full installation walkthrough, including loopMIDI setup and troubleshooting, lives in [SETUP.md](SETUP.md).

---

## Quick start

From the project folder, in PowerShell or Command Prompt:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Open `config.json` and set `midi_port_name` to match the port you created in loopMIDI (the name is case-sensitive). Then:

```powershell
python run.py
```

A preview window will open showing your webcam feed with hand-tracking overlays. Connect your DAW's MIDI input to the same loopMIDI port and you should see CC and note data arriving in real time.

If `pip install` fails on `python-rtmidi`, you most likely need the Microsoft C++ Build Tools — see [SETUP.md](SETUP.md) for the fix.

---

## Run modes

| Command | What it does |
|---|---|
| `python run.py` | Main app. Hand tracking → MIDI / OSC output. |
| `python run_mouse.py` | Alternate mode. Hand gestures drive the OS mouse cursor. |
| `python run_xr.py` | XR mode. Meta Quest 3 hand tracking → MIDI / OSC, with mixed-reality feedback in the headset. |

### XR mode (Meta Quest 3)

`run_xr.py` serves a WebXR app to the Quest 3's browser over your Wi-Fi. The headset's own hand tracking replaces the webcam: you play inside two floating control zones and see every CC and note live in passthrough, while the PC side reuses the same mapping engine, `config.json` and MIDI/OSC output. It needs only `pip install -r requirements-xr.txt` (no MediaPipe or OpenCV). Setup, controls and tuning are in [XR.md](XR.md).

---

## Keyboard controls (preview window)

| Key | Action |
|---|---|
| `Space` | Toggle the camera display on / off |
| `P` | Panic — sends All Notes Off on every MIDI channel |
| `S` | Open the live settings panel |
| `Q` or `Esc` | Quit |

---

## Default MIDI map at a glance

All CCs are sent on **Channel 1** unless noted. Drum tap notes are sent on **Channel 10**.

| Gesture | CC / Note |
|---|---|
| Right hand X / Y | CC 16 / CC 17 |
| Right hand pinch | CC 18 |
| Right hand roll / speed / depth | CC 19 / CC 20 / CC 21 |
| Left hand X / Y | CC 22 / CC 23 |
| Left hand pinch | CC 24 |
| Mode index / Shift state | CC 25 / CC 26 |
| Right XY (shift layer) | CC 48 / CC 49 |
| Right finger taps (index / middle / ring) | Notes 36 / 38 / 42 (Ch 10) |
| Pitch-pinch held note | Notes 48–84, dynamic (Ch 10) |
| Static gestures (right / left hand) | Notes 60–66 / 67–73 |

The full mapping table, every threshold, and per-gesture notes are in [GESTURES.md](GESTURES.md).

---

## Configuration

All tuning lives in `config.json` — camera index, MIDI port name, OSC settings, and per-gesture parameters (EMA smoothing, on/off thresholds, dead zones, slew limits, calibration center and range). The defaults are sensible; tweak from there.

Common command-line overrides:

```powershell
python run.py --camera 1                    # use a different webcam
python run.py --midi-port "loopMIDI Port"   # override the MIDI port
python run.py --no-preview                  # run headless
python run.py --osc --osc-host 127.0.0.1    # send OSC instead of (or alongside) MIDI
python run.py --record                      # log the message bus to CSV
python run.py --verbose                     # debug logging
python run.py --config custom.json          # use a different config file
```

---

## Project structure

```
.
├── run.py                      # Main entry point (MIDI / OSC)
├── run_mouse.py                # Alternate entry: mouse-control mode
├── run_xr.py                   # Alternate entry: Meta Quest 3 XR mode
├── config.json                 # All user-tunable settings
├── requirements.txt
├── requirements-xr.txt         # Dependencies for XR mode only
├── midi_gestures.spec          # PyInstaller build spec
├── gesture_recognizer.task     # MediaPipe gesture model
├── hand_landmarker.task        # MediaPipe hand-landmark model
│
├── midi_gestures/              # Core framework
│   ├── main.py                 # Thread orchestration, lifecycle
│   ├── bus.py                  # AsyncBus — OSC-style message spine
│   ├── vision_producer.py      # Camera capture thread
│   ├── inference_logic.py      # MediaPipe + plugin dispatch
│   ├── output_consumer.py      # Bus → MIDI/OSC translator
│   ├── scheduler.py            # High-resolution note-off timing
│   ├── safety.py               # Hand-loss decay, panic
│   ├── adapters/               # MidiAdapter, OscAdapter
│   ├── mapping/                # MappingEngine + default tables
│   ├── plugins/                # Pinch, XY, roll, depth, speed, tap, gesture, …
│   ├── ui/                     # Live settings panel
│   └── telemetry/              # Bus recorder, overlay, perf stats
│
├── mouse_gestures/             # Alternate mouse-control mode
│
├── xr_gestures/                # XR mode: PC bridge (server, certs, settings)
│   └── web/                    # WebXR app for the Quest (gesture engine, HUD, zones)
│
└── tests/                      # XR gesture engine (Node) and bridge (unittest) tests
```

---

## Architecture in one paragraph

The pipeline is multi-threaded: a `VisionProducer` captures camera frames into a 1-slot LIFO queue (always serving the freshest frame), `InferenceLogic` runs MediaPipe and dispatches the result to a set of independent gesture plugins (pinch, XY, roll, depth, speed, tap, static gestures, mode manager, etc.). Each plugin smooths and thresholds its own feature and publishes to an OSC-style `AsyncBus` with priority queues. An `OutputConsumer` plus `MappingEngine` translates bus messages into MIDI CC / note or OSC messages, sent through `MidiAdapter` / `OscAdapter`. A separate `OutputScheduler` handles precise note-off timing, and a `SafetyMonitor` decays outputs gracefully when a hand disappears and panics stuck notes on shutdown. Adding a new gesture is a new plugin file — the rest of the system doesn't need to change.

---

## Documentation

- [SETUP.md](SETUP.md): full installation walkthrough and troubleshooting
- [GESTURES.md](GESTURES.md): every gesture, threshold, and CC / note mapping
- [XR.md](XR.md): Meta Quest 3 XR mode setup, controls and tuning
- [Midi_Gestures_Hybrid_Architecture_Design_v2.txt](Midi_Gestures_Hybrid_Architecture_Design_v2.txt): internal architecture design notes
