"""
Reliability Early-Warning System — Streamlit prototype.

Same simulation/scoring engine as the ULESARB Challenge 2 brief describes
(sim.py), rendered as a Streamlit dashboard so it can be deployed the same
way as the digital twin dashboard — push to GitHub, deploy on Streamlit
Community Cloud.
"""

from datetime import datetime, timezone, timedelta
from collections import deque

import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

import sim
from sim import SENSOR_KEYS, SENSOR_META

SIM_INTERVAL_SEC = 3

st.set_page_config(
    page_title="Reliability Early-Warning System",
    page_icon="⌁",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------

COLORS = {
    "normal": "#5FA777",
    "warning": "#E8A33D",
    "critical": "#D6483F",
    "steel": "#5B8AA6",
    "bg": "#1B1E20",
    "surface": "#232729",
    "surface_raised": "#2C3133",
    "border": "#383D40",
    "text": "#ECE8E1",
    "text_muted": "#9BA3A6",
    "text_faint": "#6C7376",
}

st.markdown(f"""
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
.stApp {{ background-color: {COLORS['bg']}; }}
h1, h2, h3, .panel-name {{ font-family: 'Oswald', sans-serif; text-transform: uppercase; letter-spacing: 0.02em; }}
.mono {{ font-family: 'IBM Plex Mono', monospace; }}
.panel-card {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-left: 3px solid var(--accent, {COLORS['text_faint']});
    border-radius: 6px;
    padding: 14px 16px 6px;
    margin-bottom: 10px;
}}
.panel-name {{ font-size: 14.5px; font-weight: 500; margin: 0; color: {COLORS['text']}; }}
.panel-section {{ font-size: 11.5px; color: {COLORS['text_faint']}; margin: 2px 0 8px; }}
.status-pill {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 3px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    display: inline-block;
}}
.stat-chip {{
    background: {COLORS['surface_raised']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 8px 14px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    color: {COLORS['text_muted']};
    text-align: center;
}}
.stat-chip b {{ color: {COLORS['text']}; font-size: 15px; }}
.alert-item {{
    border-left: 3px solid {COLORS['text_faint']};
    background: {COLORS['surface_raised']};
    padding: 8px 10px;
    border-radius: 3px;
    font-size: 12px;
    margin-bottom: 8px;
}}
.alert-item.warning {{ border-left-color: {COLORS['warning']}; }}
.alert-item.critical {{ border-left-color: {COLORS['critical']}; }}
.alert-item.resolved {{ opacity: 0.4; }}
.a-title {{ font-weight: 600; display:flex; justify-content: space-between; color: {COLORS['text']};}}
.a-meta {{ font-family: 'IBM Plex Mono', monospace; color: {COLORS['text_faint']}; font-size: 10.5px; margin-top: 3px;}}
.insight-box {{
    background: {COLORS['surface_raised']};
    border: 1px solid {COLORS['border']};
    border-left: 3px solid {COLORS['steel']};
    border-radius: 4px;
    padding: 14px 16px;
    margin: 12px 0 18px;
}}
.insight-box h4 {{ color: {COLORS['steel']}; font-size: 13px; margin: 0 0 8px; text-transform: uppercase; font-family:'Oswald',sans-serif;}}
div[data-testid="stMetric"] {{ background: {COLORS['surface_raised']}; border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 8px 12px; }}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Session state / simulation tick
# --------------------------------------------------------------------------

if "panels" not in st.session_state:
    st.session_state.panels = sim.create_panels()
    st.session_state.alerts = deque(maxlen=200)
    st.session_state.interventions = deque(maxlen=200)
    st.session_state.last_tick = datetime.now(timezone.utc)

st_autorefresh(interval=SIM_INTERVAL_SEC * 1000, key="tick")

now = datetime.now(timezone.utc)
if (now - st.session_state.last_tick) >= timedelta(seconds=SIM_INTERVAL_SEC):
    for panel in st.session_state.panels.values():
        panel.step(st.session_state.alerts)
    st.session_state.last_tick = now

panels = st.session_state.panels


def gauge_figure(value, status):
    color = COLORS.get(status, COLORS["text_faint"])
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"font": {"color": COLORS["text"], "family": "IBM Plex Mono", "size": 30}},
        gauge={
            "axis": {"range": [0, 100], "visible": False},
            "bar": {"color": color, "thickness": 0.35},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "threshold": {"line": {"color": color, "width": 0}, "value": value},
        },
    ))
    fig.update_layout(
        height=120, margin=dict(l=15, r=15, t=15, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


@st.dialog("Panel Detail", width="large")
def panel_detail_dialog(panel_id):
    p = panels[panel_id]
    st.markdown(f"### {p.name}")
    st.caption(f"{p.section} · {p.failure_history_count} prior interventions on record")

    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown(f'<span class="status-pill" style="background:{COLORS[p.status]}22;color:{COLORS[p.status]}">{p.status}</span>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<span class="mono" style="font-size:22px;color:{COLORS[p.status]}">{p.risk_score}</span> <span style="color:{COLORS["text_faint"]};font-size:12px;">/ 100 risk score</span>', unsafe_allow_html=True)

    st.write("")
    cols = st.columns(3)
    for i, key in enumerate(SENSOR_KEYS):
        meta = SENSOR_META[key]
        with cols[i % 3]:
            is_active = p.drifting_sensor == key
            st.metric(
                meta["label"] + (" ⚠" if is_active else ""),
                f"{round(p.current[key], 2)} {meta['unit']}",
            )
            st.line_chart(list(p.history[key]), height=80, use_container_width=True)

    insight = p.diagnostic_insight()
    st.markdown(f"""
    <div class="insight-box">
      <h4>Technician Insight</h4>
      <p style="font-size:13.5px;">{insight['probable_cause']}</p>
      <ul style="color:{COLORS['text_muted']};font-size:13px;">
        {''.join(f'<li>{s}</li>' for s in insight['recommended_steps'])}
      </ul>
    </div>
    """, unsafe_allow_html=True)

    notes = st.text_area("Log intervention notes (fault found, action taken, parts used)", key=f"notes_{panel_id}")
    disabled = p.status == "normal"
    label = "No active fault to resolve" if disabled else "Log Intervention & Clear Alert"
    if st.button(label, disabled=disabled, type="primary", key=f"resolve_{panel_id}"):
        for a in st.session_state.alerts:
            if a["panel_id"] == panel_id and not a["resolved"]:
                a["resolved"] = True
        st.session_state.interventions.appendleft({
            "panel_id": panel_id, "panel_name": p.name,
            "notes": notes or "No notes provided.",
            "timestamp": datetime.now(timezone.utc),
        })
        p.resolve()
        st.rerun()


# --------------------------------------------------------------------------
# Top bar
# --------------------------------------------------------------------------

st.markdown("## ⌁ Reliability Early-Warning System")
st.caption("Electrical Control Panel Monitor — Dangote Cement Plant Pilot")

counts = {"normal": 0, "warning": 0, "critical": 0}
for p in panels.values():
    counts[p.status] += 1
avg_risk = round(sum(p.risk_score for p in panels.values()) / len(panels), 1)

c1, c2, c3, c4, c5 = st.columns(5)
c1.markdown(f'<div class="stat-chip"><b>{counts["normal"]}</b> Normal</div>', unsafe_allow_html=True)
c2.markdown(f'<div class="stat-chip"><b>{counts["warning"]}</b> Warning</div>', unsafe_allow_html=True)
c3.markdown(f'<div class="stat-chip"><b>{counts["critical"]}</b> Critical</div>', unsafe_allow_html=True)
c4.markdown(f'<div class="stat-chip">Avg Risk <b>{avg_risk}</b></div>', unsafe_allow_html=True)
c5.markdown(f'<div class="stat-chip">{now.strftime("%H:%M:%S")} UTC</div>', unsafe_allow_html=True)

st.write("")

# --------------------------------------------------------------------------
# Panel grid + alert rail
# --------------------------------------------------------------------------

grid_col, alert_col = st.columns([3, 1])

with grid_col:
    panel_list = list(panels.values())
    for row_start in range(0, len(panel_list), 3):
        row = panel_list[row_start:row_start + 3]
        cols = st.columns(3)
        for col, p in zip(cols, row):
            with col:
                st.markdown(f"""
                <div class="panel-card" style="--accent:{COLORS[p.status]}">
                  <p class="panel-name">{p.name}</p>
                  <p class="panel-section">{p.section}</p>
                  <span class="status-pill" style="background:{COLORS[p.status]}22;color:{COLORS[p.status]}">{p.status}</span>
                </div>
                """, unsafe_allow_html=True)
                st.plotly_chart(gauge_figure(p.risk_score, p.status), use_container_width=True, config={"displayModeBar": False}, key=f"gauge_{p.id}")
                if p.drifting_sensor:
                    st.caption(f"Watching: {p.drifting_sensor.replace('_', ' ')}")
                if st.button("View Details", key=f"btn_{p.id}", use_container_width=True):
                    panel_detail_dialog(p.id)

with alert_col:
    st.markdown("#### Alert Log")
    st.caption("Escalation feed")
    if not st.session_state.alerts:
        st.markdown(f'<p style="color:{COLORS["text_faint"]};font-size:12.5px;">No alerts yet. System nominal.</p>', unsafe_allow_html=True)
    else:
        for a in list(st.session_state.alerts)[:30]:
            resolved_cls = "resolved" if a["resolved"] else ""
            st.markdown(f"""
            <div class="alert-item {a['level']} {resolved_cls}">
              <div class="a-title"><span>{a['panel_name']}</span><span>{a['level'].upper()}</span></div>
              <div class="a-meta">{a['timestamp'].strftime('%H:%M:%S')} · risk {a['risk_score']} {'· resolved' if a['resolved'] else ''}</div>
            </div>
            """, unsafe_allow_html=True)
