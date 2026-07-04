"""Page-level layout components for the ClaimIQ console."""

import base64

import streamlit as st

from frontend.config import AUTO_INTERVAL_SEC, LOGO_PATH, LOOKER_URL
from frontend.utils import lock_active


def render_hero() -> None:
    logo_html = ""
    if LOGO_PATH.exists():
        logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
        logo_html = (
            f'<div class="hero-logo-wrap">'
            f'<img src="data:image/png;base64,{logo_b64}" '
            f'style="height:62px;object-fit:contain;">'
            f'</div>'
        )

    hero_html = (
        '<div class="hero-band">'
        '<div class="hero-blob hero-blob-1"></div>'
        '<div class="hero-blob hero-blob-2"></div>'
        '<div class="hero-blob hero-blob-3"></div>'
        '<div class="hero-grid"></div>'
        '<div class="hero-inner">'
          '<div style="display:flex;align-items:center;gap:26px;position:relative;z-index:2;">'
            + logo_html +
            '<div>'
              '<div class="hero-eyebrow">'
                '<span class="eyebrow-dot"></span>&#x26A1;&nbsp; AI Claims Pipeline'
                '<span class="hero-live-badge">LIVE</span>'
              '</div>'
              '<div class="hero-title">ClaimIQ</div>'
              '<div class="hero-sub">'
                'Intelligent insurance claims processing &mdash; intake, coverage, fraud detection,'
                ' triage, and automated reporting. Fully orchestrated end-to-end.'
              '</div>'
            '</div>'
          '</div>'
          '<div class="hero-stat-strip">'
            '<div class="hero-stat"><div class="hero-stat-val">5</div><div class="hero-stat-lbl">AI Agents</div></div>'
            '<div class="hero-stat-div"></div>'
            '<div class="hero-stat"><div class="hero-stat-val">Real-time</div><div class="hero-stat-lbl">Processing</div></div>'
            '<div class="hero-stat-div"></div>'
            '<div class="hero-stat"><div class="hero-stat-val">Drive</div><div class="hero-stat-lbl">Auto Upload</div></div>'
            '<div class="hero-stat-div"></div>'
            '<div class="hero-stat"><div class="hero-stat-val">BigQuery</div><div class="hero-stat-lbl">Analytics</div></div>'
          '</div>'
        '</div>'
        '</div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)


def initialise_session_state() -> None:
    if "auto_mode" not in st.session_state:
        st.session_state.auto_mode = False
    if "trigger_run" not in st.session_state:
        st.session_state.trigger_run = False
    if "live_log_lines" not in st.session_state:
        st.session_state.live_log_lines = []


def render_controls() -> None:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        <div class="ctrl-card ctrl-card-purple">
          <div class="ctrl-card-glow ctrl-glow-purple"></div>
          <div class="ctrl-card-top-bar ctrl-bar-purple"></div>
          <div class="ctrl-card-header">
            <span class="ctrl-icon ctrl-icon-purple">&#x26A1;</span>
            <span class="ctrl-title">Manual Run</span>
          </div>
          <div class="ctrl-card-desc">Trigger the full 5-agent pipeline immediately on any queued email.</div>
        </div>
        """, unsafe_allow_html=True)
        running = lock_active()
        if st.button("▶  Run Pipeline Now", disabled=running, use_container_width=True, key="run_btn"):
            st.session_state.trigger_run = True
            st.rerun()
        if running:
            st.markdown(
                '<div class="ctrl-status-badge ctrl-badge-amber">'
                '<span class="dot-on"></span>Pipeline running…</div>',
                unsafe_allow_html=True,
            )

    with col2:
        st.markdown("""
        <div class="ctrl-card ctrl-card-teal">
          <div class="ctrl-card-glow ctrl-glow-teal"></div>
          <div class="ctrl-card-top-bar ctrl-bar-teal"></div>
          <div class="ctrl-card-header">
            <span class="ctrl-icon ctrl-icon-teal">&#x1F504;</span>
            <span class="ctrl-title">Auto Mode</span>
          </div>
          <div class="ctrl-card-desc">Continuously poll Gmail and auto-process every incoming claim.</div>
        </div>
        """, unsafe_allow_html=True)
        st.session_state.auto_mode = st.toggle(
            f"Poll every {AUTO_INTERVAL_SEC}s", value=st.session_state.auto_mode
        )
        badge_class = "ctrl-status-badge ctrl-badge-green" if st.session_state.auto_mode else "ctrl-status-badge ctrl-badge-off"
        dot_class   = "dot-on" if st.session_state.auto_mode else "dot-off"
        label       = "Auto polling active" if st.session_state.auto_mode else "Auto polling off"
        st.markdown(
            f'<div class="{badge_class}"><span class="{dot_class}"></span>{label}</div>',
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown("""
        <div class="ctrl-card ctrl-card-blue">
          <div class="ctrl-card-glow ctrl-glow-blue"></div>
          <div class="ctrl-card-top-bar ctrl-bar-blue"></div>
          <div class="ctrl-card-header">
            <span class="ctrl-icon ctrl-icon-blue">&#x1F4CA;</span>
            <span class="ctrl-title">Analytics</span>
          </div>
          <div class="ctrl-card-desc">Open the Looker Studio dashboard for live claims analytics.</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(
            f'<a class="looker-btn" href="{LOOKER_URL}" target="_blank" rel="noopener">'
            f'<span class="looker-icon">&#x1F517;</span>'
            f'Open Looker Dashboard</a>',
            unsafe_allow_html=True,
        )
