import streamlit as st

st.set_page_config(page_title="PowerFlow", page_icon="⚡", layout="centered")

pg = st.navigation([
    st.Page("pages/1_Ingest_PDF.py", title="Ingest PDF", icon="📄"),
    st.Page("pages/3_Weekly_Brief.py", title="Weekly Brief", icon="📅"),
    st.Page("pages/4_Monthly_Brief.py", title="Monthly Brief", icon="📆"),
    st.Page("pages/5_Recalibrate_Scores.py", title="Recalibrate Scores", icon="🎯"),
])
pg.run()
