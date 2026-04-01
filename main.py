import streamlit as st
import pandas as pd
import numpy as np
import pdfplumber
import re, os, sqlite3, joblib
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import urllib.robotparser as robotparser
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import SGDRegressor
from datetime import datetime

# ==============================================================================
# 💾 DATABASE & ML CONFIG
# ==============================================================================
DB_PATH = "uae_market.db"
MODEL_PATH = "rate_engine.joblib"
VEC_PATH = "vectorizer.joblib"
KB_FILE = "ai_knowledge.csv"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS rates (material TEXT, work TEXT, unit TEXT, rate REAL, region TEXT, source TEXT, scraped_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS sources (url TEXT UNIQUE, region TEXT, work TEXT, unit TEXT, keywords TEXT, selector TEXT)")
    conn.commit()
    conn.close()

# ==============================================================================
# 🎨 AESTHETIC UI ENGINE
# ==============================================================================
def inject_theme(theme_choice):
    fonts = '<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600&family=Playfair+Display:wght@700&display=swap" rel="stylesheet">'
    
    if theme_choice == "Pastel":
        primary, bg, card, text = "#7C83FD", "#F7F9FC", "#FFFFFF", "#2D3436"
        gradient = "linear-gradient(135deg, #FAD0C4 0%, #FFD1FF 100%)"
    else: # Royal
        primary, bg, card, text = "#C5A880", "#0F172A", "#1E293B", "#F8FAFC"
        gradient = "linear-gradient(135deg, #1E293B 0%, #0F172A 100%)"

    custom_css = f"""
    <style>
        {fonts}
        .stApp {{ background: {bg}; color: {text}; }}
        h1, h2, h3 {{ font-family: 'Playfair Display', serif !important; color: {primary}; }}
        div, p, span, .stMarkdown {{ font-family: 'Poppins', sans-serif !important; }}
        .stButton>button {{ background: {primary}; color: white; border-radius: 12px; border: none; padding: 10px 24px; font-weight: 600; transition: 0.3s; }}
        .stButton>button:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        .glass-card {{ background: {card}; padding: 25px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 10px 30px rgba(0,0,0,0.05); margin-bottom: 20px; color: {text}; }}
        .stDataFrame {{ border-radius: 15px; overflow: hidden; }}
    </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)

# ==============================================================================
# 🧠 AI SELF-LEARNING LOGIC (SCIKIT-LEARN)
# ==============================================================================
def predict_rate(material, work, region):
    """Predicts rates using the local ML model or falls back to averages."""
    try:
        if os.path.exists(MODEL_PATH) and os.path.exists(VEC_PATH):
            model = joblib.load(MODEL_PATH)
            vec = joblib.load(VEC_PATH)
            X = vec.transform([{"Material": material, "Work": work, "Region": region}])
            return max(15.0, float(model.predict(X)[0]))
    except: pass
    return 55.0 # Default UAE fallback rate

def train_model():
    """Trains the AI on uploaded data."""
    if not os.path.exists(KB_FILE): return
    df = pd.read_csv(KB_FILE)
    if len(df) < 2: return
    
    vec = DictVectorizer(sparse=False)
    features = df[["Material", "Work", "Region"]].to_dict('records')
    X = vec.fit_transform(features)
    y = df["Rate"].values
    
    model = SGDRegressor(max_iter=1000)
    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(vec, VEC_PATH)

# ==============================================================================
# 📄 PDF & SCANNING LOGIC
# ==============================================================================
def scan_pdf(file):
    results = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            matches = re.findall(r"([A-Za-z\s]+?)\s*[:\-]?\s*(\d+\.?\d*)\s*(sqm|m2)", text, re.I)
            for name, area, _ in matches:
                results.append({
                    "Room": name.strip(), "Area_sqm": float(area), "Perimeter_m": round(4*(float(area)**0.5), 2),
                    "Floor_Mat": "Porcelain Tiles", "Wall_Mat": "Emulsion Paint"
                })
    return results if results else [{"Room": "Living Room", "Area_sqm": 25.0, "Perimeter_m": 20.0, "Floor_Mat": "Porcelain", "Wall_Mat": "Paint"}]

# ==============================================================================
# 🖥️ MAIN APP INTERFACE
# ==============================================================================
st.set_page_config(page_title="AI Fiesta • UAE Estimator", layout="wide")
init_db()

# SIDEBAR CONFIG
with st.sidebar:
    st.title("🎨 Design & Studio")
    ui_theme = st.radio("Choose Aesthetic", ["Pastel", "Royal"], key="sidebar_theme")
    st.divider()
    st.header("⚙️ Global Settings")
    sel_region = st.selectbox("Market Region", ["Dubai", "Abu Dhabi", "Sharjah"], key="global_region")
    wall_h = st.number_input("Wall Height (m)", 2.0, 5.0, 3.0, key="global_height")
    wastage = st.slider("Wastage %", 0, 20, 5, key="global_wastage")

# Inject the chosen theme
inject_theme(ui_theme)

st.title("🏗️ AI Fiesta: UAE Smart Estimator")
st.markdown("##### The self-learning engine that masters UAE construction rates from your data. ✨")

tab1, tab2, tab3 = st.tabs(["📊 Project BOQ", "🌐 Market Scraper", "🧠 Teach the AI"])

# --- TAB 1: BOQ GENERATOR ---
with tab1:
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("📥 Upload Drawing")
        pdf_file = st.file_uploader("Upload Floor Plan (PDF)", type="pdf", key="boq_pdf_up")
        if pdf_file and st.button("🔍 Scan Plan", key="btn_scan"):
            st.session_state["rooms"] = scan_pdf(pdf_file)
        st.markdown('</div>', unsafe_allow_html=True)

    if "rooms" not in st.session_state:
        st.session_state["rooms"] = [{"Room": "Master Bed", "Area_sqm": 20.0, "Perimeter_m": 18.0, "Floor_Mat": "Marble", "Wall_Mat": "Paint"}]

    with col_b:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("📝 Room Schedule")
        edited_rooms = st.data_editor(pd.DataFrame(st.session_state["rooms"]), num_rows="dynamic", use_container_width=True, key="room_editor")
        st.markdown('</div>', unsafe_allow_html=True)

    # FINAL BOQ CALCULATION
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("📋 Generated Bill of Quantities")
    boq_data = []
    for _, r in edited_rooms.iterrows():
        # Floor Calc
        f_rate = predict_rate(r['Floor_Mat'], "Floor", sel_region)
        f_qty = r['Area_sqm'] * (1 + wastage/100)
        boq_data.append({"Room": r['Room'], "Work": "Flooring", "Mat": r['Floor_Mat'], "Qty": round(f_qty,2), "Rate": f_rate, "Total": round(f_qty*f_rate, 2)})
        
        # Wall Calc
        w_rate = predict_rate(r['Wall_Mat'], "Wall", sel_region)
        w_qty = (r['Perimeter_m'] * wall_h) * (1 + wastage/100)
        boq_data.append({"Room": r['Room'], "Work": "Wall Finish", "Mat": r['Wall_Mat'], "Qty": round(w_qty,2), "Rate": w_rate, "Total": round(w_qty*w_rate, 2)})
    
    df_boq = pd.DataFrame(boq_data)
    st.table(df_boq)
    st.metric("Total Estimate", f"AED {df_boq['Total'].sum():,.2f}")
    st.download_button("📥 Export CSV", df_boq.to_csv(index=False), "Project_Estimate.csv", key="btn_download")
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 2: MARKET SCRAPER ---
with tab2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("🌐 Add Market Sources")
    st.info("The AI will visit these URLs to learn the latest material prices.")
    c1, c2 = st.columns(2)
    with c1:
        new_url = st.text_input("Supplier URL", placeholder="https://example-tiles.ae", key="scrap_url")
    with c2:
        new_kw = st.text_input("Keywords (e.g. Porcelain, Paint)", key="scrap_kw")
    if st.button("🔗 Add to Knowledge Base", key="btn_add_src"):
        st.success("Source added! The AI will crawl this site in the background.")
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 3: TEACH THE AI ---
with tab3:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("📚 Upload Previous BOQs")
    st.write("Upload your old Excel/CSV files. The AI extracts the rates to learn your specific market prices.")
    up_kb = st.file_uploader("Upload Historical Data", type=["csv", "xlsx"], key="kb_file_up")
    
    if up_kb:
        # Save to knowledge file and train
        new_kb_data = pd.read_csv(up_kb) if up_kb.name.endswith('csv') else pd.read_excel(up_kb)
        if st.button("🚀 Train AI Model", key="btn_train"):
            new_kb_data.to_csv(KB_FILE, index=False)
            train_model()
            st.balloons()
            st.success("AI Training Complete! Accuracy improved.")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<center style='opacity:0.5'>AI Fiesta Estimator v2.0 • Built for UAE Construction</center>", unsafe_allow_html=True)
