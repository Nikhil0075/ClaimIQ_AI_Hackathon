"""Live log tab."""

import streamlit as st

from frontend.config import AGENT_COLORS, AGENTS
from frontend.terminal import render_terminal_html
from frontend.utils import lock_active


def render_live_logs_tab():
    st.markdown(
        '<p style="font-size:13px;color:#6b5fa0;margin-bottom:14px;">'
        'Real-time output streamed from the ClaimIQ pipeline</p>',
        unsafe_allow_html=True,
    )
    terminal_placeholder = st.empty()
    terminal_placeholder.markdown(
        render_terminal_html(st.session_state.live_log_lines, running=lock_active()),
        unsafe_allow_html=True,
    )
    legend = "".join(
        f'<span class="leg-item" style="color:{AGENT_COLORS[i]};">'
        f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
        f'background:{AGENT_COLORS[i]};margin-right:5px;flex-shrink:0;"></span>'
        f'{icon} {name}</span>'
        for i, (icon, name, _) in enumerate(AGENTS)
    )
    st.markdown(
        f'<div class="term-legend"><span class="leg-label">Legend</span>{legend}</div>',
        unsafe_allow_html=True,
    )
    return terminal_placeholder
