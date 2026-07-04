# Reliability Early-Warning System — Streamlit Prototype

Same predictive maintenance concept as the ULESARB Challenge 2 brief,
rebuilt on Streamlit so it deploys the same way as the digital twin
dashboard — push to GitHub, deploy on **Streamlit Community Cloud**.

Simulates cement-plant electrical control panel telemetry, scores each
panel with a per-panel `IsolationForest` anomaly model, computes a
composite risk score, escalates through a tiered alert system, and
surfaces a technician insight portal for fault diagnosis and intervention
logging.

## Project structure

```
streamlit-predictive-maintenance/
├── app.py                    # Streamlit UI: layout, gauges, alert rail, detail dialog
├── sim.py                    # Simulation + anomaly detection + risk scoring engine
├── requirements.txt
└── .streamlit/
    └── config.toml            # dark industrial theme
```

`sim.py` is framework-agnostic — it's the same scoring/alerting logic as
the earlier Flask build, just decoupled from any web framework so `app.py`
can call `panel.step(...)` on every refresh tick.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`). The page
auto-refreshes every 3 seconds via `streamlit-autorefresh`, advancing the
simulation live — leave it running a minute to watch panels drift into
Warning/Critical. Click **View Details** on any panel for sensor tiles,
history sparklines, the technician insight portal, and to log a resolving
intervention.

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repo (same flow as the digital twin app).
2. Go to **share.streamlit.io → New app**, connect the repo, and set:
   - Main file path: `app.py`
3. Deploy. `requirements.txt` and `.streamlit/config.toml` are picked up
   automatically — no extra config needed.

## Notes

- **State is per-session and in-memory** — Streamlit reruns the script on
  every interaction, so panel/alert state lives in `st.session_state` and
  resets if the browser tab is closed or the app reboots. For a real pilot,
  back this with a database (Postgres works well on Streamlit Cloud via
  `st.connection`) so history survives restarts and is shared across users.
- **Single-session simulation:** each browser session ticks its own copy
  of the simulation. For a shared, always-on plant view across multiple
  viewers, move the simulation loop server-side (e.g. a small background
  worker writing to a shared DB) and have `app.py` just read from it —
  the same pattern as decoupling the digital twin's physics/backend from
  its Streamlit front end.
- **Swapping in real sensors:** replace `Panel.step()`'s random-walk
  telemetry with real readings pushed from your IoT gateway; the
  IsolationForest scoring, risk formula, and alert/insight logic downstream
  don't need to change.
