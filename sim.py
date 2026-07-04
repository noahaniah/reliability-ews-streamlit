"""
Predictive Maintenance & Reliability Early-Warning System — simulation engine.

Simulates IoT sensor telemetry for cement-plant electrical control panels,
runs anomaly detection (one IsolationForest per panel, trained on that
panel's own normal-operation baseline), computes a composite risk score,
and raises tiered alerts. Framework-agnostic — the Streamlit app in app.py
just reads this state and renders it.
"""

import random
import uuid
from collections import deque
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import IsolationForest

SENSOR_KEYS = ["voltage", "current", "temperature", "vibration", "power_factor", "switch_freq"]

SENSOR_META = {
    "voltage":      {"label": "Voltage",             "unit": "V",    "baseline": 415,  "noise": 2.5},
    "current":      {"label": "Current",              "unit": "A",    "baseline": 120,  "noise": 3.0},
    "temperature":  {"label": "Panel Temperature",    "unit": "°C",   "baseline": 45,   "noise": 1.2},
    "vibration":    {"label": "Vibration",             "unit": "mm/s", "baseline": 2.0,  "noise": 0.15},
    "power_factor": {"label": "Power Factor",          "unit": "",     "baseline": 0.92, "noise": 0.01},
    "switch_freq":  {"label": "Switching Frequency",   "unit": "Hz",   "baseline": 50,   "noise": 0.3},
}

PANELS_CONFIG = [
    {"id": "raw-mill-01",    "name": "Raw Mill Control Panel",     "section": "Raw Mill",      "criticality": 0.9},
    {"id": "kiln-01",        "name": "Kiln Drive Panel",           "section": "Kiln",           "criticality": 1.0},
    {"id": "preheater-01",   "name": "Preheater Fan Panel",        "section": "Preheater",      "criticality": 0.8},
    {"id": "cement-mill-01", "name": "Cement Mill MCC",            "section": "Cement Mill",    "criticality": 0.85},
    {"id": "crusher-01",     "name": "Crusher Feeder Panel",       "section": "Crusher",        "criticality": 0.6},
    {"id": "packing-01",     "name": "Packing Plant Distribution", "section": "Packing Plant",  "criticality": 0.5},
]

HISTORY_LEN = 60
ANOMALY_CHANCE = 0.06
WARNING_THRESHOLD = 40
CRITICAL_THRESHOLD = 70

CAUSES = {
    "voltage":       {"elevated": "Possible upstream supply fluctuation or failing voltage regulator.",
                       "depressed": "Possible loose connection, cable degradation, or transformer tap issue."},
    "current":       {"elevated": "Possible motor overload, bearing wear, or partial short circuit.",
                       "depressed": "Possible loss of phase, blown fuse, or downstream disconnection."},
    "temperature":   {"elevated": "Possible cooling fan failure, loose busbar connection, or overload heating.",
                       "depressed": "Sensor drift or ambient cooling anomaly; verify sensor calibration."},
    "vibration":     {"elevated": "Possible bearing degradation, motor misalignment, or mechanical looseness.",
                       "depressed": "Unusual; verify sensor mounting and calibration."},
    "power_factor":  {"elevated": "Unusual; check capacitor bank controller.",
                       "depressed": "Possible capacitor bank fault or reactive load imbalance."},
    "switch_freq":   {"elevated": "Possible contactor chatter or control logic fault.",
                       "depressed": "Possible sticking contactor or control signal loss."},
}

STEPS = {
    "voltage":      ["Check incoming supply and transformer tap settings.", "Inspect terminal connections for looseness/corrosion.", "Verify with a calibrated multimeter before panel access."],
    "current":      ["Inspect motor load and coupling for mechanical binding.", "Check for phase imbalance.", "Review protection relay trip history."],
    "temperature":  ["Inspect cooling fan/vents for blockage.", "Thermal-scan busbar joints for hot spots.", "Confirm sensor calibration."],
    "vibration":    ["Perform vibration spectrum analysis on driven motor.", "Check mounting bolts and alignment.", "Schedule bearing inspection."],
    "power_factor": ["Inspect capacitor bank fuses and contactors.", "Check for reactive load changes on the bus.", "Verify controller setpoints."],
    "switch_freq":  ["Inspect contactor contacts for pitting.", "Check control wiring for noise/interference.", "Review PLC/relay logic timers."],
}


class Panel:
    def __init__(self, cfg):
        self.id = cfg["id"]
        self.name = cfg["name"]
        self.section = cfg["section"]
        self.criticality = cfg["criticality"]
        self.current = {k: SENSOR_META[k]["baseline"] for k in SENSOR_KEYS}
        self.history = {k: deque(maxlen=HISTORY_LEN) for k in SENSOR_KEYS}
        self.risk_history = deque(maxlen=HISTORY_LEN)
        self.risk_score = 5.0
        self.status = "normal"
        self.drift = {k: 0.0 for k in SENSOR_KEYS}
        self.drifting_sensor = None
        self.failure_history_count = random.randint(0, 4)
        self.model, self.train_scores_sorted = self._train_baseline_model()
        self._seed_history()

    def _train_baseline_model(self):
        rng = np.random.default_rng(hash(self.id) % (2**32))
        rows = [[rng.normal(SENSOR_META[k]["baseline"], SENSOR_META[k]["noise"]) for k in SENSOR_KEYS]
                for _ in range(300)]
        model = IsolationForest(n_estimators=100, contamination=0.03, random_state=42)
        model.fit(rows)
        train_scores = np.sort(model.decision_function(rows))
        return model, train_scores

    def _seed_history(self):
        for _ in range(HISTORY_LEN):
            self.step(alerts=None, seed=True)

    def step(self, alerts, seed=False):
        """Advance the simulation by one tick. `alerts` is a list-like to append raised alerts to."""
        for k in SENSOR_KEYS:
            meta = SENSOR_META[k]
            noise = random.gauss(0, meta["noise"])
            pull_back = (meta["baseline"] - self.current[k]) * 0.5
            self.current[k] = self.current[k] + noise + pull_back + self.drift[k]
            self.history[k].append(round(self.current[k], 3))

        if not seed:
            if self.drifting_sensor:
                self.drift[self.drifting_sensor] *= 1.15
            elif random.random() < ANOMALY_CHANCE:
                self.drifting_sensor = random.choice(SENSOR_KEYS)
                direction = random.choice([-1, 1])
                self.drift[self.drifting_sensor] = direction * SENSOR_META[self.drifting_sensor]["noise"] * 1.5

        self._score(alerts, seed=seed)

    def _score(self, alerts, seed=False):
        reading = [[self.current[k] for k in SENSOR_KEYS]]
        raw_score = self.model.decision_function(reading)[0]
        percentile_rank = np.searchsorted(self.train_scores_sorted, raw_score) / len(self.train_scores_sorted)
        anomaly_severity = max(0.0, min(1.0, (0.06 - percentile_rank) / 0.06))

        rate_of_change = 0.0
        if self.drifting_sensor:
            meta = SENSOR_META[self.drifting_sensor]
            rate_of_change = min(1.0, abs(self.drift[self.drifting_sensor]) / (meta["noise"] * 10))

        historical_factor = min(1.0, self.failure_history_count / 5)
        production_impact = self.criticality

        fault_signal = max(anomaly_severity, rate_of_change)
        amplified_ceiling = 50 + historical_factor * 15 + production_impact * 25
        composite = fault_signal * amplified_ceiling
        self.risk_score = round(float(min(100, max(0, composite))), 1)
        self.risk_history.append(self.risk_score)

        prev_status = self.status
        if self.risk_score >= CRITICAL_THRESHOLD:
            self.status = "critical"
        elif self.risk_score >= WARNING_THRESHOLD:
            self.status = "warning"
        else:
            self.status = "normal"
            self.drifting_sensor = None
            for k in SENSOR_KEYS:
                self.drift[k] = 0.0

        if not seed and alerts is not None and self.status != prev_status and self.status in ("warning", "critical"):
            alerts.appendleft({
                "id": str(uuid.uuid4())[:8],
                "panel_id": self.id,
                "panel_name": self.name,
                "section": self.section,
                "level": self.status,
                "risk_score": self.risk_score,
                "dominant_sensor": self.drifting_sensor,
                "timestamp": datetime.now(timezone.utc),
                "resolved": False,
            })

    def diagnostic_insight(self):
        if not self.drifting_sensor:
            return {
                "probable_cause": "No active deviation. All monitored parameters within normal range.",
                "recommended_steps": ["No action required.", "Continue routine monitoring."],
            }
        sensor = self.drifting_sensor
        meta = SENSOR_META[sensor]
        direction = "elevated" if self.drift[sensor] > 0 else "depressed"
        return {
            "probable_cause": f"{meta['label']} is {direction} relative to baseline. {CAUSES[sensor][direction]}",
            "recommended_steps": STEPS[sensor],
        }

    def resolve(self):
        self.drifting_sensor = None
        for k in SENSOR_KEYS:
            self.drift[k] = 0.0
        self.failure_history_count += 1
        self._score(alerts=None)


def create_panels():
    return {cfg["id"]: Panel(cfg) for cfg in PANELS_CONFIG}
