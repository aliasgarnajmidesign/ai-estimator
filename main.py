import os
import sys
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="AI Estimator", layout="wide")

st.title("📐 AI Estimator - PDF to Estimate")
st.markdown("Upload PDF floor plans or Excel BOQs. Get instant estimates with wastage/overhead calculations.")

# Sidebar
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

# Tabs
tab1, tab2 = st.tabs(["📄 PDF to Estimate", "📊 Excel to Estimate"])

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
            units = st.number_input("Units per meter", 1.0, 10000.0, 1000.0)
            wall_height = st.number_input("Wall height (m)", 2.0, 5.0, 3.0, 0.1)
        
        # Material rates
        rates = {
            "Floor Tiles": 45,
            "Wall Paint": 12,
            "Skirting": 25,
            "Waterproofing": 30,
            "Ceiling Paint": 14
        }
        
        if st.button("Generate Estimate", type="primary"):
            # Simulate calculation (for demo)
            with st.spinner("Processing..."):
                import time
                time.sleep(2)
                
                # Sample results
                results = {
                    "Floor Area": 100.5,
                    "Wall Area": 250.2,
                    "Perimeter": 50.3,
                    "Rooms": 4
                }
                
                st.subheader("📊 Extracted Quantities")
                col_a, col_b, col_c, col_d = st.columns(4)
                col_a.metric("Floor Area", f"{results['Floor Area']} sqm")
                col_b.metric("Wall Area", f"{results['Wall Area']} sqm")
                col_c.metric("Perimeter", f"{results['Perimeter']} lm")
                col_d.metric("Rooms", results['Rooms'])
                
                # Estimate
                st.subheader("💰 Estimate")
                estimate_data = {
                    "Item": ["Floor Tiles", "Wall Paint", "Skirting"],
                    "Unit": ["sqm", "sqm", "lm"],
                    "Quantity": [100.5, 250.2, 50.3],
                    "Rate (AED)": [45, 12, 25],
                    "Wastage %": [wastage, wastage, wastage],
                    "Additional %": [additional, additional, additional],
                    "Total (AED)": [round(100.5*45*(1+wastage/100)*(1+additional/100), 2),
                                   round(250.2*12*(1+wastage/100)*(1+additional/100), 2),
                                   round(50.3*25*(1+wastage/100)*(1+additional/100), 2)]
                }
                
                df = pd.DataFrame(estimate_data)
                st.dataframe(df)
                
                # Totals
                total = df["Total (AED)"].sum()
                vat = total * 0.05
                grand_total = total + vat
                
                col_x, col_y, col_z = st.columns(3)
                col_x.metric("Subtotal", f"AED {total:,.2f}")
                col_y.metric("VAT 5%", f"AED {vat:,.2f}")
                col_z.metric("Grand Total", f"AED {grand_total:,.2f}")
                
                # Export
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Estimate')
                
                st.download_button(
                    "📥 Download Excel",
                    output.getvalue(),
                    "estimate.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

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
        with pd.ExcelWriter(bio, engine='openpyxl') as writer:
            template.to_excel(writer, index=False)
        
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
            df = pd.read_excel(excel_file)
            st.success("File loaded successfully!")
            st.dataframe(df)
            
            # Calculate
            if st.button("Calculate Totals"):
                # Add calculations
                df["Final Qty"] = df["Quantity"] * (1 + df["Wastage %"]/100) * (1 + df["Additional %"]/100)
                df["Amount (AED)"] = df["Final Qty"] * df["Rate (AED)"]
                df["VAT 5%"] = df["Amount (AED)"] * 0.05
                df["Total (AED)"] = df["Amount (AED)"] + df["VAT 5%"]
                
                st.subheader("Calculated Estimate")
                st.dataframe(df)
                
                total = df["Total (AED)"].sum()
                st.metric("Grand Total", f"AED {total:,.2f}")
                
                # Export
                export = io.BytesIO()
                with pd.ExcelWriter(export, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)
                
                st.download_button(
                    "📥 Download",
                    export.getvalue(),
                    "calculated_estimate.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
        except Exception as e:
            st.error(f"Error: {str(e)}")

# Footer
st.markdown("---")
st.markdown("AI Estimator v1.0 • Built for UAE Contractors")
