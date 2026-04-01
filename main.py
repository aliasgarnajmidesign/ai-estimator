import os
import io
import json
import base64
import tempfile
import pandas as pd
import streamlit as st

# Document & CAD Processing
import fitz  # PyMuPDF
try:
    import ezdxf
    EZDXF_AVAILABLE = True
except ImportError:
    EZDXF_AVAILABLE = False

try:
    import cloudconvert
    CLOUDCONVERT_AVAILABLE = True
except ImportError:
    CLOUDCONVERT_AVAILABLE = False

# AI API
from openai import OpenAI

# ==============================================================================
# 🧠 AI VISION AGENT (THE MAGIC)
# ==============================================================================
def analyze_image_with_ai(image_bytes, api_key, is_elevation=False):
    """Sends the floor plan/elevation to GPT-4o Vision to extract exact rooms and materials."""
    client = OpenAI(api_key=api_key)
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    doc_type = "elevation drawing" if is_elevation else "floor plan"
    
    system_prompt = f"""
    You are an expert AI Quantity Surveyor and Architect. 
    Analyze this {doc_type}. 
    
    TASKS:
    1. Identify all rooms/spaces (or facade areas if elevation). Look for text labels and dimensions.
    2. Calculate or extract the Floor Area (sqm) and Perimeter (m) for each space. If dimensions are missing, use standard architectural proportions to estimate based on the drawing.
    3. Define logical, professional materials for the floors and walls based on the room type (e.g., Bathrooms get Ceramic Tiles and Moisture-resistant paint/tiles. Bedrooms get Wooden Flooring or Porcelain and Emulsion Paint).
    
    OUTPUT EXACTLY IN THIS JSON FORMAT:
    {{
        "rooms": [
            {{
                "Room Name": "Master Bedroom",
                "Floor Area (sqm)": 24.5,
                "Perimeter (m)": 20.0,
                "Floor Material": "Wood Flooring",
                "Wall Material": "Emulsion Paint"
            }}
        ]
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Please analyze this drawing and extract the BOQ data."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
            ]}
        ]
    )
    
    return json.loads(response.choices[0].message.content)

def analyze_dxf_with_ai(dxf_text_summary, api_key):
    """Uses AI to clean up raw CAD data and assign materials."""
    client = OpenAI(api_key=api_key)
    system_prompt = """
    You are an expert AI Quantity Surveyor. I am giving you raw geometric data extracted from a DXF CAD file.
    Clean up the room names, verify the areas, calculate perimeters, and suggest Floor and Wall materials for each room.
    
    OUTPUT EXACTLY IN THIS JSON FORMAT:
    {
        "rooms": [
            {
                "Room Name": "Living Room",
                "Floor Area (sqm)": 30.0,
                "Perimeter (m)": 22.0,
                "Floor Material": "Porcelain Tiles",
                "Wall Material": "Emulsion Paint"
            }
        ]
    }
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Here is the raw CAD data:\n{dxf_text_summary}"}
        ]
    )
    return json.loads(response.choices[0].message.content)

# ==============================================================================
# 📄 PDF PROCESSING
# ==============================================================================
def convert_pdf_to_image(pdf_bytes):
    """Converts the first page of a PDF to an image for the AI to 'see'."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=200) # High DPI for clear text reading
    return pix.tobytes("png")

# ==============================================================================
# 📐 CAD PROCESSING
# ==============================================================================
def extract_raw_dxf_data(file_bytes):
    """Extracts raw lines, text, and polygons from DXF."""
    if not EZDXF_AVAILABLE:
        return "Error: ezdxf not installed."
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)
        msp = doc.modelspace()
        
        texts = [e.dxf.text for e in msp.query('TEXT')]
        polys = [e for e in msp.query('LWPOLYLINE') if e.closed]
        
        summary = f"Found {len(polys)} enclosed spaces/rooms.\n"
        summary += f"Found Text Labels: {', '.join(texts[:20])}...\n"
        summary += "Approximate geometries found. Please estimate areas based on standard room sizes for these labels."
        return summary
    finally:
        os.unlink(tmp_path)

# ==============================================================================
# 🖥️ STREAMLIT UI APP
# ==============================================================================
st.set_page_config(page_title="AI Estimator Pro", layout="wide", page_icon="🏗️")

st.title("🏗️ AI Vision Estimator Pro")
st.markdown("Upload a PDF Plan, Elevation, or CAD file. The **AI will visually analyze it**, identify rooms, dimensions, and automatically assign editable materials.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 AI Settings")
    openai_key = st.text_input("OpenAI API Key (Required for AI)", type="password", help="Starts with 'sk-...'")
    cc_key = st.text_input("CloudConvert API Key (for .DWG)", type="password")
    
    st.divider()
    st.header("⚙️ Estimating Rules")
    wall_height = st.number_input("Standard Wall Height (m)", 2.5, 6.0, 3.0, 0.1)
    wastage = st.slider("Wastage (%)", 0, 30, 5)

tab1, tab2 = st.tabs(["📄 AI Plan/Elevation Analyzer", "📐 AI CAD Analyzer"])

# --- TAB 1: PDF VISION AI ---
with tab1:
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.info("Upload an architectural floor plan or elevation. The AI will read the text and dimensions directly from the image.")
        drawing_type = st.radio("Drawing Type:", ["Floor Plan", "Elevation"])
        pdf_file = st.file_uploader("Upload PDF Drawing", type=["pdf"])
        
        if pdf_file and st.button("🚀 Analyze with AI Magic", type="primary"):
            if not openai_key:
                st.error("⚠️ Please enter your OpenAI API Key in the sidebar to use Vision AI.")
            else:
                with st.spinner("🤖 AI is looking at your drawing and calculating..."):
                    try:
                        # 1. Convert PDF to Image
                        img_bytes = convert_pdf_to_image(pdf_file.read())
                        
                        # 2. Send to AI Vision
                        ai_result = analyze_image_with_ai(img_bytes, openai_key, is_elevation=(drawing_type=="Elevation"))
                        
                        # Save to session state so it doesn't disappear
                        st.session_state['ai_data'] = pd.DataFrame(ai_result['rooms'])
                        st.success("✅ AI Analysis Complete!")
                    except Exception as e:
                        st.error(f"Error during AI analysis: {e}")

    with col2:
        if 'ai_data' in st.session_state:
            st.subheader("📝 Editable AI Output (Change Materials & Qty)")
            st.caption("The AI has identified the following. You can click on any cell to change the material or correct the numbers.")
            
            # The Data Editor: Allows user to change materials and numbers!
            edited_df = st.data_editor(
                st.session_state['ai_data'], 
                num_rows="dynamic",
                use_container_width=True
            )
            
            st.divider()
            st.subheader("💰 Final Calculated BOQ")
            
            # Calculate final numbers based on the EDITABLE table
            final_boq = []
            for index, row in edited_df.iterrows():
                # Floor calculation
                final_boq.append({
                    "Room": row["Room Name"],
                    "Work Type": "Flooring",
                    "Material": row["Floor Material"],
                    "Net Qty": row["Floor Area (sqm)"],
                    "Qty w/ Wastage": round(row["Floor Area (sqm)"] * (1 + wastage/100), 2),
                    "Unit": "sqm"
                })
                # Wall calculation
                wall_area = row["Perimeter (m)"] * wall_height
                final_boq.append({
                    "Room": row["Room Name"],
                    "Work Type": "Wall Finish",
                    "Material": row["Wall Material"],
                    "Net Qty": wall_area,
                    "Qty w/ Wastage": round(wall_area * (1 + wastage/100), 2),
                    "Unit": "sqm"
                })
            
            boq_df = pd.DataFrame(final_boq)
            st.dataframe(boq_df, use_container_width=True)
            
            # Download Button
            csv = boq_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Final BOQ (CSV)", csv, "AI_Calculated_BOQ.csv", "text/csv")


# --- TAB 2: CAD AI ---
with tab2:
    st.info("Upload a DXF file. The system will extract the raw geometry and the AI will organize it into rooms and suggest materials.")
    cad_file = st.file_uploader("Upload DXF File", type=["dxf"])
    
    if cad_file and st.button("🚀 Process CAD with AI", type="primary"):
        if not openai_key:
            st.error("⚠️ Please enter your OpenAI API Key in the sidebar.")
        else:
            with st.spinner("🤖 AI is interpreting CAD data..."):
                raw_data = extract_raw_dxf_data(cad_file.read())
                
                if "Error" in raw_data:
                    st.error(raw_data)
                else:
                    ai_cad_result = analyze_dxf_with_ai(raw_data, openai_key)
                    cad_df = pd.DataFrame(ai_cad_result['rooms'])
                    
                    st.write("### AI Interpreted CAD Data")
                    st.data_editor(cad_df, num_rows="dynamic", use_container_width=True)
