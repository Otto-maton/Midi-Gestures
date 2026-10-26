# Midi Gestures XR (Meta Quest 3)

Play Midi Gestures with the Quest 3's built-in hand tracking instead of a webcam. You see your hands, two floating control zones and a live readout of every CC and note in mixed reality (passthrough), and the MIDI lands in your DAW exactly as it does with the webcam version.

```
Quest 3 (Meta Quest Browser, WebXR)            PC
  hand tracking, 25 joints per hand
  -> gesture engine (xr_gestures/web/js)   --Wi-Fi-->   run_xr.py bridge
  -> in-headset zones, HUD, buttons        WebSocket    -> MappingEngine (same rules, config.json)
                                                        -> loopMIDI / OSC -> DAW
```

The headset does the gesture detection; the PC keeps the existing mapping engine, MIDI/OSC adapters, note-off scheduler and safety logic. No app store install and no Unity: it is a web page served by the bridge.

---

## What you need

- Meta Quest 3 (Quest 3S, Quest Pro and Quest 2 should also work; only the Quest 3 flow is described here) with **hand tracking turned on** in the Quest settings (under Movement tracking).
- A Windows PC on the **same Wi-Fi/LAN** as the headset, with loopMIDI (or another virtual MIDI port) and your DAW, set up as in [SETUP.md](SETUP.md).
- Python 3.10 or newer. The XR bridge does not need MediaPipe or OpenCV.
- Internet access on the Quest the first time the page loads (three.js comes from a CDN).

## Install

From the project folder:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements-xr.txt
```

## Run

```powershell
python run_xr.py
```

The bridge prints the address to open, for example:

```
  On the Quest 3, open this in the Meta Quest Browser:
      https://192.168.1.55:8443
```

1. On the Quest, open the **Meta Quest Browser** and type that address.
2. The browser warns that the connection is not private. This is expected: WebXR only runs on HTTPS pages, so the bridge made its own certificate (saved in `certs/`). Choose **Advanced > Proceed**. You only do this once per certificate.
3. Check the page shows **PC bridge: connected** and your MIDI port, then press **Enter mixed reality**.
4. Put the controllers down. Two boxes appear in front of you at chest height, pink for the left hand and blue for the right.

The first time you run the bridge, Windows Firewall may ask about Python: allow it on **private** networks, or the Quest cannot connect.

The usual options from `run.py` work here too: `--midi-port`, `--osc`, `--osc-host`, `--osc-port`, `--record`, `--config`, `--verbose`. Also `--port` (default 8443) and `--host` (default: all interfaces).

## Playing

A hand only plays while its palm is **inside its box**. Take a hand out and it releases (notes off, pinch to 0), and XY/roll/depth hold their last value, like lifting a finger off an XY pad. This also lets you rest your hands or reach for the buttons without sending anything.

| Gesture | In XR | Default output |
|---|---|---|
| XY | Palm position inside the box | Right CC 16/17, left CC 22/23 |
| Depth | Push forward (away from you) for higher values | Right CC 21 |
| Roll | Tilt the knuckle line like turning a dial, level = 64, +/-90 degrees = 0..127 | Right CC 19 |
| Speed | Palm speed, 1 m/s = 127 | Right CC 20 |
| Pinch | Thumb to index; continuous CC, gate on at 2.5 cm, off at 4 cm | Right CC 18, left CC 24 |
| Shift | Left fist inside the left box | CC 26, right XY moves to CC 48/49 |
| Taps | Flick the right index, middle or ring finger toward your palm | Notes 36/38/42, ch 10 |
| Pitch pinch | Pinch and move up/down (or relative to the other hand) | Notes 48-84, ch 10 |
| Hand shapes | Thumb up/down, open palm, fist, victory, pointing up, I love you | Notes 60-66 right, 67-73 left |

Which of these actually send is still decided by `config.json` (`rule_enabled`), exactly like the webcam app. The HUD shows every signal with its CC number and greys out the ones that are switched off.

**Button strip** (to the left of the left box, poke with a fingertip): **Panic** (all notes off), **Mode** (cycles mode 1-4, CC 25), **Recenter** (moves the boxes to where you are looking), **Mute** (gestures stop sending, everything is released), **Hide HUD**.

Taking the headset off, opening the Quest menu, closing the page or losing Wi-Fi all release held notes and shift; the bridge also sends All Notes Off when the headset disconnects.

### How this differs from the webcam version

- Tracking is true 3D, so depth is real distance and taps are measured as finger flexion relative to the knuckle: moving or flicking your whole hand does not fire taps.
- Hand shapes are classified from the joint angles (same seven labels as the MediaPipe recognizer).
- The pinch gate uses the actual fingertip distance, so notes trigger as your fingers meet instead of after the smoothed CC ramps up.
- Smoothing values from `config.json` (alpha, slew limit, dead zone) are converted from the webcam's 30 Hz to the headset's 72-120 Hz, so the feel stays the same.

## Tuning

The existing sections of `config.json` (`pinch`, `shift`, `xy`, `roll`, `depth`, `speed`, `tap`, `gesture`, `pitch_pinch`, `mode_manager`, `rule_enabled`) still apply. XR-only settings go in an optional `"xr"` block; anything you leave out keeps its default:

```json
"xr": {
  "zone_distance_m": 0.40,
  "zone_drop_m": 0.30,
  "zone_offset_x_m": 0.20,
  "zone_half_size_m": [0.15, 0.15, 0.15],
  "zone_gating": true,
  "pinch_closed_m": 0.015,
  "pinch_open_m": 0.10,
  "pinch_on_m": 0.025,
  "pinch_off_m": 0.040,
  "pinch_suppress_m": 0.035,
  "roll_range_deg": 90,
  "speed_cap_mps": 1.0,
  "tap_velocity_mps": 0.35,
  "tap_sides": ["right"],
  "pitch_span_m": 0.6,
  "passthrough": true
}
```

| Key | Meaning |
|---|---|
| `zone_distance_m`, `zone_drop_m` | Where the boxes sit: this far in front of your eyes and this far below eye level |
| `zone_offset_x_m`, `zone_half_size_m` | Each box's distance from centre and its half width/height/depth |
| `zone_gating` | `false` makes a tracked hand play anywhere, like the webcam version |
| `pinch_closed_m`, `pinch_open_m` | Thumb-index distances that read as pinch 127 and 0 |
| `pinch_on_m`, `pinch_off_m` | Pinch gate hysteresis (pinch events, pitch-pinch notes) |
| `pinch_suppress_m` | No taps while thumb and index are closer than this |
| `roll_range_deg`, `speed_cap_mps` | Roll angle and palm speed that read as full scale |
| `tap_velocity_mps` | How fast a finger must flex to count as a tap; raise it if taps misfire |
| `pitch_span_m` | Two-hand pitch pinch: wrist height difference covering the whole note range |
| `passthrough` | `false` starts in full VR instead of mixed reality |

Restart the bridge and reload the page after editing.

## Troubleshooting

- **Page will not load on the Quest:** both devices must be on the same network; try the other addresses the bridge printed (a PC with WSL or Hyper-V lists several); check the firewall prompt above.
- **"WebXR not available":** you opened an `http://` address. Use the `https://` one.
- **PC bridge: not connected:** the bridge stopped, or the page was opened from a different port.
- **MIDI: port not found:** the bridge could not open `midi_port_name`; it retries every few seconds once you create the port in loopMIDI.
- **No hands:** put the controllers down, and check hand tracking is on in the Quest settings.
- **Boxes in the wrong place:** poke **Recenter** while looking straight ahead.

### Over USB instead of Wi-Fi

With developer mode and `adb` you can skip the certificate:

```powershell
python run_xr.py --http
adb reverse tcp:8080 tcp:8080
```

Then open `http://localhost:8080` on the Quest.

## Developing without a headset

Open `https://localhost:8443/?emulate` on the PC (or `http://localhost:8080/?emulate` with `--http`). This loads Meta's Immersive Web Emulation Runtime as an emulated Quest 3 with hands, plus its DevUI overlay for moving the head and hands and setting pinch. `?emulate=bare` skips the DevUI so a script can drive `window.xrDevice` directly; `window.midiGestures` exposes the gesture engine and link for inspection.

Tests:

```powershell
node --test tests/xr_gestures.test.mjs
python -m unittest discover -s tests -t .
```

## Notes

- The bridge listens on your local network. Anyone on that network who can reach the port can send MIDI to your DAW; use `--host` to bind a single interface if that matters.
- Files: `run_xr.py` (entry point), `xr_gestures/` (bridge: `main.py`, `server.py`, `certs.py`, `settings.py`) and `xr_gestures/web/` (the WebXR app: `js/gestures.js` is the gesture engine, `js/app.js` the scene and session).
