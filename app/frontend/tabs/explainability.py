"""Explainability tab."""

import streamlit as st

from frontend.explainability import render_explainability


def render_explainability_tab(latest: dict | None) -> None:
    st.markdown(
        '<p style="font-size:13px;color:#6b5fa0;margin-bottom:14px;">'
        'Execution trace - tools, agents, and orchestrator decisions</p>',
        unsafe_allow_html=True,
    )
    if latest:
        try:
            render_explainability(latest)
        except Exception as exc:
            st.error(f"Explainability error: {exc}")
    else:
        st.markdown(
            '<div class="no-run"><div class="no-run-icon">Trace</div>'
            '<div class="no-run-title">No run yet</div>'
            '<div class="no-run-sub">Run the pipeline to see the execution trace</div></div>',
            unsafe_allow_html=True,
        )
