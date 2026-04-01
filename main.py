import streamlit as st
import pandas as pd
import pdfplumber
import ezdxf
import re
import io

# ==============================================================================
# 🛠️ LOCAL LOGIC: MATERIAL RULE ENGINE (Replaces AI)
# ==============================================================================
def get_materials_locally(room_name):
    """Automatically assigns materials based on keywords in the room name."""
    name = room_name.lower()
    if any(x in name for x in ["bath", "wc", "toilet", "wash"]):
        return "Ceramic Tiles", "Moisture-Resistant Paint"
    if any(x in name for x in ["kitchen", "pantry"]):
        return "Anti-slip Tiles", "Washable Paint"
    if any(x in name for x in ["bed", "living", "hall", "majlis"]):
        return "Porcelain / Marble", "Emulsion Paint"
    if any(x in name for x in ["balcony", "terrace", "external"]):
        return "Outdoor Tiles", "Weather-proof Paint"
    return "Standard Tile", "Standard Paint"

# ==============================================================================
# 📄 PDF SCANNER (No API Required)
# ==============================================================================
def scan_pdf_for_rooms(pdf_file):
    """Scans PDF for text patterns like 'Bedroom: 20sqm' or 'Area: 15.5'."""
    found_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            # Pattern to find: Room Name + Number + sqm
            # Example: "Master Bedroom 25.5 sqm" or "Kitchen - 12m2"
            matches = re.findall(r"([a-zA-Z\s]+)\s*[:\-]?\s*(\d+\.?\d*)\s*(?:sqm|m2|m²)", text, re.IGNORECASE)
            
            for m in matches:
                r_name = m[0].strip()
                r_area = float(m[1])
                r_perim = round(4 * (r_area**0.5), 2) # Geometric estimate for perimeter
                f_mat, w_mat = get_materials_locally(r_name)
                
                found_data.append({
                    "Room": r_name,
                    "Area_sqm": r_area,
                    "Perimeter_m": r_perim,
                    "Floor_Material": f_mat,
                    "Wall_Material": w_mat
                })
    
    # If no text found, return a template for the user to fill manually
    if not found_data:
        found_data = [{"Room": "Add Room Name", "Area_sqm": 0.0, "Perimeter_m": 0.0, "Floor_Material": "Tiles", "Wall_Material": "Paint"}]
    return found_data

# ==============================================================================
# 🖥️ STREAMLIT UI
# ==============================================================================
st.set_page_config(page_title="AI-Estimator (Local)", layout="wide")
st.title("🏗️ Smart Estimator (No API Required)")
st.info("This version uses **Local Text Recognition** to find rooms and **Rule Logic** to assign materials.")

with st.sidebar:
    st.header("⚙️ Project Settings")
    wall_h = st.number_input("Wall Height (m)", 2.0, 6.0, 3.0)
    wastage = st.slider("Wastage (%)", 0, 20, 5)

pdf_up = st.file_uploader("Upload Floor Plan (PDF)", type=["pdf"])

if pdf_up:
    if st.button("🔍 Scan Drawing"):
        with st.spinner("Reading PDF Data..."):
            extracted_data = scan_pdf_for_rooms(pdf_up)
            st.session_state['data'] = extracted_data

if 'data' in st.session_state:
    st.subheader("📝 Editable Project Data")
    st.caption("Change any value below. The BOQ will update automatically.")
    
    # USER CAN EDIT EVERYTHING HERE
    df = pd.DataFrame(st.session_state['data'])
    edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
    
    # CALCULATE FINAL BOQ
    st.divider()
    st.subheader("📊 Final BOQ Calculation")
    
    final_boq = []
    for _, row in edited_df.iterrows():
        # Floor Calculation
        final_boq.append({
            "Room": row['Room'], 
            "Work": "Flooring", 
            "Material": row['Floor_Material'], 
            "Net Qty": row['Area_sqm'], 
            "Total Qty (incl. Wastage)": round(row['Area_sqm'] * (1 + wastage/100), 2),
            "Unit": "sqm"
        })
        # Wall Calculation
        w_area = row['Perimeter_m'] * wall_h
        final_boq.append({
            "Room": row['Room'], 
            "Work": "Wall Finish", 
            "Material": row['Wall_Material'], 
            "Net Qty": round(w_area, 2), 
            "Total Qty (incl. Wastage)": round(w_area * (1 + wastage/100), 2),
            "Unit": "sqm"
        })
    
    st.table(pd.DataFrame(final_boq))
    
    # Download Button
    csv = pd.DataFrame(final_boq).to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download BOQ", csv, "Project_BOQ.csv", "text/csv")
