"""
Predictive Maintenance & Reliability Early-Warning System — simulation engine.

Simulates IoT sensor telemetry for cement-plant electrical control panels,
runs anomaly detection (one IsolationForest per panel, trained on that
panel's own normal-operation baseline), computes a composite risk score,
and raises tiered alerts. Framework-agnostic — the Streamlit app in app.py
just reads this state and renders it.

On top of detection, this module also simulates the escalation workflow:
the moment a panel first crosses into Warning, it auto-builds a message
addressed to that line's manager (with the Electrical Manager copied and
the technician rostered on duty that day named directly), so nobody has
to manually notice a fault and go tell someone — the system already told
the right three people, with the diagnosis and the exact steps to take.
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

# --------------------------------------------------------------------------
# Duty roster — who gets notified, per line, plus who's on shift today.
# In a real deployment this would be pulled from an HR/shift-scheduling
# system; here it's fixed + randomly rostered per session to demonstrate
# the workflow without needing that integration yet.
# --------------------------------------------------------------------------

ELECTRICAL_MANAGER = "Engr. Ifeanyi Okoro"

LINE_MANAGERS = {
    "Raw Mill":       "Tunde Bakare",
    "Kiln":           "Ngozi Umeh",
    "Preheater":      "Ibrahim Sule",
    "Cement Mill":    "Chika Nwosu",
    "Crusher":        "Emeka Obi",
    "Packing Plant":  "Fatima Bello",
}

TECHNICIAN_POOL = [
    "Chinedu Eze", "Aisha Mohammed", "Peter Danladi", "Blessing Achebe",
    "Sunday Okafor", "Grace Adeyemi", "Musa Ibrahim", "Ada Chukwu",
]

CAUSES = {
    "voltage":       {"elevated": "voltage regulation fault — most likely an upstream supply fluctuation or a failing voltage regulator inside the panel.",
                       "depressed": "a voltage drop consistent with a loose connection, degraded cable, or a transformer tap that has shifted."},
    "current":       {"elevated": "an overcurrent condition consistent with motor overload, bearing wear increasing mechanical drag, or a developing partial short circuit.",
                       "depressed": "an undercurrent condition consistent with a lost phase, a blown fuse, or a downstream disconnection."},
    "temperature":   {"elevated": "abnormal heat buildup consistent with a cooling fan failure, a loose/high-resistance busbar joint, or sustained overload heating.",
                       "depressed": "a temperature reading below expected range — check for sensor drift or a calibration issue before assuming a real fault."},
    "vibration":     {"elevated": "mechanical vibration consistent with bearing degradation, motor misalignment, or a loosened mounting.",
                       "depressed": "an unusually low vibration reading — verify the sensor is still properly mounted before ruling out a fault."},
    "power_factor":  {"elevated": "an unusual power factor reading — check the capacitor bank controller for a stuck or miscalibrated setpoint.",
                       "depressed": "a falling power factor consistent with a capacitor bank fault or a reactive load imbalance on the bus."},
    "switch_freq":   {"elevated": "irregular switching consistent with contactor chatter or a control-logic fault.",
                       "depressed": "reduced switching activity consistent with a sticking contactor or a lost control signal."},
}

# Detailed, numbered, safety-first procedures — written so a technician can
# act on them directly without having to guess what "check the panel" means.
STEPS = {
    "voltage": [
        "Before opening the panel: confirm PPE (insulated gloves, face shield) and apply lockout/tagout if isolation is required for the check.",
        "Verify the incoming supply voltage at the main breaker with a calibrated multimeter — confirm it matches the utility/generator output.",
        "Inspect all line and load terminal connections for looseness, discoloration, or corrosion; torque any loose terminals to spec.",
        "Check the transformer tap setting against the panel's nameplate configuration.",
        "If supply and terminations check out, test the voltage regulator output directly; replace if it is out of tolerance.",
        "Log the corrected reading and clear the alert only after two consecutive stable readings.",
    ],
    "current": [
        "Confirm no immediate safety hazard (smoke, smell of burning insulation) before proceeding — evacuate and escalate immediately if present.",
        "Check the driven motor for mechanical binding: attempt to rotate the shaft by hand (motor de-energized) to feel for resistance.",
        "Measure current on all three phases and compare for imbalance greater than 5%.",
        "Pull the protection relay's trip history for repeated nuisance trips on this circuit.",
        "Inspect motor bearings for play or noise consistent with wear contributing to load.",
        "If imbalance or binding is confirmed, isolate and tag the motor for maintenance before re-energizing.",
    ],
    "temperature": [
        "Check the enclosure's cooling fan is running and unobstructed; clear any dust/debris from intake and exhaust vents.",
        "Use a thermal camera or infrared thermometer to scan busbar joints and contactor terminals for hot spots above 60°C differential.",
        "Re-torque any joint reading hot relative to its neighbors.",
        "Confirm the ambient temperature sensor reading against a handheld reference thermometer to rule out sensor drift.",
        "If heat persists after cooling/torque checks, inspect for sustained overload on the circuit (see current fault procedure).",
    ],
    "vibration": [
        "Do not touch rotating components — take all readings with the equipment running and guards in place.",
        "Run a vibration spectrum reading on the driven motor and compare against baseline signature.",
        "Visually and physically check mounting bolts for looseness (equipment stopped and isolated for this step).",
        "Check shaft coupling alignment against the motor's alignment spec.",
        "If the spectrum shows a bearing-frequency signature, schedule a bearing inspection/replacement before next production run.",
    ],
    "power_factor": [
        "Inspect the capacitor bank fuses for any blown indicators.",
        "Check capacitor bank contactors are cycling correctly under the automatic controller.",
        "Review recent changes in reactive load on this bus (new equipment added, load pattern change).",
        "Verify controller setpoints haven't been altered from commissioning values.",
        "Replace any capacitor unit that tests outside ±10% of rated capacitance.",
    ],
    "switch_freq": [
        "De-energize and inspect contactor contacts for pitting or burning; replace if worn beyond spec.",
        "Check control wiring for loose connections or interference sources near the control cabinet.",
        "Review PLC/relay logic timer settings against the commissioning configuration.",
        "Cycle the contactor manually (de-energized) to confirm free mechanical movement.",
        "Re-energize and confirm stable switching over at least 10 consecutive cycles before clearing the alert.",
    ],
}


class Panel:
    def __init__(self, cfg, technician):
        self.id = cfg["id"]
        self.name = cfg["name"]
        self.section = cfg["section"]
        self.criticality = cfg["criticality"]
        self.line_manager = LINE_MANAGERS[self.section]
        self.technician = technician
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
            alert = {
                "id": str(uuid.uuid4())[:8],
                "panel_id": self.id,
                "panel_name": self.name,
                "section": self.section,
                "level": self.status,
                "risk_score": self.risk_score,
                "dominant_sensor": self.drifting_sensor,
                "timestamp": datetime.now(timezone.utc),
                "resolved": False,
            }
            alert["notification"] = self.build_notification()
            alerts.appendleft(alert)

    def diagnostic_insight(self):
        if not self.drifting_sensor:
            return {
                "probable_cause": "No active deviation. All monitored parameters within normal range.",
                "recommended_steps": ["No action required.", "Continue routine monitoring."],
            }
        sensor = self.drifting_sensor
        meta = SENSOR_META[sensor]
        direction = "elevated" if self.drift[sensor] > 0 else "depressed"
        value = round(self.current[sensor], 2)
        baseline = meta["baseline"]
        pct = round((value - baseline) / baseline * 100, 1)
        return {
            "probable_cause": (
                f"{meta['label']} is reading {value}{meta['unit']} against a baseline of {baseline}{meta['unit']} "
                f"({'+' if pct >= 0 else ''}{pct}%), consistent with {CAUSES[sensor][direction]}"
            ),
            "recommended_steps": STEPS[sensor],
        }

    def build_notification(self):
        """Build the auto-dispatched escalation message for the current fault —
        addressed to this line's manager, copying the Electrical Manager, and
        naming the technician already rostered on duty for this line today."""
        insight = self.diagnostic_insight()
        urgency = (
            "CRITICAL — IMMEDIATE ACTION REQUIRED"
            if self.status == "critical"
            else "EARLY WARNING — PLEASE REVIEW BEFORE THIS ESCALATES"
        )
        steps_block = "\n".join(f"  {i}. {s}" for i, s in enumerate(STEPS.get(self.drifting_sensor, []), start=1)) \
            if self.drifting_sensor else "  1. Continue monitoring.\n  2. Re-check after the next reading cycle."

        subject = f"[{self.status.upper()}] {self.name} — {self.section} — Risk {self.risk_score}/100"
        body = (
            f"{urgency}\n\n"
            f"Line: {self.section}\n"
            f"Panel: {self.name}\n"
            f"Risk score: {self.risk_score}/100 ({self.status.upper()})\n"
            f"Time detected: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            f"Diagnosis:\n  {insight['probable_cause']}\n\n"
            f"Recommended steps:\n{steps_block}\n\n"
            f"Technician on duty today for {self.section}: {self.technician}. Please proceed to the control room "
            f"to review this reading before it progresses further — no need to wait for a manual report."
        )
        return {
            "to": f"{self.line_manager} ({self.section} Line Manager)",
            "cc": f"{ELECTRICAL_MANAGER} (Electrical Manager)",
            "attention": f"{self.technician} (On-duty Technician — {self.section})",
            "subject": subject,
            "body": body,
            "level": self.status,
        }

    def resolve(self):
        self.drifting_sensor = None
        for k in SENSOR_KEYS:
            self.drift[k] = 0.0
        self.failure_history_count += 1
        self._score(alerts=None)


def create_panels():
    """Create the panel fleet and roster a distinct technician onto each
    line for today's shift — mirrors a real daily duty assignment."""
    technicians = random.sample(TECHNICIAN_POOL, len(PANELS_CONFIG))
    return {
        cfg["id"]: Panel(cfg, technician)
        for cfg, technician in zip(PANELS_CONFIG, technicians)
    }
