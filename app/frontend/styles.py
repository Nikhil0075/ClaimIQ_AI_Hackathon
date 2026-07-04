"""CSS styling for the ClaimIQ Streamlit console."""

import streamlit as st

CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"],
[data-testid="stApp"], .stApp {
    background: #06060e !important;
    font-family: 'Inter', sans-serif !important;
    color: #e8e4f4 !important;
}
[data-testid="stHeader"], [data-testid="stToolbar"] { background: transparent !important; }
[data-testid="stSidebarCollapsedControl"] { display: none; }
footer, [data-testid="stDecoration"], [data-testid="collapsedControl"] { display: none; }
.block-container { padding: 2rem 2.5rem 4rem !important; max-width: 1380px !important; }

::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background:#0e0e1a; }
::-webkit-scrollbar-thumb { background:#3d2060; border-radius:999px; }

/* ── KEYFRAMES ── */
@keyframes pulse       { 0%,100%{opacity:1}       50%{opacity:.35} }
@keyframes blink       { 0%,100%{opacity:1}        50%{opacity:0} }
@keyframes blob-drift  { 0%,100%{transform:translate(0,0) scale(1)}
                         33%{transform:translate(30px,-20px) scale(1.06)}
                         66%{transform:translate(-20px,15px) scale(.96)} }
@keyframes shimmer     { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
@keyframes live-pulse  { 0%,100%{box-shadow:0 0 0 0 rgba(74,222,128,.6)}
                         50%{box-shadow:0 0 0 5px rgba(74,222,128,0)} }
@keyframes card-glow   { 0%,100%{opacity:.5} 50%{opacity:.9} }
@keyframes spin-slow   { to{transform:rotate(360deg)} }
@keyframes fade-up     { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:none} }

/* ── TABS ── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: rgba(14,14,26,.6) !important;
    border-radius: 16px !important;
    border: 1px solid rgba(161,66,244,.2) !important;
    padding: 6px !important; gap: 4px !important;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important; border-radius: 12px !important;
    color: #9f98b8 !important; font-weight: 600 !important;
    font-size: 14px !important; padding: 10px 20px !important;
    border: none !important; transition: all .18s ease !important;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    background: rgba(161,66,244,.12) !important; color: #e8e4f4 !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
    background: linear-gradient(135deg,rgba(161,66,244,.25),rgba(124,58,237,.2)) !important;
    color: #c084fc !important; border: 1px solid rgba(161,66,244,.35) !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display:none !important; }

/* ════════════════════════════════
   HERO BAND
   ════════════════════════════════ */
.hero-band {
    background: linear-gradient(140deg,#0e0720 0%,#060412 50%,#0a0820 100%);
    border: 1px solid rgba(161,66,244,.4);
    border-radius: 32px;
    padding: 0;
    box-shadow:
        0 0 0 1px rgba(255,255,255,.03) inset,
        0 40px 100px rgba(0,0,0,.7),
        0 0 80px rgba(120,40,220,.12);
    margin-bottom: 28px;
    position: relative; overflow: hidden;
    animation: fade-up .5s ease both;
}

/* Animated glow blobs */
.hero-blob {
    position: absolute; border-radius: 50%;
    filter: blur(80px); pointer-events: none; will-change: transform;
}
.hero-blob-1 {
    width: 520px; height: 420px; top: -120px; left: -80px;
    background: radial-gradient(circle,rgba(161,66,244,.28) 0%,transparent 70%);
    animation: blob-drift 12s ease-in-out infinite;
}
.hero-blob-2 {
    width: 380px; height: 300px; bottom: -100px; right: 80px;
    background: radial-gradient(circle,rgba(96,60,220,.22) 0%,transparent 70%);
    animation: blob-drift 16s ease-in-out infinite reverse;
}
.hero-blob-3 {
    width: 240px; height: 240px; top: 30px; right: 280px;
    background: radial-gradient(circle,rgba(192,132,252,.14) 0%,transparent 70%);
    animation: blob-drift 9s ease-in-out infinite 3s;
}

/* Subtle dot-grid overlay */
.hero-grid {
    position: absolute; inset: 0; pointer-events: none;
    background-image:
        radial-gradient(circle, rgba(161,66,244,.18) 1px, transparent 1px);
    background-size: 32px 32px;
    mask-image: radial-gradient(ellipse 80% 100% at 50% 50%,black 40%,transparent 100%);
    opacity: .5;
}

/* Shimmer top edge */
.hero-band::after {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg,
        transparent 0%, rgba(161,66,244,.6) 30%,
        rgba(192,132,252,1) 50%, rgba(161,66,244,.6) 70%, transparent 100%);
    background-size: 200% 100%;
    animation: shimmer 3s linear infinite;
}

.hero-inner {
    position: relative; z-index: 2;
    padding: 32px 40px 28px;
    display: flex; flex-direction: column; gap: 28px;
}

.hero-logo-wrap {
    background: rgba(255,255,255,.05);
    border: 1px solid rgba(255,255,255,.1);
    border-radius: 18px; padding: 12px 14px;
    backdrop-filter: blur(8px);
    box-shadow: 0 8px 24px rgba(0,0,0,.3), inset 0 1px 0 rgba(255,255,255,.08);
    flex-shrink: 0;
}

.hero-eyebrow {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(161,66,244,.12);
    border: 1px solid rgba(161,66,244,.45);
    border-radius: 999px; padding: 6px 16px;
    font-size: 11.5px; font-weight: 700; letter-spacing: .14em;
    text-transform: uppercase; color: #c084fc; margin-bottom: 16px;
}
.eyebrow-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #c084fc; box-shadow: 0 0 8px #c084fc;
    animation: pulse 1.8s ease-in-out infinite;
}
.hero-live-badge {
    background: rgba(74,222,128,.18); border: 1px solid rgba(74,222,128,.5);
    border-radius: 999px; padding: 2px 9px; font-size: 9.5px;
    color: #4ade80; letter-spacing: .18em; margin-left: 4px;
    animation: live-pulse 2s infinite;
}

.hero-title {
    font-size: 52px; font-weight: 900; line-height: 1.0;
    letter-spacing: -2px; margin: 0 0 12px;
    background: linear-gradient(110deg,#ffffff 10%,#d8b4fe 45%,#c084fc 65%,#a855f7 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
    text-shadow: none;
    filter: drop-shadow(0 0 40px rgba(168,85,247,.35));
}
.hero-sub {
    font-size: 15px; color: #9f98b8; line-height: 1.7; max-width: 600px;
    font-weight: 400;
}

/* Stat strip */
.hero-stat-strip {
    display: flex; align-items: center; gap: 0;
    background: rgba(255,255,255,.03);
    border: 1px solid rgba(161,66,244,.18);
    border-radius: 16px; overflow: hidden;
    backdrop-filter: blur(12px);
}
.hero-stat {
    flex: 1; padding: 14px 22px; text-align: center;
    transition: background .2s ease;
}
.hero-stat:hover { background: rgba(161,66,244,.08); }
.hero-stat-val {
    font-size: 18px; font-weight: 800; color: #e8e4f4; letter-spacing: -.4px;
    background: linear-gradient(135deg,#fff,#c084fc);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
}
.hero-stat-lbl {
    font-size: 10.5px; font-weight: 600; color: #6b5fa0;
    text-transform: uppercase; letter-spacing: .1em; margin-top: 3px;
}
.hero-stat-div {
    width: 1px; height: 36px; flex-shrink: 0;
    background: linear-gradient(180deg,transparent,rgba(161,66,244,.3),transparent);
}

/* ════════════════════════════════
   CONTROL CARDS
   ════════════════════════════════ */
.ctrl-card {
    background: rgba(10,10,20,.9);
    border-radius: 22px;
    padding: 22px 22px 18px;
    margin-bottom: 16px;
    position: relative; overflow: hidden;
    border: 1px solid rgba(255,255,255,.07);
    box-shadow: 0 20px 60px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.04);
    transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
    animation: fade-up .5s ease both;
}
.ctrl-card:hover {
    transform: translateY(-3px);
}

/* Per-card accent colours */
.ctrl-card-purple { border-color: rgba(161,66,244,.25); }
.ctrl-card-purple:hover { border-color: rgba(161,66,244,.5); box-shadow: 0 24px 70px rgba(0,0,0,.5), 0 0 30px rgba(161,66,244,.12); }
.ctrl-card-teal   { border-color: rgba(20,184,166,.2); }
.ctrl-card-teal:hover   { border-color: rgba(20,184,166,.45); box-shadow: 0 24px 70px rgba(0,0,0,.5), 0 0 30px rgba(20,184,166,.1); }
.ctrl-card-blue   { border-color: rgba(96,165,250,.2); }
.ctrl-card-blue:hover   { border-color: rgba(96,165,250,.45); box-shadow: 0 24px 70px rgba(0,0,0,.5), 0 0 30px rgba(96,165,250,.1); }

/* Glowing ambient light behind each card */
.ctrl-card-glow {
    position: absolute; pointer-events: none;
    width: 220px; height: 220px; border-radius: 50%;
    filter: blur(60px); top: -60px; right: -40px;
    animation: card-glow 4s ease-in-out infinite;
}
.ctrl-glow-purple { background: radial-gradient(circle,rgba(161,66,244,.25),transparent 70%); }
.ctrl-glow-teal   { background: radial-gradient(circle,rgba(20,184,166,.2),transparent 70%); }
.ctrl-glow-blue   { background: radial-gradient(circle,rgba(96,165,250,.18),transparent 70%); }

/* Coloured top bar per card */
.ctrl-card-top-bar {
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    border-radius: 22px 22px 0 0;
}
.ctrl-bar-purple { background: linear-gradient(90deg,transparent,rgba(161,66,244,.9),rgba(192,132,252,1),rgba(161,66,244,.9),transparent); }
.ctrl-bar-teal   { background: linear-gradient(90deg,transparent,rgba(20,184,166,.8),rgba(94,234,212,1),rgba(20,184,166,.8),transparent); }
.ctrl-bar-blue   { background: linear-gradient(90deg,transparent,rgba(96,165,250,.8),rgba(147,197,253,1),rgba(96,165,250,.8),transparent); }

.ctrl-card-header {
    display: flex; align-items: center; gap: 12px; margin-bottom: 10px;
}
.ctrl-icon {
    width: 38px; height: 38px; border-radius: 12px;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 17px; flex-shrink: 0;
}
.ctrl-icon-purple { background:rgba(161,66,244,.15); border:1px solid rgba(161,66,244,.3); }
.ctrl-icon-teal   { background:rgba(20,184,166,.12);  border:1px solid rgba(20,184,166,.28); }
.ctrl-icon-blue   { background:rgba(96,165,250,.12);  border:1px solid rgba(96,165,250,.28); }

.ctrl-title {
    font-size: 16px; font-weight: 800; color: #f0ecff; letter-spacing: -.3px;
}
.ctrl-card-desc {
    font-size: 12.5px; color: #6b5fa0; line-height: 1.55; margin-bottom: 6px;
    font-weight: 400;
}

/* Status badges (replaces auto-badge-on/off) */
.ctrl-status-badge {
    display: inline-flex; align-items: center; gap: 8px;
    border-radius: 999px; padding: 6px 14px;
    font-size: 12.5px; font-weight: 700; margin-top: 10px;
}
.ctrl-badge-green { background:rgba(74,222,128,.1);  border:1px solid rgba(74,222,128,.35);  color:#4ade80; }
.ctrl-badge-amber { background:rgba(250,204,21,.1);  border:1px solid rgba(250,204,21,.35);  color:#facc15; }
.ctrl-badge-off   { background:rgba(107,114,128,.08);border:1px solid rgba(107,114,128,.22); color:#6b7280; }

/* keep old badge classes working too */
.auto-badge-on  { display:inline-flex;align-items:center;gap:8px;background:rgba(74,222,128,.12);border:1px solid rgba(74,222,128,.35);border-radius:999px;padding:6px 14px;color:#4ade80;font-size:13px;font-weight:700;margin-top:12px; }
.auto-badge-off { display:inline-flex;align-items:center;gap:8px;background:rgba(107,114,128,.1);border:1px solid rgba(107,114,128,.25);border-radius:999px;padding:6px 14px;color:#9ca3af;font-size:13px;font-weight:700;margin-top:12px; }
.dot-on  { display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;box-shadow:0 0 10px #4ade8088;animation:pulse 1.4s infinite; }
.dot-off { display:inline-block;width:8px;height:8px;border-radius:50%;background:#6b7280; }

/* ── BUTTONS ── */
div.stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg,#a855f7 0%,#7c3aed 60%,#6d28d9 100%) !important;
    border: 1px solid rgba(192,132,252,.45) !important;
    border-radius: 14px !important;
    color: #fff !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 15px !important; font-weight: 800 !important;
    padding: .85rem 1.4rem !important;
    box-shadow:
        0 0 0 1px rgba(255,255,255,.08) inset,
        0 12px 36px rgba(124,58,237,.4),
        0 4px 12px rgba(0,0,0,.3) !important;
    transition: all .2s ease !important;
    letter-spacing: .01em !important;
    position: relative !important;
}
div.stButton > button::before {
    content: ''; position: absolute; inset: 0; border-radius: 14px;
    background: linear-gradient(180deg,rgba(255,255,255,.12) 0%,transparent 60%);
    pointer-events: none;
}
div.stButton > button:hover {
    background: linear-gradient(135deg,#b97cff 0%,#8b46f5 60%,#7c3aed 100%) !important;
    box-shadow:
        0 0 0 1px rgba(255,255,255,.12) inset,
        0 18px 50px rgba(161,66,244,.55),
        0 4px 16px rgba(0,0,0,.4) !important;
    transform: translateY(-2px) !important;
}
div.stButton > button:active { transform: translateY(0) !important; }
div.stButton > button:disabled {
    background: rgba(50,40,80,.6) !important;
    border-color: rgba(100,80,150,.2) !important;
    box-shadow: none !important; color: #4b4568 !important; cursor: not-allowed !important;
}

/* ── TOGGLE ── */
[data-testid="stToggle"] > label { color:#e0d8f8 !important; font-weight:600 !important; font-size:14px !important; }

/* ── LOOKER BUTTON ── */
.looker-btn {
    display: inline-flex; align-items: center; gap: 12px;
    background: linear-gradient(135deg,rgba(96,165,250,.15),rgba(147,197,253,.08));
    border: 1px solid rgba(96,165,250,.4);
    border-radius: 14px; padding: 14px 22px;
    color: #93c5fd; font-weight: 700; font-size: 15px;
    text-decoration: none; width: 100%; transition: all .2s ease;
    box-shadow: 0 8px 28px rgba(96,165,250,.12),
                inset 0 1px 0 rgba(255,255,255,.06);
    position: relative; overflow: hidden;
}
.looker-btn::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg,transparent,rgba(147,197,253,.6),transparent);
}
.looker-icon { font-size: 18px; }
.looker-btn:hover {
    background: linear-gradient(135deg,rgba(96,165,250,.25),rgba(147,197,253,.15));
    border-color: rgba(147,197,253,.65); color: #bfdbfe;
    box-shadow: 0 14px 42px rgba(96,165,250,.25),
                inset 0 1px 0 rgba(255,255,255,.1);
    transform: translateY(-2px);
}

/* ── SECTION DIVIDER ── */
.divider {
    height: 1px; margin: 28px 0;
    background: linear-gradient(90deg,transparent,rgba(161,66,244,.25),transparent);
}
.sec-header {
    font-size:17px; font-weight:800; color:#fff; letter-spacing:-.3px;
    margin:0 0 16px; display:flex; align-items:center; gap:10px;
}
.sec-header-line { flex:1; height:1px; background:linear-gradient(90deg,rgba(161,66,244,.35),transparent); }

/* ── LIVE TERMINAL ── */
.terminal-outer {
    background: #04040c; border: 1px solid rgba(161,66,244,.3); border-radius: 18px;
    overflow: hidden; box-shadow: 0 24px 64px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.03);
}
.terminal-titlebar {
    background: rgba(14,14,26,.95); border-bottom: 1px solid rgba(161,66,244,.2);
    padding: 12px 18px; display: flex; align-items: center; gap: 12px;
}
.tdot { width:12px; height:12px; border-radius:50%; display:inline-block; flex-shrink:0; }
.term-status-run { color:#facc15; font-size:11px; font-weight:700;
                   font-family:'JetBrains Mono',monospace; animation:pulse 1.4s infinite; }
.term-status-ok  { color:#4ade80; font-size:11px; font-weight:700; font-family:'JetBrains Mono',monospace; }
.terminal-body {
    padding: 16px 20px; font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 12.5px; line-height: 1.7; max-height: 540px; overflow-y: auto; color: #c8c3d8;
}
.terminal-body::-webkit-scrollbar { width:4px; }
.terminal-body::-webkit-scrollbar-thumb { background:#3d2060; border-radius:999px; }
.ll { display:flex; gap:12px; padding:1px 0; }
.ll-ts  { color:#4b4568; min-width:68px; flex-shrink:0; font-size:11px; padding-top:1px; }
.ll-tag { min-width:96px; flex-shrink:0; font-size:10.5px; font-weight:700;
          text-transform:uppercase; letter-spacing:.05em; padding-top:2px; }
.ll-txt { word-break:break-word; flex:1; }
.ll.sys .ll-txt { color:#555070; font-style:italic; }
.ll.sep .ll-txt { color:#2a1f48; letter-spacing:.15em; }
.term-cursor { display:inline-block; width:8px; height:14px; background:#a142f4;
               border-radius:2px; animation:blink .9s step-end infinite; vertical-align:middle; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
.term-empty { text-align:center; padding:60px 0; }
.term-empty-icon { font-size:36px; margin-bottom:12px; }
.term-empty-title { font-size:14px; font-weight:600; color:#4b4568; }
.term-empty-sub   { font-size:12px; color:#2d2545; margin-top:4px; }

/* ── LEGEND ── */
.term-legend {
    display:flex; gap:18px; flex-wrap:wrap; margin-top:14px; padding:12px 18px;
    background:rgba(10,10,20,.6); border-radius:12px; border:1px solid rgba(161,66,244,.12);
    align-items:center;
}
.leg-label { font-size:11px; color:#6b5fa0; font-weight:700; text-transform:uppercase;
             letter-spacing:.08em; }
.leg-item  { font-size:12px; font-weight:600; display:flex; align-items:center; gap:5px; }

/* ── EXPLAINABILITY CARDS ── */
.ex-card {
    background: rgba(10,10,22,.9); border: 1px solid rgba(161,66,244,.2);
    border-radius: 18px; padding: 22px 24px; margin-bottom: 14px;
    position: relative; overflow: hidden; transition: border-color .2s ease;
}
.ex-card:hover { border-color: rgba(161,66,244,.45); }
.ex-card-bar { position:absolute; top:0; left:0; bottom:0; width:4px; border-radius:4px 0 0 4px; opacity:.8; }
.ex-hdr { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }
.ex-name { font-size:16px; font-weight:800; color:#e8e4f4; display:flex; align-items:center; gap:10px; }
.ex-badge { font-size:11px; font-weight:700; padding:4px 12px; border-radius:999px;
            text-transform:uppercase; letter-spacing:.06em; }
.ex-section-lbl { font-size:10px; font-weight:700; text-transform:uppercase;
                  letter-spacing:.12em; margin-bottom:6px; opacity:.65; }
.ex-box {
    background: rgba(5,5,14,.8); border: 1px solid rgba(161,66,244,.12);
    border-radius: 10px; padding: 12px 14px; font-size: 12.5px; line-height: 1.65;
    color: #9f98b8; font-family: 'JetBrains Mono', ui-monospace, monospace;
    white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto;
}
.ex-box.decided { border-color:rgba(161,66,244,.22); background:rgba(161,66,244,.04); color:#c8c3d8; }
.ex-kv { display:flex; gap:10px; align-items:baseline; margin-bottom:5px; }
.ex-kv-k { font-size:11.5px; color:#6b7280; min-width:108px; flex-shrink:0; }
.ex-kv-v { font-size:13px; color:#e8e4f4; font-weight:700; }
.ex-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }

/* ── FINAL SUMMARY ── */
.fs-hero {
    background: linear-gradient(135deg,rgba(20,10,45,.98),rgba(10,8,28,.97));
    border: 1px solid rgba(161,66,244,.35); border-radius: 24px; padding: 28px 32px;
    margin-bottom: 24px; position: relative; overflow: hidden;
    box-shadow: 0 24px 70px rgba(0,0,0,.5);
}
.fs-hero::before {
    content:''; position:absolute; inset:0;
    background: radial-gradient(ellipse 80% 100% at 0% 0%,rgba(161,66,244,.15),transparent 60%);
    pointer-events:none;
}
.fs-claim-id { font-size:11px; font-weight:700; text-transform:uppercase;
               letter-spacing:.15em; color:#6b5fa0; margin-bottom:6px; }
.fs-claimant { font-size:28px; font-weight:900; color:#fff; letter-spacing:-.5px; margin-bottom:4px; }
.fs-type-pill {
    display:inline-flex; align-items:center; gap:6px;
    background:rgba(161,66,244,.15); border:1px solid rgba(161,66,244,.3);
    border-radius:999px; padding:4px 14px; font-size:12px; font-weight:700;
    color:#c084fc; text-transform:uppercase; letter-spacing:.08em;
}
.fs-amount { font-size:38px; font-weight:900; color:#c084fc; letter-spacing:-1px; line-height:1; }
.fs-amount-lbl { font-size:12px; color:#6b7280; margin-bottom:4px; }

.verdict-card {
    background:rgba(10,10,22,.9); border:1px solid rgba(161,66,244,.2);
    border-radius:18px; padding:20px 22px; position:relative; overflow:hidden; height:100%;
}
.vc-title { font-size:11px; font-weight:700; text-transform:uppercase;
            letter-spacing:.12em; color:#6b5fa0; margin-bottom:12px; }
.vc-score { font-size:34px; font-weight:900; line-height:1; margin-bottom:6px; }
.vc-label { font-size:13px; font-weight:600; color:#9f98b8; }
.vc-bar-bg { background:rgba(255,255,255,.06); border-radius:999px; height:6px; margin-top:12px; overflow:hidden; }
.vc-bar-fill { height:100%; border-radius:999px; }

.decision-banner {
    border-radius:18px; padding:22px 28px; display:flex; align-items:center; gap:20px;
    margin-bottom:20px; position:relative; overflow:hidden;
}
.decision-banner.human { background:linear-gradient(135deg,rgba(248,113,113,.1),rgba(220,38,38,.06));
                          border:1px solid rgba(248,113,113,.35); }
.decision-banner.auto  { background:linear-gradient(135deg,rgba(74,222,128,.1),rgba(16,185,129,.06));
                          border:1px solid rgba(74,222,128,.35); }
.decision-icon  { font-size:36px; flex-shrink:0; }
.decision-title { font-size:20px; font-weight:900; margin-bottom:4px; }
.decision-banner.human .decision-title { color:#f87171; }
.decision-banner.auto  .decision-title { color:#4ade80; }
.decision-desc  { font-size:13px; color:#9f98b8; line-height:1.5; }

.av-row { background:rgba(10,10,22,.85); border:1px solid rgba(161,66,244,.15);
          border-radius:14px; padding:14px 18px; margin-bottom:10px;
          display:flex; align-items:flex-start; gap:16px; }
.av-icon { font-size:20px; flex-shrink:0; margin-top:2px; }
.av-name { font-size:13px; font-weight:700; color:#e8e4f4; margin-bottom:4px; }
.av-text { font-size:12.5px; color:#8b84a8; line-height:1.55; }
.av-chips { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.avc { font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px; }
.avc-p { border:1px solid rgba(161,66,244,.25); color:#c084fc; background:rgba(161,66,244,.1); }
.avc-g { border:1px solid rgba(74,222,128,.3);  color:#4ade80; background:rgba(74,222,128,.08); }
.avc-r { border:1px solid rgba(248,113,113,.3); color:#f87171; background:rgba(248,113,113,.08); }
.avc-y { border:1px solid rgba(250,204,21,.3);  color:#facc15; background:rgba(250,204,21,.08); }
.avc-b { border:1px solid rgba(96,165,250,.3);  color:#60a5fa; background:rgba(96,165,250,.08); }

.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:24px; }
.stat-card { background:rgba(10,10,22,.9); border:1px solid rgba(161,66,244,.18);
             border-radius:14px; padding:16px 18px; }
.stat-lbl { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.1em; color:#6b5fa0; margin-bottom:6px; }
.stat-val { font-size:20px; font-weight:800; color:#e8e4f4; }
.stat-sub { font-size:11px; color:#6b7280; margin-top:3px; }

.link-btn {
    display:inline-flex; align-items:center; gap:8px; padding:10px 18px; border-radius:12px;
    font-size:13px; font-weight:700; text-decoration:none; transition:all .18s ease;
}
.link-btn-form {
    background:rgba(161,66,244,.12); border:1px solid rgba(161,66,244,.35); color:#c084fc;
}
.link-btn-form:hover { background:rgba(161,66,244,.22); color:#e0b8ff; }
.link-btn-drive {
    background:rgba(66,133,244,.1); border:1px solid rgba(66,133,244,.35); color:#7ab8ff;
}
.link-btn-drive:hover { background:rgba(66,133,244,.2); color:#a5d0ff; }

.no-run { text-align:center; padding:72px 0; }
.no-run-icon  { font-size:42px; margin-bottom:14px; }
.no-run-title { font-size:16px; font-weight:700; color:#4b4568; margin-bottom:6px; }
.no-run-sub   { font-size:13px; color:#2d2545; }
</style>
"""


def apply_styles() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
