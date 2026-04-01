import streamlit as st
import pandas as pd
import numpy as np
import pdfplumber
import re, os, time, sqlite3, joblib
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import urllib.robotparser as robotparser
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import SGDRegressor
from datetime import datetime

# =========================
# Config & Storage
# =========================
DB_PATH = "market_rates.db"
MODEL_PATH = "rate_model.joblib"
VEC_PATH = "dv.joblib"
UPLOAD_KB = "knowledge.csv"  # user-uploaded historical BOQs

# =========================
# DB Helpers
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        material TEXT,
        work TEXT,
        unit TEXT,
        rate REAL,
        region TEXT,
        source TEXT,
        scraped_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        region TEXT,
        work TEXT,
        unit TEXT,
        material_keywords TEXT,
        selector TEXT
    )""")
    conn.commit()
    conn.close()

def add_source(url, region, work, unit, material_keywords, selector):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO sources(url, region, work, unit, material_keywords, selector) VALUES (?,?,?,?,?,?)",
                  (url.strip(), region.strip(), work.strip(), unit.strip(), material_keywords.strip(), selector.strip()))
        conn.commit()
    finally:
        conn.close()

def get_sources():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM sources", conn)
    conn.close()
    return df

def store_rates(rows):
    if not rows:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for r in rows:
        c.execute("""INSERT INTO rates(material, work, unit, rate, region, source, scraped_at)
                     VALUES (?,?,?,?,?,?,?)""",
                  (r["material"], r["work"], r["unit"], float(r["rate"]), r["region"], r["source"], r["scraped_at"]))
    conn.commit()
    conn.close()

def load_rates_df(limit_days=365):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM rates", conn)
    conn.close()
    if not df.empty:
        # Keep recent year by default
        df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")
        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=limit_days)
        df = df[df["scraped_at"] >= cutoff]
    return df

# =========================
# Scraping (Free Sources)
# =========================
PRICE_PATTERNS = [
    r"AED\s*([\d,]+\.?\d*)\s*/\s*(sqm|m2|m²)",
    r"([\d,]+\.?\d*)\s*AED\s*/\s*(sqm|m2|m²)",
    r"AED\s*([\d,]+\.?\d*)",  # fallback if unit missing on the page
]

def robots_allowed(url):
    try:
        parsed = urlparse(url)
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch("*", url)
    except:
        return False

def classify_material(text, keyword_line):
    # Material classification using user-provided keywords (comma-separated)
    base = text.lower()
    for kw in [k.strip().lower() for k in keyword_line.split(",") if k.strip()]:
        if kw in base:
            return kw.title()
    # Default fallbacks
    if "porcelain" in base: return "Porcelain Tiles"
    if "ceramic" in base: return "Ceramic Tiles"
    if "marble" in base: return "Marble"
    if "vinyl" in base: return "Vinyl"
    if "paint" in base or "emulsion" in base: return "Emulsion Paint"
    return "Generic Material"

def scrape_source_row(src_row):
    url = src_row["url"]
    if not robots_allowed(url):
        return []
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text(" ", strip=True)

        # If selector provided, prefer it
        if src_row["selector"]:
            elems = soup.select(src_row["selector"])
            text = " ".join([e.get_text(" ", strip=True) for e in elems]) or text

        found = []
        for pat in PRICE_PATTERNS:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                price = m.group(1).replace(",", "")
                unit = m.group(2).lower() if len(m.groups()) >= 2 and m.group(2) else src_row["unit"].lower()
                try:
                    rate = float(price)
                except:
                    continue
                material = classify_material(text, src_row["material_keywords"])
                found.append({
                    "material": material,
                    "work": src_row["work"].title(),
                    "unit": unit if unit in ["sqm", "m2", "m²"] else src_row["unit"],
                    "rate": rate,
                    "region": src_row["region"],
                    "source": url,
                    "scraped_at": datetime.utcnow().isoformat()
                })
        # Deduplicate by (material, work, unit, rate)
        unique = {(f['material'], f['work'], f['unit'], f['rate']): f for f in found}.values()
        return list(unique)
    except Exception:
        return []

def scrape_all_sources():
    df = get_sources()
    all_rows = []
    for _, row in df.iterrows():
        rows = scrape_source_row(row)
        all_rows.extend(rows)
    store_rates(all_rows)
    return all_rows

# =========================
# Self-Learning (Online ML)
# =========================
def load_kb():
    if os.path.exists(UPLOAD_KB):
        return pd.read_csv(UPLOAD_KB)
    # Seed defaults
    return pd.DataFrame([
        {"Material": "Ceramic Tiles", "Work": "Floor", "Rate": 45.0, "Region": "Dubai"},
        {"Material": "Porcelain Tiles", "Work": "Floor", "Rate": 65.0, "Region": "Dubai"},
        {"Material": "Emulsion Paint", "Work": "Wall", "Rate": 18.0, "Region": "Dubai"},
        {"Material": "Marble", "Work": "Floor", "Rate": 150.0, "Region": "Dubai"},
        {"Material": "Vinyl", "Work": "Floor", "Rate": 40.0, "Region": "Dubai"},
    ])

def save_kb(df):
    df.to_csv(UPLOAD_KB, index=False)

def fit_or_update_model(train_df):
    # Features: material, work, region
    if train_df.empty:
        return None, None
    feats = train_df[["Material", "Work", "Region"]].astype(str).to_dict(orient="records")
    y = train_df["Rate"].astype(float).values

    if os.path.exists(MODEL_PATH) and os.path.exists(VEC_PATH):
        dv = joblib.load(VEC_PATH)
        X = dv.transform(feats)
        model = joblib.load(MODEL_PATH)
        model.partial_fit(X, y)  # online update
    else:
        dv = DictVectorizer(sparse=True)
        X = dv.fit_transform(feats)
        model = SGDRegressor(random_state=42, max_iter=1000, tol=1e-3)
        model.fit(X, y)
    joblib.dump(dv, VEC_PATH)
    joblib.dump(model, MODEL_PATH)
    return model, dv

def predict_rate(material, work, region):
    # Try model, then fall back to medians
    if os.path.exists(MODEL_PATH) and os.path.exists(VEC_PATH):
        dv = joblib.load(VEC_PATH)
        model = joblib.load(MODEL_PATH)
        X = dv.transform([{"Material": material, "Work": work, "Region": region}])
        try:
            pred = float(model.predict(X)[0])
            if pred > 5:
                return pred
        except:
            pass
    # Fallback to recent scraped medians
    rates = load_rates_df()
    if not rates.empty:
        subset = rates[(rates["material"] == material) & (rates["work"] == work) & (rates["region"] == region)]
        if subset.empty:
            subset = rates[(rates["material"] == material) & (rates["work"] == work)]
        if not subset.empty:
            return float(subset["rate"].median())
    # Final fallback to KB defaults
    kb = load_kb()
    subset = kb[(kb["Material"] == material) & (kb["Work"] == work) & (kb["Region"] == region)]
    if subset.empty:
        subset = kb[(kb["Material"] == material) & (kb["Work"] == work)]
    return float(subset["Rate"].mean() if not subset.empty else 50.0)

# =========================
# PDF Analyzer (Local)
# =========================
def analyze_pdf_rooms(pdf_file):
    results = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            matches = re.findall(r"([A-Za-z\s]+?)\s*[:\-]?\s*(\d+\.?\d*)\s*(sqm|m2|m²)", text, flags=re.IGNORECASE)
            for name, area, _ in matches:
                area_val = float(area)
                perim_est = round(4 * (area_val**0.5), 2)
                fname = name.strip()
                # Simple local material inference
                nlow = fname.lower()
                if any(k in nlow for k in ["bath", "toilet", "wc", "wash"]):
                    fmat, wmat = "Ceramic Tiles", "Moisture-Resistant Paint"
                elif any(k in nlow for k in ["kitchen", "pantry"]):
                    fmat, wmat = "Porcelain Tiles", "Washable Paint"
                elif any(k in nlow for k in ["balcony", "terrace"]):
                    fmat, wmat = "Outdoor Tiles", "Weather-Proof Paint"
                else:
                    fmat, wmat = "Porcelain Tiles", "Emulsion Paint"
                results.append({
                    "Room": fname,
                    "Area_sqm": area_val,
                    "Perimeter_m": perim_est,
                    "Floor_Material": fmat,
                    "Wall_Material": wmat
                })
    if not results:
        results = [{"Room": "New Room", "Area_sqm": 0.0, "Perimeter_m": 0.0, "Floor_Material": "Porcelain Tiles", "Wall_Material": "Emulsion Paint"}]
    return results

# =========================
# UI: Themes & Styles
# =========================
def inject_theme(theme="Pastel"):
    fonts = """
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;500;700&family=Playfair+Display:wght@500;700&display=swap" rel="stylesheet">
    """
    if theme == "Pastel":
        # Lavender / Mint / Peach
        css = """
        <style>
        :root {
          --bg1: #F7F5FF; --bg2:#F0FFF9;
          --card:#FFFFFFDD; --text:#2A2A2A; --muted:#6b7280;
          --accent:#7C83FD; --accent2:#6EE7B7;
          --btn:#7C83FD; --btn-text:#ffffff;
        }
        .stApp { background: linear-gradient(135deg,var(--bg1),var(--bg2)); }
        h1, h2, h3 { font-family: 'Playfair Display', serif; color: var(--text);}
        .stMarkdown, p, span, div { font-family:'Poppins', sans-serif; color: var(--text);}
        .the-card { background: var(--card); backdrop-filter: blur(8px); border-radius:16px; padding:18px 20px; border:1px solid #e6e6e6; box-shadow:0 10px 30px rgba(0,0,0,0.06); }
        .section-title { font-size: 1.1rem; color: var(--muted); margin-top: 6px; }
        .stButton>button { background: var(--btn); color: var(--btn-text); border-radius:12px; padding:10px 16px; border:none; font-weight:600; }
        .stDownloadButton>button { border-radius:12px; font-weight:600; }
        hr { border-color:#eaeaea; }
        </style>
        """
    else:
        # Royal: Deep Navy / Gold / Burgundy
        css = """
        <style>
        :root {
          --bg1:#0F172A; --bg2:#111827;
          --card:#0B1220CC; --text:#E5E7EB; --muted:#9CA3AF;
          --accent:#C5A880; --accent2:#B91C1C;
          --btn:#C5A880; --btn-text:#111827;
        }
        .stApp { background: radial-gradient(circle at 10% 10%, #1f2937 0%, var(--bg2) 60%); }
        h1, h2, h3 { font-family: 'Playfair Display', serif; color: var(--text);}
        .stMarkdown, p, span, div { font-family:'Poppins', sans-serif; color: var(--text);}
        .the-card { background: var(--card); backdrop-filter: blur(10px); border-radius:18px; padding:20px 22px; border:1px solid #1f2937; box-shadow:0 16px 40px rgba(0,0,0,0.4); }
        .section-title { font-size: 1.1rem; color: var(--muted); margin-top: 6px; }
        .stButton>button { background: var(--btn); color: var(--btn-text); border-radius:14px; padding:10px 18px; border:none; font-weight:700; }
        .stDownloadButton>button { border-radius:14px; font-weight:700; }
        hr { border-color:#374151; }
        </style>
        """
    st.markdown(fonts + css, unsafe_allow_html=True)

# =========================
# App
# =========================
st.set_page_config(page_title="UAE Estimator • Self-Learning", layout="wide")
init_db()

# Sidebar
with st.sidebar:
    theme = st.radio("🎨 Theme", ["Pastel", "Royal"], index=0)
    inject_theme(theme)
    st.markdown("### ⚙️ Settings")
    region = st.selectbox("🏙️ Region", ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "RAK", "UAQ", "Fujairah"], index=0)
    wall_h = st.number_input("📏 Wall Height (m)", 2.0, 6.0, 3.0)
    wastage = st.slider("📉 Wastage (%)", 0, 20, 5)
    st.markdown("---")
    st.caption("Tip: Add supplier URLs in Live Market to auto-learn rates.")

st.title("🏗️ AI Estimator UAE — Self‑Learning, Beautiful, and Free")

tab1, tab2, tab3, tab4 = st.tabs([
    "📄 Rooms & BOQ",
    "🌐 Live Market (Free Sources)",
    "📚 Teach the AI (Uploads)",
    "📈 Model & Rates"
])

# -------------------- TAB 1: Rooms & BOQ --------------------
with tab1:
    st.markdown("#### 🧭 Analyze a PDF plan or enter rooms manually")
    c1, c2 = st.columns([1,2])
    with c1:
        up_pdf = st.file_uploader("📥 Upload Plan (PDF)", type=["pdf"])
        if up_pdf and st.button("🔍 Extract Rooms from PDF"):
            with st.spinner("Reading PDF for room names & areas..."):
                st.session_state["rooms"] = analyze_pdf_rooms(up_pdf)

    # If no rooms yet, seed one row
    if "rooms" not in st.session_state:
        st.session_state["rooms"] = [{"Room":"Living Room","Area_sqm":25.0,"Perimeter_m":20.0,
                                      "Floor_Material":"Porcelain Tiles","Wall_Material":"Emulsion Paint"}]

    with c2:
        st.markdown("<div class='the-card'>", unsafe_allow_html=True)
        st.markdown("### 📝 Project Rooms (Editable)")
        rooms_df = st.data_editor(pd.DataFrame(st.session_state["rooms"]), num_rows="dynamic", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='the-card'>", unsafe_allow_html=True)
    st.markdown("### 📊 BOQ with Self‑Learning Rates")
    boq = []
    for _, r in rooms_df.iterrows():
        # Flooring
        frate = predict_rate(str(r["Floor_Material"]), "Floor", region)
        fqty = float(r["Area_sqm"])
        boq.append({
            "Room": r["Room"], "Work":"Flooring", "Material": r["Floor_Material"],
            "Qty": round(fqty*(1+wastage/100),2), "Unit":"sqm",
            "Rate (AED/sqm)": round(frate,2), "Amount (AED)": round(fqty*frate*(1+wastage/100),2)
        })
        # Walls
        wqty = float(r["Perimeter_m"])*wall_h
        wrate = predict_rate(str(r["Wall_Material"]), "Wall", region)
        boq.append({
            "Room": r["Room"], "Work":"Wall Finish", "Material": r["Wall_Material"],
            "Qty": round(wqty*(1+wastage/100),2), "Unit":"sqm",
            "Rate (AED/sqm)": round(wrate,2), "Amount (AED)": round(wqty*wrate*(1+wastage/100),2)
        })
    boq_df = pd.DataFrame(boq)
    st.dataframe(boq_df, use_container_width=True)
    st.metric("💰 Project Total", f"AED {boq_df['Amount (AED)'].sum():,.2f}")
    st.download_button("📥 Download BOQ (CSV)", boq_df.to_csv(index=False).encode("utf-8"),
                       "BOQ_UAE_AI.csv", "text/csv")
    st.markdown("</div>", unsafe_allow_html=True)

# -------------------- TAB 2: Live Market --------------------
with tab2:
    st.markdown("#### 🌐 Add free public sources (that allow scraping). The AI learns every time.")
    with st.expander("➕ Add Source"):
        url = st.text_input("🔗 URL")
        scol1, scol2, scol3 = st.columns(3)
        with scol1:
            s_region = st.selectbox("🏙️ Region", ["Dubai","Abu Dhabi","Sharjah","Ajman","RAK","UAQ","Fujairah"])
        with scol2:
            s_work = st.selectbox("🧱 Work Type", ["Floor","Wall"])
        with scol3:
            s_unit = st.selectbox("📐 Unit", ["sqm","m2","m²"])
        mat_kw = st.text_input("🔎 Material keywords (comma-separated)", help="e.g. porcelain, ceramic, marble, paint")
        selector = st.text_input("🧩 Optional CSS selector", help=".price, #rates etc.")
        if st.button("💾 Save Source"):
            if url:
                add_source(url, s_region, s_work, s_unit, mat_kw, selector)
                st.success("Source saved!")

    src_df = get_sources()
    st.markdown("<div class='the-card'>", unsafe_allow_html=True)
    st.markdown("### 📚 Current Sources")
    st.dataframe(src_df, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("🔄 Fetch Latest Prices"):
        with st.spinner("Collecting rates (respecting robots.txt)..."):
            new_rows = scrape_all_sources()
        if new_rows:
            st.success(f"✅ Stored {len(new_rows)} fresh price points.")
        else:
            st.info("No rates found. Try adding CSS selector or different sources.")

    rates_now = load_rates_df()
    if not rates_now.empty:
        st.markdown("<div class='the-card'>", unsafe_allow_html=True)
        st.markdown("### 🧾 Recent Market Rates")
        show = rates_now.sort_values("scraped_at", ascending=False).head(100)
        st.dataframe(show, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

# -------------------- TAB 3: Teach the AI --------------------
with tab3:
    st.markdown("#### 📤 Upload your BOQs to teach the AI (Material, Work, Rate, Region columns)")
    up = st.file_uploader("Upload CSV/XLSX", type=["csv","xlsx"])
    if up:
        try:
            df = pd.read_csv(up) if up.name.endswith(".csv") else pd.read_excel(up)
            st.dataframe(df.head(), use_container_width=True)
            # Keep only required columns
            needed = ["Material","Work","Rate","Region"]
            if not all(c in df.columns for c in needed):
                st.warning("Your file must include: Material, Work, Rate, Region")
            else:
                kb = load_kb()
                kb = pd.concat([kb, df[needed]], ignore_index=True)
                save_kb(kb)
                model, dv = fit_or_update_model(kb)
                st.success("✅ AI updated from your data.")
        except Exception as e:
            st.error(f"Upload failed: {e}")

    st.markdown("<div class='the-card'>", unsafe_allow_html=True)
    st.markdown("### 🧠 Current Knowledge Base (last 20)")
    st.dataframe(load_kb().tail(20), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# -------------------- TAB 4: Model & Rates --------------------
with tab4:
    st.markdown("#### 🔮 Test AI predictions")
    left, right = st.columns(2)
    with left:
        m = st.selectbox("🧱 Material", ["Ceramic Tiles","Porcelain Tiles","Marble","Vinyl","Emulsion Paint","Generic Material"])
        w = st.selectbox("🛠️ Work", ["Floor","Wall"])
        r = st.selectbox("🏙️ Region", ["Dubai","Abu Dhabi","Sharjah","Ajman","RAK","UAQ","Fujairah"])
        if st.button("🔮 Predict Rate"):
            pr = predict_rate(m, w, r)
            st.metric("AI Predicted Rate", f"AED {pr:.2f} / sqm")
    with right:
        st.markdown("<div class='the-card'>", unsafe_allow_html=True)
        st.markdown("### 📈 Recent medians by material/work")
        rates = load_rates_df()
        if not rates.empty:
            piv = rates.groupby(["material","work"])["rate"].median().reset_index().rename(columns={"rate":"Median AED/sqm"})
            st.dataframe(piv.sort_values("Median AED/sqm", ascending=False), use_container_width=True)
        else:
            st.info("Scrape or upload to see market medians.")
        st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<hr/>", unsafe_allow_html=True)
st.caption("Notes: Only add sources you are allowed to scrape. The app respects robots.txt. Prices normalized to AED/sqm where possible.")
