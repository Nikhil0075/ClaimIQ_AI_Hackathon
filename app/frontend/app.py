"""Application composition for the ClaimIQ Streamlit console."""

import time

import streamlit as st

from frontend.config import AUTO_INTERVAL_SEC
from frontend.layout import initialise_session_state, render_controls, render_hero
from frontend.runner import run_claimiq_streaming
from frontend.styles import apply_styles
from frontend.tabs import render_explainability_tab, render_live_logs_tab, render_summary_tab
from frontend.terminal import rebuild_live_log
from frontend.utils import load_logs, lock_active


def render_app() -> None:
    apply_styles()
    initialise_session_state()
    render_hero()
    render_controls()

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    tab_logs, tab_explain, tab_summary = st.tabs([
        "Live Logs",
        "Explainability",
        "Final Analysis",
    ])

    logs = load_logs()
    latest = logs[0] if logs else None

    if not st.session_state.live_log_lines and latest:
        st.session_state.live_log_lines = rebuild_live_log(latest)

    with tab_logs:
        terminal_placeholder = render_live_logs_tab()

    with tab_explain:
        render_explainability_tab(latest)

    with tab_summary:
        render_summary_tab(latest)

    if st.session_state.get("trigger_run"):
        st.session_state.trigger_run = False
        result = run_claimiq_streaming(terminal_placeholder)
        if result:
            st.rerun()

    elif st.session_state.auto_mode and not lock_active():
        time.sleep(AUTO_INTERVAL_SEC)
        result = run_claimiq_streaming(terminal_placeholder, mode="auto")
        if result:
            st.rerun()
