# ClaimIQ Streamlit Frontend

`app/streamlit_app.py` is now only the Streamlit bootstrap. The UI code lives here, grouped by responsibility.

- `app.py` composes the page, controls, tabs, and run triggers.
- `config.py` stores paths, constants, agent labels, and dashboard settings.
- `styles.py` owns the CSS injected into Streamlit.
- `layout.py` renders the hero, controls, and session-state setup.
- `utils.py` contains log storage, summary parsing, stage detection, and lock helpers.
- `terminal.py` renders and rebuilds the live terminal view.
- `runner.py` streams `app/run.py` output into the UI.
- `explainability.py` parses and renders the execution timeline.
- `summary.py` renders the final claim analysis.
- `tabs/` contains one module per visible tab.
