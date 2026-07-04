"""Final analysis tab."""

import streamlit as st

from frontend.summary import render_final_summary


def render_summary_tab(latest: dict | None) -> None:
    st.markdown(
        '<p style="font-size:13px;color:#6b5fa0;margin-bottom:14px;">'
        'Comprehensive analysis from all agents and the orchestrator</p>',
        unsafe_allow_html=True,
    )
    if latest:
        try:
            render_final_summary(latest)
        except Exception as exc:
            st.error(f"Analysis error: {exc}")
    else:
        st.markdown(
            '<div class="no-run"><div class="no-run-icon">Analysis</div>'
            '<div class="no-run-title">No analysis yet</div>'
            '<div class="no-run-sub">Complete a pipeline run to see the final analysis</div></div>',
            unsafe_allow_html=True,
        )
