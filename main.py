import os
import io
import pandas as pd
import streamlit as st

# ----------------------------------
# Page Config
# ----------------------------------
st.set_page_config(page_title="AI Estimator", layout="wide")

st.title("📐 AI Estimator - PDF to Estimate")
st.markdown("Upload PDF floor plans or Excel BOQs. Get instant estimates with wastage/overhead calculations.")

# ----------------------------------
# Sidebar
# ----------------------------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2092/2092658.png", width=100)
    st.title("Settings")
    api_key = st.text_input("CloudConvert API Key (optional)", type="password")
    if api_key:
        os.environ["CLOUDCONVERT_API_KEY"] = api_key
    
    st.markdown("---")
    st.markdown("### Quick Start")
    st.markdown("1. Upload PDF or Excel")
    st.markdown("2. Adjust wastage %")
    st.markdown("3. Download estimate")

# ----------------------------------
# Tabs
# ----------------------------------
tab1, tab2 = st.tabs(["📄 PDF to Estimate", "📊 Excel to Estimate"])

# =====================================================================
# TAB 1: PDF to Estimate (Demo extraction + correct per-row calculations)
# =====================================================================
with tab1:
    st.header("PDF Floor Plan to Estimate")
    
    pdf_file = st.file_uploader("Upload PDF Floor Plan", type=["pdf"])
    
    if pdf_file:
        st.success(f"Uploaded: {pdf_file.name}")
        
        # Settings
        col1, col2 = st.columns(2)
        with col1:
            wastage = st.slider("Wastage %", 0.0, 30.0, 5.0, 0.5)
            additional = st.slider("Additional %", 0.0, 30.0, 5.0, 0.5)
        
        with col2:
            units = st.number_input("Units per meter (optional)", 1.0, 10000.0, 1000.0, 1.0)
            wall_height = st.number_input("Wall height (m) (optional)", 2.0, 5.0, 3.0, 0.1)
        
        # Material rates (AED)
        rates = {
            "Floor Tiles": 45,
            "Wall Paint": 12,
            "Skirting": 25,
            # You can add more items below when you add extraction logic:
            # "Waterproofing": 30,
            # "Ceiling Paint": 14
        }
        
        if st.button("Generate Estimate", type="primary"):
            with st.spinner("Processing..."):
                import time
                time.sleep(1.5)
                
                # DEMO extraction results (replace these with your real PDF parsing later)
                results = {
                    "Floor Area": 100.5,   # sqm
                    "Wall Area": 250.2,    # sqm
                    "Perimeter": 50.3,     # lm
                    "Rooms": 4
                }
                
                # Show extracted metrics
                st.subheader("📊 Extracted Quantities (Demo)")
                col_a, col_b, col_c, col_d = st.columns(4)
                col_a.metric("Floor Area", f"{results['Floor Area']} sqm")
                col_b.metric("Wall Area", f"{results['Wall Area']} sqm")
                col_c.metric("Perimeter", f"{results['Perimeter']} lm")
                col_d.metric("Rooms", results['Rooms'])
                
                # Build estimate table (IMPORTANT: compute totals per-row, not one repeated value)
                st.subheader("💰 Estimate")
                
                estimate_data = {
                    "Item": ["Floor Tiles", "Wall Paint", "Skirting"],
                    "Unit": ["sqm", "sqm", "lm"],
                    "Quantity": [results["Floor Area"], results["Wall Area"], results["Perimeter"]],
                    "Rate (AED)": [rates["Floor Tiles"], rates["Wall Paint"], rates["Skirting"]],
                    "Wastage %": [wastage, wastage, wastage],
                    "Additional %": [additional, additional, additional],
                }
                
                df = pd.DataFrame(estimate_data)
                
                # Correct per-row total calculation
                df["Total (AED)"] = (
                    df["Quantity"] * df["Rate (AED)"] *
                    (1 + df["Wastage %"] / 100.0) *
                    (1 + df["Additional %"] / 100.0)
                ).round(2)
                
                st.dataframe(df, use_container_width=True)
                
                # Totals
                subtotal = float(df["Total (AED)"].sum())
                vat = round(subtotal * 0.05, 2)
                grand_total = round(subtotal + vat, 2)
                
                col_x, col_y, col_z = st.columns(3)
                col_x.metric("Subtotal", f"AED {subtotal:,.2f}")
                col_y.metric("VAT 5%", f"AED {vat:,.2f}")
                col_z.metric("Grand Total", f"AED {grand_total:,.2f}")
                
                # Export to Excel with engine fallback
                output = io.BytesIO()
                wrote = False
                try:
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df.to_excel(writer, index=False, sheet_name="Estimate")
                    wrote = True
                except Exception:
                    pass
                if not wrote:
                    try:
                        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                            df.to_excel(writer, index=False, sheet_name="Estimate")
                        wrote = True
                    except Exception as e:
                        st.error(f"Excel export failed. Please add 'openpyxl' or 'xlsxwriter' to requirements.txt. Error: {e}")
                
                if wrote:
                    st.download_button(
                        "📥 Download Excel",
                        output.getvalue(),
                        "estimate.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

# =====================================================================
# TAB 2: Excel BOQ to Estimate
# =====================================================================
with tab2:
    st.header("Excel BOQ to Estimate")
    
    # Template download
    if st.button("📋 Download Template"):
        template = pd.DataFrame({
            "Item": ["Floor Tiles", "Wall Paint", "Skirting"],
            "Unit": ["sqm", "sqm", "lm"],
            "Quantity": [100, 250, 50],
            "Rate (AED)": [45, 12, 25],
            "Wastage %": [5, 5, 5],
            "Additional %": [5, 5, 5]
        })
        
        bio = io.BytesIO()
        wrote = False
        try:
            with pd.ExcelWriter(bio, engine="openpyxl") as writer:
                template.to_excel(writer, index=False, sheet_name="Template")
            wrote = True
        except Exception:
            pass
        if not wrote:
            try:
                with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
                    template.to_excel(writer, index=False, sheet_name="Template")
                wrote = True
            except Exception as e:
                st.error(f"Template export failed. Please add 'openpyxl' or 'xlsxwriter' to requirements.txt. Error: {e}")
        
        if wrote:
            st.download_button(
                "Click to download",
                bio.getvalue(),
                "template.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    # File upload
    excel_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])
    
    if excel_file:
        try:
            df_in = pd.read_excel(excel_file)
            st.success("File loaded successfully!")
            st.dataframe(df_in, use_container_width=True)
            
            # Validate required columns
            required_cols = {"Item", "Unit", "Quantity", "Rate (AED)", "Wastage %", "Additional %"}
            missing = [c for c in required_cols if c not in df_in.columns]
            if missing:
                st.error(f"Missing required columns: {', '.join(missing)}")
            else:
                if st.button("Calculate Totals"):
                    df = df_in.copy()
                    
                    # Ensure numeric
                    for col in ["Quantity", "Rate (AED)", "Wastage %", "Additional %"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                    
                    # Add calculations
                    df["Final Qty"] = (
                        df["Quantity"] * (1 + df["Wastage %"] / 100.0) * (1 + df["Additional %"] / 100.0)
                    ).round(3)
                    df["Amount (AED)"] = (df["Final Qty"] * df["Rate (AED)"]).round(2)
                    df["VAT 5%"] = (df["Amount (AED)"] * 0.05).round(2)
                    df["Total (AED)"] = (df["Amount (AED)"] + df["VAT 5%"]).round(2)
                    
                    st.subheader("Calculated Estimate")
                    st.dataframe(df, use_container_width=True)
                    
                    total = float(df["Total (AED)"].sum())
                    st.metric("Grand Total (incl. VAT)", f"AED {total:,.2f}")
                    
                    # Export
                    export = io.BytesIO()
                    wrote = False
                    try:
                        with pd.ExcelWriter(export, engine="openpyxl") as writer:
                            df.to_excel(writer, index=False, sheet_name="Calculated")
                        wrote = True
                    except Exception:
                        pass
                    if not wrote:
                        try:
                            with pd.ExcelWriter(export, engine="xlsxwriter") as writer:
                                df.to_excel(writer, index=False, sheet_name="Calculated")
                            wrote = True
                        except Exception as e:
                            st.error(f"Excel export failed. Please add 'openpyxl' or 'xlsxwriter' to requirements.txt. Error: {e}")
                    
                    if wrote:
                        st.download_button(
                            "📥 Download",
                            export.getvalue(),
                            "calculated_estimate.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                
        except Exception as e:
            st.error(f"Error: {str(e)}")

# ----------------------------------
# Footer
# ----------------------------------
st.markdown("---")
st.markdown("AI Estimator v1.0 • Built for UAE Contractors")
