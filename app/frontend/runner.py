"""Streaming execution wrapper for the ClaimIQ backend pipeline."""

import os
import subprocess
import sys
from datetime import datetime

import streamlit as st

from frontend.config import RUN_PY_PATH
from frontend.terminal import render_terminal_html
from frontend.utils import (
    _ansi,
    _ts_from_line,
    acquire_lock,
    add_log,
    detect_agent_live,
    parse_run_summary,
    release_lock,
)

def run_claimiq_streaming(terminal_placeholder, mode: str = "manual") -> dict | None:
    started = datetime.now()

    if not acquire_lock():
        return None

    if not RUN_PY_PATH.exists():
        release_lock()
        st.error(f"❌  run.py not found at {RUN_PY_PATH}")
        return None

    stdout_lines: list[str] = []
    live_lines:   list[tuple] = []
    current_agent = 0

    proc = subprocess.Popen(
        [sys.executable, str(RUN_PY_PATH)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=RUN_PY_PATH.parent,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    )

    try:
        for raw in proc.stdout:
            stdout_lines.append(raw)
            line_clean = _ansi(raw).strip()
            if not line_clean:
                continue
            ts = _ts_from_line(line_clean)
            current_agent = detect_agent_live(raw, current_agent)
            live_lines.append((ts, current_agent, raw))
            st.session_state.live_log_lines = live_lines[:]
            terminal_placeholder.markdown(
                render_terminal_html(live_lines, running=True),
                unsafe_allow_html=True,
            )
    finally:
        proc.wait()
        release_lock()

    full_stdout = "".join(stdout_lines)
    summary     = parse_run_summary(full_stdout)
    duration    = round((datetime.now() - started).total_seconds(), 2)
    status      = "success" if proc.returncode == 0 else "failed"

    entry = {
        "time":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode":         mode,
        "status":       status,
        "duration_sec": duration,
        "summary":      summary,
        "stdout":       full_stdout,
    }

    add_log(entry)

    st.session_state.live_log_lines = live_lines[:]
    terminal_placeholder.markdown(
        render_terminal_html(live_lines, running=False),
        unsafe_allow_html=True,
    )

    return entry
