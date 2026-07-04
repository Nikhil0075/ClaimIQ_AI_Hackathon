"""
ClaimIQ Streamlit Operations Console.

Run: streamlit run app/streamlit_app.py
"""

from pathlib import Path
import sys

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

st.set_page_config(
    page_title="ClaimIQ - Console",
    page_icon=":zap:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from streamlit_deploy import configure_streamlit_cloud_runtime

configure_streamlit_cloud_runtime()

from frontend.app import render_app

render_app()
