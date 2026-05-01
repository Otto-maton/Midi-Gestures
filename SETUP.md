# Midi Gestures - Setup Guide

## Requirements

- **Windows 10/11** (64-bit)
- **Python 3.10, 3.11, or 3.12** - [python.org/downloads](https://www.python.org/downloads/)
  - During install, check **"Add Python to PATH"**
- **A webcam** (built-in or USB)
- **A virtual MIDI port** - loopMIDI (free) is recommended: [tobias-erichsen.de/software/loopmidi.html](https://www.tobias-erichsen.de/software/loopmidi.html)
- **A DAW or MIDI-capable software** (Ableton, FL Studio, Reaper, etc.)

---

## Step 1 - Install loopMIDI

1. Download and install loopMIDI from the link above.
2. Open loopMIDI.
3. In the bottom-left text field, type a name for your port (e.g. `loopMIDI Port`) then click the **+** button.
4. The port will appear in the list - leave loopMIDI running in the system tray whenever you use Midi Gestures.

---

## Step 2 - Get the project files

If you received a zip file, extract it to a folder of your choice, for example:
```
C:\Users\YourName\Documents\Midi Gestures
```

If you are cloning from git:
```bash
git clone <repo-url> "Midi Gestures"
```

---

## Step 3 - Create a Python virtual environment

Open a terminal (Command Prompt or PowerShell) inside the project folder:

```powershell
cd "C:\Users\YourName\Documents\Midi Gestures"
python -m venv venv
```

Activate the environment:

```powershell
venv\Scripts\activate
```

You should see `(venv)` at the start of your prompt.

---

## Step 4 - Install dependencies

With the virtual environment active:

```powershell
pip install -r requirements.txt
```

This installs:
- `mediapipe` - hand tracking
- `opencv-python` - webcam capture
- `python-rtmidi` - MIDI output
- `python-osc` - OSC output (optional)
- `numpy` - signal processing

This may take a minute or two on first install.

---

## Step 5 - Configure your MIDI port

Open `config.json` in a text editor (Notepad works fine):

```json
{
  "midi_port_name": "loopMIDI Port"
}
```

Change the value to exactly match the port name you created in loopMIDI. The name is case-sensitive.

If you are using a different virtual MIDI driver (e.g. **loopbe1**, **IAC Driver** on Mac), use that port name instead.

---

## Step 6 - Run Midi Gestures

With the virtual environment still active, from the project folder:

```powershell
python run.py
```

A preview window will open showing your webcam feed with hand tracking overlaid. The terminal will show connection status and debug output.

To stop, press **Ctrl+C** in the terminal or close the preview window.

---

## Step 7 - Connect your DAW

In your DAW, add a MIDI input track or instrument and set its MIDI input to the loopMIDI port you created. Midi Gestures will now send MIDI CC and note data into your DAW in real time.

---

## Default MIDI Mappings

All CCs are sent on **Channel 1**. Drum tap notes are sent on **Channel 10**.

| Gesture | CC / Note |
|---|---|
| Right hand X position | CC 16 |
| Right hand Y position | CC 17 |
| Right hand pinch | CC 18 |
| Right hand roll | CC 19 |
| Right hand speed | CC 20 |
| Right hand depth | CC 21 |
| Left hand X position | CC 22 |
| Left hand Y position | CC 23 |
| Left hand pinch | CC 24 |
| Mode index | CC 25 |
| Shift state | CC 26 |
| Right XY (shift layer) X | CC 48 |
| Right XY (shift layer) Y | CC 49 |
| Right index finger tap | Note 36 (Ch 10) |
| Right middle finger tap | Note 38 (Ch 10) |
| Right ring finger tap | Note 42 (Ch 10) |

**Shift** is activated by holding the left hand open flat. While shift is held, the right hand XY sends on CCs 48/49 instead of 16/17, allowing a second set of controls without moving your hands away.

---

## Camera settings

If your webcam is not detected, or you have multiple cameras, you can change which camera is used by adding to `config.json`:

```json
{
  "midi_port_name": "loopMIDI Port",
  "camera_index": 0
}
```

Change `0` to `1`, `2`, etc. to select a different camera.

---

## Troubleshooting

**"No MIDI port found" / not connecting**
- Make sure loopMIDI is open and the port is listed as active.
- Double-check the port name in `config.json` matches exactly (including capitalisation and spaces).
- The app will retry the MIDI connection every 3 seconds automatically - you can open loopMIDI after starting the app.

**Preview window does not open / camera error**
- Check that no other application is using the webcam.
- Try changing `camera_index` in `config.json`.

**Laggy or stuttery tracking**
- Ensure you are running in good lighting facing the camera.
- Close other CPU-heavy applications.
- Lower `inference_fps` in `config.json` (e.g. `15`) to reduce CPU load.

**pip install fails on python-rtmidi**
- You may need the Microsoft C++ Build Tools. Download from: [visualstudio.microsoft.com/visual-cpp-build-tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and install the "Desktop development with C++" workload, then retry `pip install -r requirements.txt`.

---

## Running again after initial setup

Each time you want to use Midi Gestures:

1. Open loopMIDI (if it is not already running in the tray).
2. Open a terminal in the project folder.
3. Activate the virtual environment: `venv\Scripts\activate`
4. Run: `python run.py`
