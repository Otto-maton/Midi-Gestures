from __future__ import annotations
import copy
import time
import logging
from typing import List, Dict, Tuple
from midi_gestures.bus import BusMessage
from midi_gestures.models import MappingContext, OutputMessage

logger = logging.getLogger(__name__)


class MappingEngine:
    def __init__(self, mapping_tables: list, cfg: dict):
        self._tables = copy.deepcopy(mapping_tables)
        for rule in self._tables:
            out = rule.get("output")
            if isinstance(out, dict):
                rule["output"] = [out]
            elif out is None:
                rule["output"] = []
        self._cfg = cfg
        self._context = MappingContext()
        self._rate_buckets: Dict[str, float] = {}
        self._rate_limit_s = cfg.get("output_rate_limit_s", 0.008)
        # (rule_idx, out_idx) -> (channel, note) currently sounding
        self._pitched_gate_notes: Dict[Tuple[int, int], Tuple[int, int]] = {}
        saved = cfg.get("rule_enabled", {})
        self._rule_enabled: Dict[int, bool] = {int(k): bool(v) for k, v in saved.items()}
        self._solo_path: str | None = None
        self._rules_by_path: Dict[str, list] = {}
        for i, rule in enumerate(self._tables):
            self._rules_by_path.setdefault(rule["path"], []).append(i)

    def set_solo_path(self, path: str | None):
        self._solo_path = path

    def get_solo_path(self) -> str | None:
        return self._solo_path

    def get_cc_assignments(self) -> list:
        result = []
        for i, rule in enumerate(self._tables):
            for j, o in enumerate(rule["output"]):
                if o.get("kind") == "midi_cc":
                    result.append({
                        "rule_index": i,
                        "out_index": j,
                        "path": rule["path"],
                        "cc": o["cc"],
                        "channel": o["channel"],
                        "label": f"{rule['path']} [{j}]",
                    })
        return result

    def set_cc(self, rule_index: int, out_index: int, new_cc: int):
        self._tables[rule_index]["output"][out_index]["cc"] = max(0, min(127, int(new_cc)))

    def get_note_assignments(self) -> list:
        result = []
        note_kinds = ("midi_note_gate", "midi_note_on", "midi_note_gate_pitched")
        for i, rule in enumerate(self._tables):
            for j, o in enumerate(rule["output"]):
                if o.get("kind") in note_kinds:
                    result.append({
                        "rule_index": i,
                        "out_index": j,
                        "path": rule["path"],
                        "note": o.get("note", 0),
                        "channel": o["channel"],
                        "kind": o["kind"],
                    })
        return result

    def set_note(self, rule_index: int, out_index: int, new_note: int):
        self._tables[rule_index]["output"][out_index]["note"] = max(0, min(127, int(new_note)))

    def is_rule_enabled(self, rule_index: int) -> bool:
        return self._rule_enabled.get(rule_index, True)

    def set_rule_enabled(self, rule_index: int, enabled: bool):
        self._rule_enabled[rule_index] = bool(enabled)
        if "rule_enabled" not in self._cfg:
            self._cfg["rule_enabled"] = {}
        self._cfg["rule_enabled"][str(rule_index)] = bool(enabled)

    def get_all_rule_info(self) -> list:
        return [
            {
                "rule_index": i,
                "path": rule["path"],
                "shift": rule.get("shift"),
                "mode": rule.get("mode"),
                "kinds": [o.get("kind", "") for o in rule["output"]],
                "enabled": self.is_rule_enabled(i),
            }
            for i, rule in enumerate(self._tables)
        ]

    def update_context(self, msg: BusMessage):
        if not msg.args:
            return
        if msg.path == "/shift":
            self._context.shift_state = bool(msg.args[0])
        elif msg.path == "/mode/index":
            self._context.mode_index = int(msg.args[0])
        elif msg.path.startswith("/hand/") and msg.path.endswith("/present"):
            parts = msg.path.split("/")
            if len(parts) >= 3:
                self._context.hand_presence[parts[2]] = bool(msg.args[0])

    def process(self, msg: BusMessage) -> List[OutputMessage]:
        self.update_context(msg)
        outputs = self._release_inactive_pitched()
        candidate_indices = self._rules_by_path.get(msg.path, [])
        if not candidate_indices:
            return outputs
        if self._solo_path is not None and msg.path != self._solo_path:
            return outputs
        for rule_idx in candidate_indices:
            if not self._rule_active(rule_idx):
                continue
            rule = self._tables[rule_idx]
            arg_index = rule.get("arg_index", 0)
            for i, tmpl in enumerate(rule["output"]):
                if tmpl.get("kind") == "midi_note_gate_pitched":
                    outputs.extend(self._build_pitched_gate(tmpl, msg, (rule_idx, i)))
                    continue
                idx = arg_index[i] if isinstance(arg_index, list) else arg_index
                om = self._build_output(tmpl, msg, idx)
                if om:
                    bucket = self._bucket_key(tmpl, msg.path, i)
                    if self._check_rate(bucket):
                        outputs.append(om)
        return outputs

    def _rule_active(self, rule_idx: int) -> bool:
        if not self._rule_enabled.get(rule_idx, True):
            return False
        rule = self._tables[rule_idx]
        if self._solo_path is not None and rule["path"] != self._solo_path:
            return False
        shift_req = rule.get("shift")
        if shift_req is not None and shift_req != self._context.shift_state:
            return False
        mode_req = rule.get("mode")
        if mode_req is not None and mode_req != self._context.mode_index:
            return False
        return True

    def _build_pitched_gate(self, tmpl: dict, msg: BusMessage, key: Tuple[int, int]) -> List[OutputMessage]:
        # Sources may stream [note, gate] every frame, so only edges produce
        # MIDI: a pitch change while held releases the old note first.
        if len(msg.args) < 2:
            return []
        note = max(0, min(127, int(round(float(msg.args[0])))))
        ch = tmpl["channel"]
        if float(msg.args[1]) < 0.5:
            return self._release_pitched(key)
        if self._pitched_gate_notes.get(key) == (ch, note):
            return []
        outputs = self._release_pitched(key)
        self._pitched_gate_notes[key] = (ch, note)
        outputs.append(OutputMessage(kind="midi_note_gate_on", data={
            "channel": ch,
            "note": note,
            "velocity": tmpl.get("velocity", 100),
        }))
        return outputs

    def _release_pitched(self, key: Tuple[int, int]) -> List[OutputMessage]:
        held = self._pitched_gate_notes.pop(key, None)
        if held is None:
            return []
        ch, note = held
        return [OutputMessage(kind="midi_note_gate_off", data={"channel": ch, "note": note, "velocity": 0})]

    def _release_inactive_pitched(self) -> List[OutputMessage]:
        # A held note whose rule stops applying (shift/mode change, rule
        # disabled, other path soloed) would never receive its gate-off.
        outputs = []
        for key in [k for k in self._pitched_gate_notes if not self._rule_active(k[0])]:
            outputs.extend(self._release_pitched(key))
        return outputs

    def _matches_rule(self, rule: dict, msg: BusMessage) -> bool:
        if rule["path"] != msg.path:
            return False
        shift_req = rule.get("shift")
        if shift_req is not None and shift_req != self._context.shift_state:
            return False
        mode_req = rule.get("mode")
        if mode_req is not None and mode_req != self._context.mode_index:
            return False
        return True

    def _build_output(self, tmpl: dict, msg: BusMessage, arg_idx: int) -> OutputMessage | None:
        kind = tmpl.get("kind")
        if not kind:
            return None

        if kind == "midi_cc":
            raw = msg.args[arg_idx] if arg_idx < len(msg.args) else 0.0
            scale_max = tmpl.get("scale_max")
            if scale_max is not None:
                value = int(round(raw * (127 / max(scale_max, 1))))
            elif tmpl.get("snap"):
                value = 127 if raw else 0
            else:
                value = int(round(float(raw) * 127))
            value = max(0, min(127, value))
            return OutputMessage(kind="midi_cc", data={
                "channel": tmpl["channel"],
                "cc": tmpl["cc"],
                "value": value,
            })

        elif kind == "midi_note_on":
            vel = tmpl.get("velocity", 100)
            return OutputMessage(kind="midi_note_on", data={
                "channel": tmpl["channel"],
                "note": tmpl["note"],
                "velocity": vel,
                "duration_s": tmpl.get("duration_s", 0.1),
            })

        elif kind == "midi_note_gate":
            raw = msg.args[arg_idx] if arg_idx < len(msg.args) else 0.0
            if float(raw) >= 0.5:
                return OutputMessage(kind="midi_note_gate_on", data={
                    "channel": tmpl["channel"],
                    "note": tmpl["note"],
                    "velocity": tmpl.get("velocity", 100),
                })
            else:
                return OutputMessage(kind="midi_note_gate_off", data={
                    "channel": tmpl["channel"],
                    "note": tmpl["note"],
                    "velocity": 0,
                })

        elif kind == "panic":
            return OutputMessage(kind="panic", data={})

        elif kind == "osc":
            return OutputMessage(kind="osc", data={
                "address": tmpl.get("address", msg.path),
                "args": msg.args,
            })

        return None

    def _bucket_key(self, tmpl: dict, path: str, idx: int) -> str:
        kind = tmpl.get("kind", "")
        if kind == "midi_cc":
            return f"cc_{tmpl.get('channel')}_{tmpl.get('cc')}"
        elif kind == "midi_note_on":
            return f"note_{tmpl.get('channel')}_{tmpl.get('note')}"
        return f"{path}_{idx}"

    def _check_rate(self, bucket: str) -> bool:
        now = time.monotonic()
        last = self._rate_buckets.get(bucket, 0.0)
        if now - last >= self._rate_limit_s:
            self._rate_buckets[bucket] = now
            return True
        return False

