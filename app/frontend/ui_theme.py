"""Shared visual styling for the Streamlit dashboard UI."""

import streamlit as st


def inject_dashboard_css() -> None:
    """Apply lightweight dashboard styling without changing application behavior."""
    st.markdown(
        """
        <style>
        :root {
            --oa-bg: #f5f7fb;
            --oa-surface: #ffffff;
            --oa-border: #e4e9f2;
            --oa-text: #1f2937;
            --oa-muted: #6b7280;
            --oa-sidebar: #172033;
            --oa-sidebar-2: #101827;
            --oa-green: #1f9d63;
            --oa-blue: #3377d6;
        }

        .stApp {
            background: var(--oa-bg);
        }

        .block-container {
            max-width: 1500px;
            padding-top: 1.4rem;
            padding-bottom: 2rem;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, var(--oa-sidebar) 0%, var(--oa-sidebar-2) 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.06);
        }

        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span {
            color: #eef2f7;
        }

        section[data-testid="stSidebar"] .stButton > button {
            width: 100%;
            justify-content: flex-start;
            min-height: 2.65rem;
            border-radius: 10px;
            border: 1px solid transparent;
            font-weight: 600;
        }

        section[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
            background: transparent;
            color: #cfd8e6;
        }

        section[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
            background: rgba(255, 255, 255, 0.08);
            color: #ffffff;
        }

        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: #2c3c57;
            color: #ffffff;
            border-color: rgba(255, 255, 255, 0.08);
        }

        div[data-testid="stChatMessage"] {
            background: var(--oa-surface);
            border: 1px solid var(--oa-border);
            border-radius: 14px;
            padding: 0.8rem 0.95rem;
            box-shadow: 0 4px 18px rgba(31, 41, 55, 0.035);
        }

        div[data-testid="stChatInput"] {
            border-radius: 12px;
        }

        .oa-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1.2rem;
        }

        .oa-header h1 {
            font-size: 1.45rem;
            margin: 0;
            color: var(--oa-text);
        }

        .oa-header .oa-subtitle {
            color: var(--oa-muted);
            font-size: 0.88rem;
            margin-top: 0.15rem;
        }

        .oa-status {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.4rem 0.7rem;
            font-size: 0.78rem;
            font-weight: 700;
            white-space: nowrap;
        }

        .oa-status.ok {
            color: #16734a;
            background: #e9f8f0;
            border: 1px solid #bfe8d1;
        }

        .oa-status.off {
            color: #a33a3a;
            background: #fff0f0;
            border: 1px solid #f4caca;
        }

        .oa-panel-title {
            font-size: 0.92rem;
            font-weight: 800;
            color: var(--oa-text);
            margin-bottom: 0.55rem;
        }

        .oa-card {
            background: var(--oa-surface);
            border: 1px solid var(--oa-border);
            border-radius: 14px;
            padding: 0.85rem 0.95rem;
            margin-bottom: 0.75rem;
            box-shadow: 0 4px 18px rgba(31, 41, 55, 0.035);
        }

        .oa-card-title {
            font-weight: 800;
            color: var(--oa-text);
            margin-bottom: 0.15rem;
        }

        .oa-card-meta {
            font-size: 0.80rem;
            color: var(--oa-muted);
            line-height: 1.45;
        }

        .oa-event-summary {
            border-left: 4px solid var(--oa-green);
        }

        .oa-empty {
            color: var(--oa-muted);
            font-size: 0.86rem;
            padding: 0.55rem 0;
        }

        .oa-sidebar-brand {
            padding: 0.3rem 0 1rem 0;
        }

        .oa-sidebar-brand strong {
            font-size: 1.15rem;
            color: #ffffff;
        }

        .oa-sidebar-brand div {
            font-size: 0.75rem;
            color: #91a0b5;
            margin-top: 0.15rem;
        }

        .oa-section-spacer {
            height: 0.35rem;
        }

        @media (max-width: 1050px) {
            .oa-header {
                align-items: flex-start;
                flex-direction: column;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
