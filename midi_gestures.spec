# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

mediapipe_datas, mediapipe_binaries, mediapipe_hiddenimports = collect_all('mediapipe')
cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all('cv2')

datas = [
    ('gesture_recognizer.task', '.'),
    ('hand_landmarker.task', '.'),
    ('config.json', '.'),
]
datas += mediapipe_datas
datas += cv2_datas
datas += collect_data_files('rtmidi')

binaries = []
binaries += mediapipe_binaries
binaries += cv2_binaries
binaries += collect_dynamic_libs('rtmidi')

hiddenimports = [
    'midi_gestures',
    'midi_gestures.bus',
    'midi_gestures.models',
    'midi_gestures.config',
    'midi_gestures.inference_logic',
    'midi_gestures.vision_producer',
    'midi_gestures.output_consumer',
    'midi_gestures.scheduler',
    'midi_gestures.safety',
    'midi_gestures.mapping.engine',
    'midi_gestures.mapping.default_maps',
    'midi_gestures.adapters.base_adapter',
    'midi_gestures.adapters.midi_adapter',
    'midi_gestures.adapters.osc_adapter',
    'midi_gestures.plugins.base',
    'midi_gestures.plugins.utils',
    'midi_gestures.plugins.pinch',
    'midi_gestures.plugins.pitch_pinch',
    'midi_gestures.plugins.shift',
    'midi_gestures.plugins.xy',
    'midi_gestures.plugins.roll',
    'midi_gestures.plugins.depth',
    'midi_gestures.plugins.speed',
    'midi_gestures.plugins.tap',
    'midi_gestures.plugins.gesture',
    'midi_gestures.plugins.mode_manager',
    'midi_gestures.telemetry.overlay',
    'midi_gestures.telemetry.recorder',
    'midi_gestures.telemetry.stats',
    'midi_gestures.ui.settings_panel',
    'rtmidi',
    'pythonosc',
    'pythonosc.udp_client',
    'tkinter',
    'tkinter.ttk',
    'numpy',
]
hiddenimports += mediapipe_hiddenimports
hiddenimports += cv2_hiddenimports

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'pandas', 'PyQt5', 'PyQt6', 'wx'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MidiGestures',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MidiGestures',
)
