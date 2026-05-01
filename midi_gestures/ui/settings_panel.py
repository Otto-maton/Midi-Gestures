from __future__ import annotations
import threading
import logging
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from midi_gestures.plugins.base import Plugin
    from midi_gestures.mapping.engine import MappingEngine

logger = logging.getLogger(__name__)

_PLUGIN_LABELS = {
    "PinchPlugin":   "Pinch",
    "RollPlugin":    "Roll",
    "XYPlugin":      "XY",
    "DepthPlugin":   "Depth",
    "SpeedPlugin":   "Speed",
    "ShiftPlugin":   "Shift (Fist)",
    "TapPlugin":     "Tap",
}

_PATH_LABELS = {
    "/hand/right/xy [0]":    "R XY - X axis",
    "/hand/right/xy [1]":    "R XY - Y axis",
    "/hand/right/pinch":     "R Pinch",
    "/hand/right/pinch_held":"R Pinch Hold (gate)",
    "/hand/right/pinch_pitch":"R Pitch Pinch (positioned note)",
    "/hand/right/roll":      "R Roll",
    "/hand/right/speed":     "R Speed",
    "/hand/right/depth":     "R Depth",
    "/hand/left/xy [0]":     "L XY - X axis",
    "/hand/left/xy [1]":     "L XY - Y axis",
    "/hand/left/pinch":      "L Pinch",
    "/hand/left/pinch_held": "L Pinch Hold (gate)",
    "/hand/left/pinch_pitch":"L Pitch Pinch (positioned note)",
    "/shift":                "Shift state",
    "/mode/index":           "Mode index",
    "/hand/right/gesture/thumb_up":    "R Gesture - Thumb Up",
    "/hand/right/gesture/thumb_down":  "R Gesture - Thumb Down",
    "/hand/right/gesture/open_palm":   "R Gesture - Open Palm",
    "/hand/right/gesture/closed_fist": "R Gesture - Closed Fist",
    "/hand/right/gesture/victory":     "R Gesture - Victory",
    "/hand/right/gesture/pointing_up": "R Gesture - Pointing Up",
    "/hand/right/gesture/iloveyou":    "R Gesture - ILoveYou",
    "/hand/left/gesture/thumb_up":     "L Gesture - Thumb Up",
    "/hand/left/gesture/thumb_down":   "L Gesture - Thumb Down",
    "/hand/left/gesture/open_palm":    "L Gesture - Open Palm",
    "/hand/left/gesture/closed_fist":  "L Gesture - Closed Fist",
    "/hand/left/gesture/victory":      "L Gesture - Victory",
    "/hand/left/gesture/pointing_up":  "L Gesture - Pointing Up",
    "/hand/left/gesture/iloveyou":     "L Gesture - ILoveYou",
    "/event/hand/right/tap_index":     "R Tap - Index",
    "/event/hand/right/tap_middle":    "R Tap - Middle",
    "/event/hand/right/tap_ring":      "R Tap - Ring",
    "/event/stop":                     "Event - Stop",
}


class SettingsPanel:
    def __init__(self, plugins: List["Plugin"], mapping_engine: "MappingEngine",
                 cfg: dict | None = None, config_path: str | None = None):
        self._plugins = plugins
        self._mapping_engine = mapping_engine
        self._cfg = cfg if cfg is not None else {}
        self._config_path = config_path if config_path is not None else "config.json"
        self._inference = None
        self._vision = None
        self._output_consumer = None
        self._active_paths: dict = {}
        self._thread: threading.Thread | None = None
        self._root = None
        self._lock = threading.Lock()

    def set_inference(self, inference):
        self._inference = inference

    def set_vision(self, vision):
        self._vision = vision

    def set_output_consumer(self, oc):
        import time as _t
        self._output_consumer = oc
        def _cb(path, val):
            self._active_paths[path] = (val, _t.monotonic())
        oc.set_active_path_callback(_cb)

    def start(self):
        self._thread = threading.Thread(target=self._run_tk, name="SettingsPanel", daemon=True)
        self._thread.start()

    def stop(self):
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def show(self):
        if self._root:
            try:
                self._root.after(0, self._root.deiconify)
                self._root.after(0, self._root.lift)
            except Exception:
                pass

    def hide(self):
        if self._root:
            try:
                self._root.after(0, self._root.withdraw)
            except Exception:
                pass

    def toggle(self):
        if self._root:
            try:
                self._root.after(0, self._toggle_visibility)
            except Exception:
                pass

    def _toggle_visibility(self):
        if self._root.state() == "withdrawn":
            self._root.deiconify()
            self._root.lift()
        else:
            self._root.withdraw()

    def _run_tk(self):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            logger.warning("Tkinter not available - settings panel disabled")
            return

        self._root = tk.Tk()
        self._root.title("Midi Gestures - Settings")
        self._root.resizable(True, True)
        self._root.protocol("WM_DELETE_WINDOW", self._root.withdraw)

        notebook = ttk.Notebook(self._root)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        system_frame = ttk.Frame(notebook)
        notebook.add(system_frame, text="System")
        self._build_system_tab(system_frame, tk, ttk)

        sensitivity_frame = ttk.Frame(notebook)
        notebook.add(sensitivity_frame, text="Sensitivity")
        self._build_sensitivity_tab(sensitivity_frame, tk, ttk)

        cc_frame = ttk.Frame(notebook)
        notebook.add(cc_frame, text="CC Mapping")
        self._build_cc_tab(cc_frame, tk, ttk)

        note_frame = ttk.Frame(notebook)
        notebook.add(note_frame, text="Note Mapping")
        self._build_note_tab(note_frame, tk, ttk)

        toggles_frame = ttk.Frame(notebook)
        notebook.add(toggles_frame, text="Toggles")
        self._build_toggles_tab(toggles_frame, tk, ttk)

        mapping_frame = ttk.Frame(notebook)
        notebook.add(mapping_frame, text="Mapping Mode")
        self._build_mapping_tab(mapping_frame, tk, ttk)

        self._root.update_idletasks()
        self._root.withdraw()
        self._root.mainloop()

    def _build_system_tab(self, parent, tk, ttk):


        lf_camera = ttk.LabelFrame(parent, text="Camera", padding=(8, 4))
        lf_camera.pack(fill="x", padx=8, pady=(8, 4))

        def _int_row(frame, row, label, key, default, from_, to):
            ttk.Label(frame, text=label, width=30, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(4, 4), pady=2)
            var = tk.IntVar(value=self._cfg.get(key, default))
            spin = ttk.Spinbox(frame, from_=from_, to=to, width=8, textvariable=var)
            spin.grid(row=row, column=1, sticky="w", padx=(0, 4), pady=2)
            frame.columnconfigure(0, weight=1)
            return var, key

        def _float_row(frame, row, label, key, default, from_, to, increment=0.05):
            ttk.Label(frame, text=label, width=30, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(4, 4), pady=2)
            var = tk.DoubleVar(value=self._cfg.get(key, default))
            spin = ttk.Spinbox(frame, from_=from_, to=to, increment=increment,
                               width=8, textvariable=var, format="%.2f")
            spin.grid(row=row, column=1, sticky="w", padx=(0, 4), pady=2)
            frame.columnconfigure(0, weight=1)
            return var, key

        cam_vars = []
        v, k = _int_row(lf_camera, 0, "Capture Width", "capture_width", 640, 160, 1920)
        cam_vars.append((v, k))
        v, k = _int_row(lf_camera, 1, "Capture Height", "capture_height", 480, 120, 1080)
        cam_vars.append((v, k))

        lf_inference = ttk.LabelFrame(parent, text="Inference", padding=(8, 4))
        lf_inference.pack(fill="x", padx=8, pady=4)

        inf_vars = []
        v, k = _int_row(lf_inference, 0, "Inference FPS", "inference_fps", 30, 1, 120)
        inf_vars.append((v, k))
        v, k = _float_row(lf_inference, 1, "Min Detection Confidence",
                          "min_detection_confidence", 0.6, 0.0, 1.0)
        inf_vars.append((v, k))
        v, k = _float_row(lf_inference, 2, "Min Tracking Confidence",
                          "min_tracking_confidence", 0.5, 0.0, 1.0)
        inf_vars.append((v, k))

        use_gpu_var = tk.BooleanVar(value=self._cfg.get("use_gpu", False))
        ttk.Checkbutton(lf_inference, text="Use GPU", variable=use_gpu_var).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=(4, 4), pady=2)

        status_var = tk.StringVar(value="")
        status_lbl = ttk.Label(parent, textvariable=status_var, foreground="green")
        status_lbl.pack(padx=8, pady=(4, 0), anchor="w")

        def _apply_camera():
            for var, key in cam_vars:
                try:
                    self._cfg[key] = int(var.get())
                except (ValueError, TypeError):
                    pass
            from midi_gestures.config import save_config
            save_config(self._cfg, self._config_path)
            status_var.set("Camera settings applied and saved - restart app to take effect.")
            if self._vision:
                threading.Thread(target=self._vision.restart if hasattr(self._vision, "restart")
                                 else lambda: None, daemon=True).start()

        def _apply_inference():
            for var, key in inf_vars:
                try:
                    val = var.get()
                    if key == "inference_fps":
                        self._cfg[key] = int(val)
                    else:
                        self._cfg[key] = round(float(val), 4)
                except (ValueError, TypeError):
                    pass
            self._cfg["use_gpu"] = bool(use_gpu_var.get())
            from midi_gestures.config import save_config
            save_config(self._cfg, self._config_path)
            status_var.set("Applying inference settings...")
            if self._inference:
                def _do_restart():
                    try:
                        self._inference.restart()
                        if self._root:
                            self._root.after(0, lambda: status_var.set("Inference restarted and saved."))
                    except Exception as exc:
                        self._cfg["use_gpu"] = False
                        if self._root:
                            msg = f"Restart failed: {exc}"
                            self._root.after(0, lambda m=msg: status_var.set(m))
                            self._root.after(0, lambda: use_gpu_var.set(False))
                threading.Thread(target=_do_restart, daemon=True).start()
            else:
                status_var.set("Inference settings saved.")

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(btn_frame, text="Apply Camera", command=_apply_camera).pack(
            side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Apply Inference", command=_apply_inference).pack(
            side="left")

    def _build_sensitivity_tab(self, parent, tk, ttk):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(_):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        row = 0
        for plugin in self._plugins:
            schema = plugin.get_param_schema()
            if not schema:
                continue

            plugin_class = plugin.__class__.__name__
            side = getattr(plugin, "_side", None)
            display_name = _PLUGIN_LABELS.get(plugin_class, plugin_class)
            if side:
                display_name = f"{display_name} ({'Right' if side == 'right' else 'Left'})"

            lf = ttk.LabelFrame(inner, text=display_name, padding=(8, 4))
            lf.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
            inner.columnconfigure(0, weight=1)
            row += 1

            _CLASS_TO_CFG_KEY = {
                "PinchPlugin": "pinch", "ShiftPlugin": "shift", "XYPlugin": "xy",
                "RollPlugin": "roll", "DepthPlugin": "depth", "SpeedPlugin": "speed",
                "TapPlugin": "tap", "GesturePlugin": "gesture",
                "ModeManagerPlugin": "mode_manager", "PitchPinchPlugin": "pitch_pinch",
            }
            plugin_cfg_key = _CLASS_TO_CFG_KEY.get(plugin_class)

            for p_idx, (param_name, meta) in enumerate(schema.items()):
                p_min = meta["min"]
                p_max = meta["max"]
                p_val = meta["value"]
                label_text = meta.get("label", param_name)

                ttk.Label(lf, text=label_text, width=26, anchor="w").grid(
                    row=p_idx, column=0, sticky="w", padx=(4, 2))

                var = tk.DoubleVar(value=p_val)

                def _make_callback(pl=plugin, pn=param_name, v=var, cfg_key=plugin_cfg_key):
                    def cb(*_):
                        try:
                            fv = round(float(v.get()), 4)
                            pl.set_param(pn, fv)
                            if cfg_key:
                                if cfg_key not in self._cfg:
                                    self._cfg[cfg_key] = {}
                                self._cfg[cfg_key][pn] = fv
                                from midi_gestures.config import save_config
                                save_config(self._cfg, self._config_path)
                        except (ValueError, TypeError):
                            pass
                    return cb

                cb = _make_callback()

                scale = ttk.Scale(lf, from_=p_min, to=p_max, orient="horizontal",
                                  variable=var, command=lambda _val, c=cb: c())
                scale.grid(row=p_idx, column=1, sticky="ew", padx=4)
                lf.columnconfigure(1, weight=1)

                spin = ttk.Spinbox(lf, from_=p_min, to=p_max, increment=(p_max - p_min) / 100,
                                   width=7, textvariable=var, format="%.3f")
                spin.grid(row=p_idx, column=2, sticky="e", padx=(2, 4))
                var.trace_add("write", cb)

    def _build_cc_tab(self, parent, tk, ttk):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(_):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        ttk.Label(inner, text="Gesture / Signal", font=("", 9, "bold"), width=30, anchor="w").grid(
            row=0, column=0, padx=(8, 4), pady=(6, 2), sticky="w")
        ttk.Label(inner, text="Ch", font=("", 9, "bold"), width=5, anchor="w").grid(
            row=0, column=1, padx=2, sticky="w")
        ttk.Label(inner, text="CC#", font=("", 9, "bold"), width=6, anchor="w").grid(
            row=0, column=2, padx=2, sticky="w")
        ttk.Separator(inner, orient="horizontal").grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=2)

        assignments = self._mapping_engine.get_cc_assignments()

        for row_idx, assignment in enumerate(assignments, start=2):
            ri = assignment["rule_index"]
            oi = assignment["out_index"]
            path = assignment["path"]
            ch = assignment["channel"]
            cc = assignment["cc"]

            key_with_idx = f"{path} [{oi}]"
            display = _PATH_LABELS.get(key_with_idx, _PATH_LABELS.get(path, path))

            ttk.Label(inner, text=display, anchor="w").grid(
                row=row_idx, column=0, padx=(8, 4), pady=1, sticky="w")
            ttk.Label(inner, text=str(ch), anchor="w").grid(
                row=row_idx, column=1, padx=2, sticky="w")

            var = tk.IntVar(value=cc)
            spin = ttk.Spinbox(inner, from_=0, to=127, width=5, textvariable=var)
            spin.grid(row=row_idx, column=2, padx=(2, 8), pady=1, sticky="w")

            def _make_cc_callback(r=ri, o=oi, v=var):
                def cb(*_):
                    try:
                        self._mapping_engine.set_cc(r, o, int(v.get()))
                    except (ValueError, TypeError):
                        pass
                return cb

            var.trace_add("write", _make_cc_callback())

        inner.columnconfigure(0, weight=1)

    def _build_note_tab(self, parent, tk, ttk):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(_):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        ttk.Label(inner, text="Gesture / Signal", font=("", 9, "bold"), width=30, anchor="w").grid(
            row=0, column=0, padx=(8, 4), pady=(6, 2), sticky="w")
        ttk.Label(inner, text="Ch", font=("", 9, "bold"), width=5, anchor="w").grid(
            row=0, column=1, padx=2, sticky="w")
        ttk.Label(inner, text="Note#", font=("", 9, "bold"), width=6, anchor="w").grid(
            row=0, column=2, padx=2, sticky="w")
        ttk.Label(inner, text="Kind", font=("", 9, "bold"), width=12, anchor="w").grid(
            row=0, column=3, padx=2, sticky="w")
        ttk.Separator(inner, orient="horizontal").grid(
            row=1, column=0, columnspan=4, sticky="ew", padx=6, pady=2)

        assignments = self._mapping_engine.get_note_assignments()

        for row_idx, assignment in enumerate(assignments, start=2):
            ri = assignment["rule_index"]
            oi = assignment["out_index"]
            path = assignment["path"]
            ch = assignment["channel"]
            note = assignment["note"]
            kind = assignment["kind"]

            display = _PATH_LABELS.get(path, path)

            ttk.Label(inner, text=display, anchor="w").grid(
                row=row_idx, column=0, padx=(8, 4), pady=1, sticky="w")
            ttk.Label(inner, text=str(ch), anchor="w").grid(
                row=row_idx, column=1, padx=2, sticky="w")

            var = tk.IntVar(value=note)
            spin = ttk.Spinbox(inner, from_=0, to=127, width=5, textvariable=var)
            spin.grid(row=row_idx, column=2, padx=(2, 4), pady=1, sticky="w")

            kind_short = "gate" if kind == "midi_note_gate" else "on"
            ttk.Label(inner, text=kind_short, anchor="w").grid(
                row=row_idx, column=3, padx=(2, 8), sticky="w")

            def _make_note_callback(r=ri, o=oi, v=var):
                def cb(*_):
                    try:
                        self._mapping_engine.set_note(r, o, int(v.get()))
                    except (ValueError, TypeError):
                        pass
                return cb

            var.trace_add("write", _make_note_callback())

        inner.columnconfigure(0, weight=1)

    def _build_toggles_tab(self, parent, tk, ttk):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(_):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _group_key(path: str) -> str:
            if path.startswith("/hand/right/gesture"):
                return "Right Hand - Gestures"
            if path.startswith("/hand/left/gesture"):
                return "Left Hand - Gestures"
            if path.startswith("/hand/right"):
                return "Right Hand - Continuous"
            if path.startswith("/hand/left"):
                return "Left Hand - Continuous"
            if path.startswith("/event/hand/right"):
                return "Right Hand - Events"
            if path.startswith("/event/hand/left"):
                return "Left Hand - Events"
            return "System"

        rules = self._mapping_engine.get_all_rule_info()

        groups: dict = {}
        for rule in rules:
            gk = _group_key(rule["path"])
            groups.setdefault(gk, []).append(rule)

        GROUP_ORDER = [
            "Right Hand - Continuous",
            "Right Hand - Gestures",
            "Right Hand - Events",
            "Left Hand - Continuous",
            "Left Hand - Gestures",
            "Left Hand - Events",
            "System",
        ]

        row = 0
        for group_name in GROUP_ORDER:
            if group_name not in groups:
                continue
            group_rules = groups[group_name]

            lf = ttk.LabelFrame(inner, text=group_name, padding=(8, 4))
            lf.grid(row=row, column=0, sticky="ew", padx=8, pady=(6, 2))
            inner.columnconfigure(0, weight=1)
            row += 1

            rule_vars: list = []

            for r_idx, rule_info in enumerate(group_rules):
                ri = rule_info["rule_index"]
                path = rule_info["path"]
                shift = rule_info["shift"]
                mode = rule_info["mode"]

                key_with_idx = f"{path} [0]"
                label = _PATH_LABELS.get(key_with_idx, _PATH_LABELS.get(path, path))

                suffix_parts = []
                if shift is True:
                    suffix_parts.append("shift")
                if mode is not None:
                    suffix_parts.append(f"mode {mode}")
                if suffix_parts:
                    label = f"{label}  [{', '.join(suffix_parts)}]"

                var = tk.BooleanVar(value=rule_info["enabled"])
                rule_vars.append((ri, var))

                def _make_toggle_cb(rule_index=ri, v=var):
                    def cb(*_):
                        self._mapping_engine.set_rule_enabled(rule_index, v.get())
                    return cb

                ttk.Checkbutton(lf, text=label, variable=var,
                                command=_make_toggle_cb()).grid(
                    row=r_idx, column=0, sticky="w", padx=(4, 4), pady=1)

            btn_row = ttk.Frame(lf)
            btn_row.grid(row=len(group_rules), column=0, sticky="w", pady=(4, 2))

            def _make_group_all(rvars=rule_vars, val=True):
                def cb():
                    for ri2, v2 in rvars:
                        v2.set(val)
                        self._mapping_engine.set_rule_enabled(ri2, val)
                return cb

            ttk.Button(btn_row, text="Enable All",
                       command=_make_group_all(rule_vars, True)).pack(side="left", padx=(0, 4))
            ttk.Button(btn_row, text="Disable All",
                       command=_make_group_all(rule_vars, False)).pack(side="left")

    def _build_mapping_tab(self, parent, tk, ttk):
        import time as _time

        _SKIP = {"/event/panic", "/event/stop"}
        all_rules = self._mapping_engine.get_all_rule_info()
        mapped_paths_ordered = list(dict.fromkeys(
            r["path"] for r in all_rules if r["path"] not in _SKIP
        ))
        mapped_paths_set = set(mapped_paths_ordered)

        # ── Solo mode controls ───────────────────────────────────────────────
        selected_path = [None]
        solo_active = [False]

        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=(10, 4))

        solo_btn_text = tk.StringVar(value="Solo Selected Signal")
        solo_btn = ttk.Button(top, textvariable=solo_btn_text, width=24, state="disabled")
        solo_btn.pack(side="left")
        status_var = tk.StringVar(value="Select a signal below, then click Solo to send only that gesture's MIDI.")
        ttk.Label(top, textvariable=status_var, foreground="gray").pack(side="left", padx=(12, 0))

        def _toggle_solo():
            solo_active[0] = not solo_active[0]
            if solo_active[0]:
                path = selected_path[0]
                if path:
                    self._mapping_engine.set_solo_path(path)
                    if self._output_consumer:
                        self._output_consumer.set_mapping_mode(False)
                    solo_btn_text.set("Stop Solo")
                    key0 = f"{path} [0]"
                    disp = _PATH_LABELS.get(key0, _PATH_LABELS.get(path, path))
                    status_var.set(f"SOLO: {disp}  –  only this signal is sent to MIDI")
                else:
                    solo_active[0] = False
            else:
                self._mapping_engine.set_solo_path(None)
                solo_btn_text.set("Solo Selected Signal")
                status_var.set("Select a signal below, then click Solo to send only that gesture's MIDI.")

        solo_btn.config(command=_toggle_solo)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=(6, 0))

        # ── Active signals list ──────────────────────────────────────────────
        sig_outer = ttk.Frame(parent)
        sig_outer.pack(fill="x", padx=8, pady=(6, 4))

        ttk.Label(sig_outer, text="Active Signals", font=("", 9, "bold")).pack(anchor="w")
        ttk.Label(sig_outer, text="Click Select next to a signal, then click Solo above to send only that gesture.",
                  foreground="gray").pack(anchor="w", pady=(0, 4))

        sig_lf = ttk.Frame(sig_outer, relief="sunken", borderwidth=1)
        sig_lf.pack(fill="x")

        hdr = ttk.Frame(sig_lf)
        hdr.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(hdr, text="Signal", width=28, anchor="w", font=("", 8, "bold")).pack(side="left")
        ttk.Label(hdr, text="Level", width=14, anchor="w", font=("", 8, "bold")).pack(side="left", padx=(4, 0))
        ttk.Separator(sig_lf, orient="horizontal").pack(fill="x")

        NUM_ROWS = min(len(mapped_paths_ordered), 14)
        slot_paths = [""] * NUM_ROWS
        slot_name_vars = []
        slot_bar_vars = []
        slot_val_vars = []
        slot_btns = []

        for i in range(NUM_ROWS):
            rf = ttk.Frame(sig_lf)
            rf.pack(fill="x", padx=4, pady=1)

            nv = tk.StringVar(value="")
            ttk.Label(rf, textvariable=nv, width=28, anchor="w").pack(side="left")

            bv = tk.DoubleVar(value=0.0)
            pb = ttk.Progressbar(rf, orient="horizontal", length=100, maximum=1.0,
                                 mode="determinate", variable=bv)
            pb.pack(side="left", padx=(4, 4))

            vv = tk.StringVar(value="")
            ttk.Label(rf, textvariable=vv, width=5, anchor="e").pack(side="left")

            sb = ttk.Button(rf, text="Select", width=6,
                            command=lambda ii=i: _select_slot(ii))
            sb.pack(side="left", padx=(6, 0))
            sb.config(state="disabled")

            slot_name_vars.append(nv)
            slot_bar_vars.append(bv)
            slot_val_vars.append(vv)
            slot_btns.append(sb)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=(4, 0))

        # ── Editor panel ─────────────────────────────────────────────────────
        edit_header_var = tk.StringVar(value="Edit Selected Signal")
        edit_lf = ttk.LabelFrame(parent, labelwidget=ttk.Label(parent, textvariable=edit_header_var,
                                                                font=("", 9, "bold")),
                                 padding=(8, 6))
        edit_lf.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        placeholder = ttk.Label(edit_lf,
                                text="No signal selected.\nClick Select next to any signal above.",
                                foreground="gray", justify="center")
        placeholder.pack(pady=20)

        editor_frame = ttk.Frame(edit_lf)

        def _build_editor(path):
            for w in editor_frame.winfo_children():
                w.destroy()

            key0 = f"{path} [0]"
            display = _PATH_LABELS.get(key0, _PATH_LABELS.get(path, path))
            edit_header_var.set(f"Edit: {display}")

            ttk.Label(editor_frame, text=path, foreground="gray").grid(
                row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))

            cc_list = [a for a in self._mapping_engine.get_cc_assignments() if a["path"] == path]
            note_list = [a for a in self._mapping_engine.get_note_assignments() if a["path"] == path]
            rule_info = {r["rule_index"]: r for r in self._mapping_engine.get_all_rule_info()
                         if r["path"] == path}

            entries = []
            row_idx = 1

            def _shift_suffix(r_info):
                parts = []
                s = r_info.get("shift")
                m = r_info.get("mode")
                if s is True:
                    parts.append("shift")
                elif s is False:
                    parts.append("no shift")
                if m is not None:
                    parts.append(f"mode {m}")
                return f"  [{', '.join(parts)}]" if parts else ""

            for a in cc_list:
                ri = a["rule_index"]
                oi = a["out_index"]
                suffix = _shift_suffix(rule_info.get(ri, {}))

                ttk.Label(editor_frame, text=f"CC{suffix}", width=18, anchor="w").grid(
                    row=row_idx, column=0, padx=(0, 4), pady=3, sticky="w")
                ttk.Label(editor_frame, text="Ch:", anchor="e").grid(
                    row=row_idx, column=1, padx=(0, 2))
                ch_var = tk.IntVar(value=a["channel"])
                ttk.Spinbox(editor_frame, from_=1, to=16, width=4, textvariable=ch_var).grid(
                    row=row_idx, column=2, padx=(0, 10))
                ttk.Label(editor_frame, text="CC#:", anchor="e").grid(
                    row=row_idx, column=3, padx=(0, 2))
                cc_var = tk.IntVar(value=a["cc"])
                ttk.Spinbox(editor_frame, from_=0, to=127, width=5, textvariable=cc_var).grid(
                    row=row_idx, column=4, padx=(0, 10))
                en_var = tk.BooleanVar(value=self._mapping_engine.is_rule_enabled(ri))
                ttk.Checkbutton(editor_frame, text="Enabled", variable=en_var).grid(
                    row=row_idx, column=5)
                entries.append(("cc", ri, oi, cc_var, ch_var, en_var))
                row_idx += 1

            for a in note_list:
                ri = a["rule_index"]
                oi = a["out_index"]
                suffix = _shift_suffix(rule_info.get(ri, {}))
                kind_short = {"midi_note_gate": "gate", "midi_note_on": "on",
                              "midi_note_gate_pitched": "pitched"}.get(a.get("kind", ""), "note")

                ttk.Label(editor_frame, text=f"Note/{kind_short}{suffix}", width=18, anchor="w").grid(
                    row=row_idx, column=0, padx=(0, 4), pady=3, sticky="w")
                ttk.Label(editor_frame, text="Ch:", anchor="e").grid(
                    row=row_idx, column=1, padx=(0, 2))
                ch_var = tk.IntVar(value=a["channel"])
                ttk.Spinbox(editor_frame, from_=1, to=16, width=4, textvariable=ch_var).grid(
                    row=row_idx, column=2, padx=(0, 10))
                ttk.Label(editor_frame, text="Note#:", anchor="e").grid(
                    row=row_idx, column=3, padx=(0, 2))
                note_var = tk.IntVar(value=a["note"])
                ttk.Spinbox(editor_frame, from_=0, to=127, width=5, textvariable=note_var).grid(
                    row=row_idx, column=4, padx=(0, 10))
                en_var = tk.BooleanVar(value=self._mapping_engine.is_rule_enabled(ri))
                ttk.Checkbutton(editor_frame, text="Enabled", variable=en_var).grid(
                    row=row_idx, column=5)
                entries.append(("note", ri, oi, note_var, ch_var, en_var))
                row_idx += 1

            if not entries:
                ttk.Label(editor_frame, text="(No CC or Note outputs for this path)",
                          foreground="gray").grid(row=row_idx, column=0, columnspan=6, pady=4)
                row_idx += 1

            save_status = tk.StringVar(value="")

            def _save():
                from midi_gestures.config import save_config
                for kind, ri, oi, val_var, ch_var, en_var in entries:
                    try:
                        if kind == "cc":
                            self._mapping_engine.set_cc(ri, oi, int(val_var.get()))
                        else:
                            self._mapping_engine.set_note(ri, oi, int(val_var.get()))
                        self._mapping_engine.set_rule_enabled(ri, en_var.get())
                    except (ValueError, TypeError):
                        pass
                save_config(self._cfg, self._config_path)
                save_status.set("Saved.")
                editor_frame.after(2000, lambda: save_status.set(""))

            ttk.Separator(editor_frame, orient="horizontal").grid(
                row=row_idx, column=0, columnspan=6, sticky="ew", pady=(8, 4))
            row_idx += 1
            ttk.Button(editor_frame, text="Apply & Save", command=_save).grid(
                row=row_idx, column=4, columnspan=2, sticky="e", pady=(0, 2))
            ttk.Label(editor_frame, textvariable=save_status, foreground="green").grid(
                row=row_idx, column=0, columnspan=4, sticky="w")

        def _select_path(path):
            if not path:
                return
            if solo_active[0]:
                solo_active[0] = False
                self._mapping_engine.set_solo_path(None)
                solo_btn_text.set("Solo Selected Signal")
                status_var.set("Select a signal below, then click Solo to send only that gesture's MIDI.")
            selected_path[0] = path
            placeholder.pack_forget()
            editor_frame.pack(fill="both", expand=True)
            _build_editor(path)
            solo_btn.config(state="normal")

        def _select_slot(idx):
            p = slot_paths[idx]
            if p:
                _select_path(p)

        # ── Refresh loop ──────────────────────────────────────────────────────
        def _refresh():
            now = _time.monotonic()
            path_vals = []
            for p in mapped_paths_ordered:
                entry = self._active_paths.get(p)
                if entry:
                    val, ts = entry
                    age = now - ts
                    effective = max(0.0, abs(float(val)) * max(0.0, 1.0 - age / 1.5))
                else:
                    effective = 0.0
                path_vals.append((p, effective))

            path_vals.sort(key=lambda x: x[1], reverse=True)

            for i in range(NUM_ROWS):
                if i < len(path_vals):
                    p, eff = path_vals[i]
                    slot_paths[i] = p
                    key0 = f"{p} [0]"
                    disp = _PATH_LABELS.get(key0, _PATH_LABELS.get(p, p))
                    slot_name_vars[i].set(disp)
                    slot_bar_vars[i].set(min(1.0, eff))
                    slot_val_vars[i].set(f"{eff:.2f}")
                    slot_btns[i].config(state="normal")
                else:
                    slot_paths[i] = ""
                    slot_name_vars[i].set("")
                    slot_bar_vars[i].set(0.0)
                    slot_val_vars[i].set("")
                    slot_btns[i].config(state="disabled")

            parent.after(200, _refresh)

        parent.after(200, _refresh)