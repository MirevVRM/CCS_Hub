import streamlit as st
import pandas as pd
import json
import io
import os
import glob
from dataclasses import asdict

import altair as alt

# Import existing models and optimization logic
from models import Plant, SystemParameters
from data_io import (
    validate_input_data, 
    load_scenario_from_excel, 
    load_plants_from_csv, 
    save_results_to_excel, 
    save_results_to_csv_zip, 
    create_excel_template
)
from optimizer import prepare_model_data, build_and_solve_optimizations, generate_results
from explainer import generate_explanations

st.set_page_config(page_title="CCS Hub Optimization", layout="wide")

# ==============================================================================
# Helper Functions
# ==============================================================================

# Unused old JSON routines removed (glob and save to disk)
def create_new_scenario():
    """Initializes empty state."""
    st.session_state.sys_params = {
        "planning_horizon_y": 25,
        "start_year": 2025,
        "annual_hub_capacity_mtpy": 20.0,
        "cumulative_storage_capacity_mt": 500.0,
        "minimum_connection_time_y": 10,
        "capture_efficiency": 0.9
    }
    st.session_state.plants_df = pd.DataFrame(columns=["id", "name", "co2_flow_mtpy", "capture_cost_euro_per_t", "remaining_life_y", "max_co2_mt"])

def save_results(plant_results, yearly_results, summary, plant_year_df, yearly_expanded_df, explanations, filename="results.json"):
    """Saves the output of the optimization to a JSON file, including detailed analytics."""
    if not filename.endswith('.json'):
         filename += '.json'
         
    output_data = {
        "system_summary": asdict(summary),
        "plant_results": [asdict(pr) for pr in plant_results],
        "yearly_hub_load": yearly_expanded_df.to_dict(orient="records"),
        "plant_year_contributions": plant_year_df.to_dict(orient="records"),
        "decision_explanations": [asdict(e) for e in explanations]
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    st.success(f"Saved results and detailed analytics to {filename}")

def apply_universal_chart_formatting(chart: alt.Chart, force_black: bool = False) -> alt.Chart:
    """
    Applies unified configuration to Altair charts to prevent text truncation, 
    improve readability across normal and Fullscreen modes, and maintain UI stability.
    """
    text_c = '#000000' if force_black else 'currentColor'
    label_fs = 14 if force_black else 13
    title_fs = 16 if force_black else 15
    title_main_fs = 18 if force_black else 16
    
    return chart.configure_axis(
        labelLimit=1000,   # Prevent Y/X axis long names from truncating (1000px limit)
        labelOverlap=True if force_black else False, # Allow Altair to hide overlapping labels in export
        labelFontSize=label_fs,
        titleFontSize=title_fs,
        labelPadding=5,
        titlePadding=10,
        labelColor=text_c, # Inherit Streamlit DOM text color or force black for SVG export
        titleColor=text_c,
        tickColor=text_c,
        domainColor=text_c
    ).configure_legend(
        labelLimit=1000,
        labelFontSize=label_fs,
        titleFontSize=title_fs,
        symbolSize=150 if not force_black else 200,
        labelColor=text_c,
        titleColor=text_c
    ).configure_title(
        fontSize=title_main_fs,
        fontWeight='bold',
        anchor='start',
        offset=15,
        color=text_c       # Inherit Streamlit DOM text color or force black for SVG export
    ).configure_view(
        strokeOpacity=0    # Clean up default border
    )

def render_download_button(chart_export: alt.Chart, filename: str, key: str):
    """Generates an SVG on the server and provides a download button."""
    try:
        f = io.StringIO()
        chart_export.save(f, format='svg')
        svg_data = f.getvalue()
        st.download_button("📥 Download SVG for Word", data=svg_data, file_name=filename, mime="image/svg+xml", key=key)
    except Exception as e:
        st.error(f"SVG export failed. Please ensure `vl-convert-python` is installed. Error: {e}")

# ==============================================================================
# State Initialization
# ==============================================================================

if 'sys_params' not in st.session_state:
    create_new_scenario()

if 'run_results' not in st.session_state:
    st.session_state.run_results = None

# ==============================================================================
# UI Sidebar
# ==============================================================================

with st.sidebar:
    st.title("📂 Scenario Management")
    
    if st.button("➕ Create New Scenario", use_container_width=True):
        create_new_scenario()
        st.session_state.run_results = None
        st.success("Started a new empty scenario.")
        
    st.divider()
    
    st.subheader("Load Scenario")
    st.info("CSV updates only the Plants table. System parameters remain as currently set in the UI.")
    uploaded_file = st.file_uploader("Upload File", type=['json', 'xlsx', 'csv'])
    if uploaded_file is not None:
        if st.button("Load Uploaded File"):
            try:
                import dataclasses
                if uploaded_file.name.endswith('.json'):
                    data = json.loads(uploaded_file.getvalue().decode('utf-8'))
                    if "system_summary" in data:
                        st.error("This is a results file, not a scenario.")
                    else:
                        st.session_state.sys_params = data.get("system_parameters", st.session_state.sys_params)
                        st.session_state.plants_df = pd.DataFrame(data.get("plants", []))
                        st.success(f"Loaded JSON: {uploaded_file.name}")
                        st.session_state.run_results = None
                elif uploaded_file.name.endswith('.xlsx'):
                    plants, sys_params = load_scenario_from_excel(uploaded_file)
                    st.session_state.sys_params = dataclasses.asdict(sys_params)
                    st.session_state.plants_df = pd.DataFrame([dataclasses.asdict(p) for p in plants])
                    st.success(f"Loaded Excel: {uploaded_file.name}")
                    st.session_state.run_results = None
                elif uploaded_file.name.endswith('.csv'):
                    plants = load_plants_from_csv(uploaded_file)
                    st.session_state.plants_df = pd.DataFrame([dataclasses.asdict(p) for p in plants])
                    st.success(f"Loaded CSV Plants: {uploaded_file.name}. System parameters remain unchanged.")
                    st.session_state.run_results = None
                
                # Auto-calculate max co2
                if not st.session_state.plants_df.empty:
                    st.session_state.plants_df['max_co2_mt'] = st.session_state.plants_df['co2_flow_mtpy'] * st.session_state.plants_df['remaining_life_y']
            except Exception as e:
                st.error(f"Error loading file: {e}")

    st.divider()
    
    st.subheader("Save Current Scenario")
    scenario_data = {
        "system_parameters": st.session_state.sys_params,
        "plants": st.session_state.plants_df.to_dict('records')
    }
    scenario_json = json.dumps(scenario_data, indent=2, ensure_ascii=False)
    st.download_button("Download JSON Scenario", data=scenario_json, file_name="scenario.json", mime="application/json")
    
    st.divider()
    
    st.subheader("Templates")
    template_bytes = create_excel_template()
    st.download_button("Download Excel Template", data=template_bytes, file_name="scenario_template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
# ==============================================================================
# Main Content Area
# ==============================================================================

st.title("🌍 CCS Hub Optimization Tool")
st.markdown("Configure your scenario, define your CO₂ sources, and run the optimization engine.")

tab_sys, tab_plants, tab_opt, tab_analytics, tab_explain = st.tabs([
    "⚙️ System Parameters", 
    "🏭 Plants Configuration", 
    "🚀 Optimization Summary",
    "📊 Detailed Analytics",
    "💡 Decision Explanations"
])

# ----------------- Tab 1: System Parameters -----------------
with tab_sys:
    st.header("System Settings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.session_state.sys_params["planning_horizon_y"] = st.number_input(
            "Planning Horizon (years) [T]", value=int(st.session_state.sys_params["planning_horizon_y"]))
            
        st.session_state.sys_params["start_year"] = st.number_input(
            "Start Year", value=int(st.session_state.sys_params["start_year"]))
            
        st.session_state.sys_params["capture_efficiency"] = st.number_input(
            "Capture Efficiency [\u03B7]", step=0.05, value=float(st.session_state.sys_params["capture_efficiency"]))
            
    with col2:
        st.session_state.sys_params["annual_hub_capacity_mtpy"] = st.number_input(
            "Annual Hub Capacity (Mt/y) [A]", step=1.0, value=float(st.session_state.sys_params["annual_hub_capacity_mtpy"]))
            
        st.session_state.sys_params["cumulative_storage_capacity_mt"] = st.number_input(
            "Cumulative Storage Capacity (Mt) [G]", step=10.0, value=float(st.session_state.sys_params["cumulative_storage_capacity_mt"]))
            
        st.session_state.sys_params["minimum_connection_time_y"] = st.number_input(
            "Minimum Connection Time (years) [m]", value=int(st.session_state.sys_params["minimum_connection_time_y"]))


# ----------------- Tab 2: Plants Configuration -----------------
with tab_plants:
    st.header("CO₂ Sources (Plants)")
    st.markdown("Add, remove, or edit plants below. The `max_co2_mt` column is auto-calculated based on `co2_flow_mtpy * remaining_life_y`.")

    # Configure columns for data editor
    column_config = {
        "id": st.column_config.NumberColumn("Plant ID", required=True, format="%d"),
        "name": st.column_config.TextColumn("Plant Name", required=True),
        "co2_flow_mtpy": st.column_config.NumberColumn("Gen. CO₂ Flow (Mt/y)", required=True, format="%.3f"),
        "capture_cost_euro_per_t": st.column_config.NumberColumn("Capture Cost (€/t)", required=True, format="%.2f"),
        "remaining_life_y": st.column_config.NumberColumn("Remaining Life (y)", required=True, format="%d"),
        "max_co2_mt": st.column_config.NumberColumn("Max Gen. CO₂ (Mt)  [Auto]", disabled=True, format="%.3f")
    }

    # Edited dataframe
    edited_df = st.data_editor(
        st.session_state.plants_df,
        column_config=column_config,
        num_rows="dynamic",
        use_container_width=True,
        key="plant_editor"
    )

    # Auto-calculate max_co2_mt on the fly
    if not edited_df.empty:
        # Fill NaNs with defaults to avoid computation errors while user is typing
        edited_df['co2_flow_mtpy'] = pd.to_numeric(edited_df['co2_flow_mtpy'], errors='coerce').fillna(0)
        edited_df['remaining_life_y'] = pd.to_numeric(edited_df['remaining_life_y'], errors='coerce').fillna(0)
        
        # Calculate
        edited_df['max_co2_mt'] = edited_df['co2_flow_mtpy'] * edited_df['remaining_life_y']
        
        # Save back to state
        st.session_state.plants_df = edited_df

# ----------------- Tab 3: Optimization & Results -----------------
with tab_opt:
    st.header("Optimization Engine")
    
    if st.button("🚀 Run Two-Stage Optimization", type="primary", use_container_width=True):
        st.session_state.run_results = None # Clear previous
        
        # 1. Convert state back to dataclasses
        sys_obj = SystemParameters(**st.session_state.sys_params)
        
        try:
            plant_objs = []
            for _, row in st.session_state.plants_df.iterrows():
                # Avoid passing completely empty rows
                if pd.isna(row['id']) or row['name'] == "":
                     continue
                
                plant_objs.append(Plant(
                    id=int(row['id']),
                    name=str(row['name']),
                    co2_flow_mtpy=float(row['co2_flow_mtpy']),
                    capture_cost_euro_per_t=float(row['capture_cost_euro_per_t']),
                    remaining_life_y=int(row['remaining_life_y']),
                    max_co2_mt=float(row['max_co2_mt'])
                ))
                
            if not plant_objs:
                 st.error("No valid plants found. Please add plants in the Configuration tab.")
                 st.stop()
                 
            # 1.5 Validate input data
            try:
                validate_input_data(plant_objs, sys_obj)
            except Exception as e:
                st.error(f"Data validation failed: {e}")
                st.stop()
                 
            # 2. Build model data
            model_data = prepare_model_data(plant_objs, sys_obj)
            
            if not model_data.allowed_starts:
                st.error("Error: No valid connection options found. All plants fail the minimum connection time or hub capacity limits.")
                st.stop()
                
            # 3. Solve Phase 1 & 2
            with st.spinner("Running Optimization Stages..."):
                solution = build_and_solve_optimizations(model_data)
                
            # 4. Handle Result
            if solution is None:
                st.error("Optimization could not find a feasible solution. Your constraints (Storage / Hub / Connection Time) might be too restrictive.")
            else:
                st.success("Optimization completed successfully!")
                plant_res, yearly_res, summary = generate_results(model_data, solution)
                
                # --- PREPARE DETAILED ANALYTICS DATAFRAMES ---
                
                # 1. Yearly Cumulative Expansion
                y_df = pd.DataFrame([asdict(y) for y in yearly_res])
                y_df['cumulative_storage_used_mt'] = y_df['hub_load_mtpy'].cumsum()
                y_df['storage_remaining_mt'] = sys_obj.cumulative_storage_capacity_mt - y_df['cumulative_storage_used_mt']
                
                # 2. Plant-Year Flat Contributions
                flat_data = []
                for p in plant_res:
                    # We need to trace cumulative captured for this specific plant manually
                    cum_cap_plant = 0.0
                    for yr in yearly_res:
                        is_active = False
                        contribution = 0.0
                        if p.selected and p.start_calendar_year is not None:
                            if p.start_calendar_year <= yr.calendar_year < (p.start_calendar_year + p.active_years):
                                is_active = True
                                contribution = p.annual_captured_co2_mtpy
                                cum_cap_plant += contribution
                                
                        flat_data.append({
                            "plant_id": p.plant_id,
                            "plant_name": p.plant_name,
                            "calendar_year": yr.calendar_year,
                            "selected": p.selected,
                            "active_in_year": is_active,
                            "generated_co2_mtpy": p.annual_generated_co2_mtpy if is_active else 0.0,
                            "captured_co2_mtpy": p.annual_captured_co2_mtpy if is_active else 0.0,
                            "residual_co2_mtpy": p.annual_residual_co2_mtpy if is_active else 0.0,
                            "contribution_to_hub_load_mtpy": contribution,
                            "cumulative_captured_to_date_by_plant": cum_cap_plant
                        })
                
                flat_df = pd.DataFrame(flat_data)
                
                # 3. Generate Rule-Based Explanations
                explanations = generate_explanations(plant_objs, plant_res, sys_obj, y_df, summary.storage_remaining_mt)
                
                st.session_state.run_results = {
                    "plants": plant_res,
                    "yearly": yearly_res,
                    "summary": summary,
                    "yearly_expanded_df": y_df,
                    "plant_year_df": flat_df,
                    "explanations": explanations
                }
                
        except Exception as e:
            st.error(f"An error occurred during formulation/optimization: {e}")

    # Display Results if available
    if st.session_state.run_results is not None:
        st.divider()
        res = st.session_state.run_results
        smry = res["summary"]
        
        # Top Metrics
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Captured CO₂", f"{smry.total_captured_co2_mt:.3f} Mt")
        m2.metric("Total Capture Cost", f"€ {smry.total_capture_cost_euro:,.0f}")
        m3.metric("Avg Capture Cost", f"{smry.average_capture_cost_euro_per_t:.2f} €/t")
        m4.metric("Storage Used", f"{smry.storage_used_mt:.3f} Mt")
        m5.metric("Storage Remaining", f"{smry.storage_remaining_mt:.3f} Mt")
        
        st.divider()
        
        st.subheader("Plant Contributions Overview")
        
        p_df = pd.DataFrame([asdict(p) for p in res["plants"]])
        selected_p_df = p_df[p_df['selected'] == True].copy()
        
        # Consistent Color Palette for Export & UI
        all_plants = sorted(p_df['plant_name'].unique())
        # Tableau 10 standard professional palette
        hex_colors = ["#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b", "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac"] * 3
        plant_color_scale = alt.Scale(domain=all_plants, range=hex_colors[:len(all_plants)])
        
        if not selected_p_df.empty and smry.total_captured_co2_mt > 0:
            selected_p_df['co2_share_pct'] = (selected_p_df['cumulative_captured_co2_mt'] / smry.total_captured_co2_mt * 100).round(1)
            selected_p_df['cost_share_pct'] = (selected_p_df['total_capture_cost_euro'] / smry.total_capture_cost_euro * 100).round(1)
            
            selected_p_df['co2_label'] = selected_p_df.apply(lambda x: f"{x['cumulative_captured_co2_mt']:.1f} Mt ({x['co2_share_pct']}%)", axis=1)
            
            def fmt_cost(c):
                if c >= 1e9: return f"€{c/1e9:.2f}B"
                elif c >= 1e6: return f"€{c/1e6:.1f}M"
                return f"€{c:,.0f}"
                
            selected_p_df['cost_label'] = selected_p_df.apply(lambda x: f"{fmt_cost(x['total_capture_cost_euro'])} ({x['cost_share_pct']}%)", axis=1)

            hover = alt.selection_point(on='mouseover', empty=True, nearest=False, fields=['plant_name'])
            
            max_co2 = float(selected_p_df['cumulative_captured_co2_mt'].max())
            max_cost = float(selected_p_df['total_capture_cost_euro'].max())
            
            sorted_co2 = selected_p_df.sort_values(by='cumulative_captured_co2_mt', ascending=False)['plant_name'].tolist()
            sorted_cost = selected_p_df.sort_values(by='total_capture_cost_euro', ascending=False)['plant_name'].tolist()

            # --- CO2 Chart ---
            def get_bar_co2(interactive=True):
                op = alt.condition(hover, alt.value(1.0), alt.value(0.4)) if interactive else alt.value(1.0)
                return alt.Chart(selected_p_df).mark_bar(cornerRadiusEnd=3).encode(
                    x=alt.X('cumulative_captured_co2_mt:Q', title='Captured CO₂ (Mt)', scale=alt.Scale(domain=[0, max_co2 * 1.30])),
                    y=alt.Y('plant_name:N', sort=sorted_co2, title=None),
                    color=alt.Color('plant_name:N', legend=None, scale=plant_color_scale),
                    opacity=op,
                    tooltip=[
                        alt.Tooltip('plant_name:N', title='Plant'),
                        alt.Tooltip('cumulative_captured_co2_mt:Q', title='CO2 Captured (Mt)', format='.3f'),
                        alt.Tooltip('co2_share_pct:Q', title='Share (%)', format='.1f')
                    ]
                )

            # Labels for CO2
            def get_text_co2(color_hex, interactive=True):
                op = alt.condition(hover, alt.value(1.0), alt.value(0.4)) if interactive else alt.value(1.0)
                return alt.Chart(selected_p_df).mark_text(
                    align='left', baseline='middle', dx=4, fontWeight='bold', clip=False,
                    size=alt.expr("max(13, min(width / 40, 18))"), color=color_hex
                ).encode(
                    x=alt.X('cumulative_captured_co2_mt:Q'), y=alt.Y('plant_name:N', sort=sorted_co2),
                    text='co2_label:N', opacity=op
                )

            export_h = min(450, max(300, len(selected_p_df)*60))
            chart_co2_ui = apply_universal_chart_formatting((get_bar_co2(True) + get_text_co2('currentColor', True)).properties(title="Total Captured CO₂ Share", height=min(350, max(200, len(selected_p_df)*42))).add_params(hover))
            chart_co2_export = apply_universal_chart_formatting((get_bar_co2(False) + get_text_co2('#000000', False)).properties(
                title="Total Captured CO₂ Share", width=700, height=export_h
            ), force_black=True)

            # --- Cost Chart ---
            def get_bar_cost(interactive=True):
                op = alt.condition(hover, alt.value(1.0), alt.value(0.4)) if interactive else alt.value(1.0)
                return alt.Chart(selected_p_df).mark_bar(cornerRadiusEnd=3).encode(
                    x=alt.X('total_capture_cost_euro:Q', 
                            title='Capture Cost (€)', 
                            scale=alt.Scale(domain=[0, max_cost * 1.30]),
                            axis=alt.Axis(
                                labelExpr="datum.value >= 1e9 ? '€' + format(datum.value / 1e9, '.0f') + 'B' : datum.value >= 1e6 ? '€' + format(datum.value / 1e6, '.0f') + 'M' : '€' + format(datum.value, '.0f')",
                                tickCount=5
                            )),
                    y=alt.Y('plant_name:N', sort=sorted_cost, title=None),
                    color=alt.Color('plant_name:N', legend=None, scale=plant_color_scale),
                    opacity=op,
                    tooltip=[
                        alt.Tooltip('plant_name:N', title='Plant'),
                        alt.Tooltip('total_capture_cost_euro:Q', title='Capture Cost (€)', format=',.0f'),
                        alt.Tooltip('cost_share_pct:Q', title='Share (%)', format='.1f')
                    ]
                )

            # Labels for Cost
            def get_text_cost(color_hex, interactive=True):
                op = alt.condition(hover, alt.value(1.0), alt.value(0.4)) if interactive else alt.value(1.0)
                return alt.Chart(selected_p_df).mark_text(
                    align='left', baseline='middle', dx=4, fontWeight='bold', clip=False,
                    size=alt.expr("max(13, min(width / 40, 18))"), color=color_hex
                ).encode(
                    x=alt.X('total_capture_cost_euro:Q'), y=alt.Y('plant_name:N', sort=sorted_cost),
                    text='cost_label:N', opacity=op
                )

            chart_cost_ui = apply_universal_chart_formatting((get_bar_cost(True) + get_text_cost('currentColor', True)).properties(title="Total Capture Cost Share", height=min(350, max(200, len(selected_p_df)*42))).add_params(hover))
            chart_cost_export = apply_universal_chart_formatting((get_bar_cost(False) + get_text_cost('#000000', False)).properties(
                title="Total Capture Cost Share", width=700, height=export_h
            ), force_black=True)

            col_c1, col_c2 = st.columns(2)
            with col_c1:
                st.altair_chart(chart_co2_ui, use_container_width=True)
                render_download_button(chart_co2_export, "co2_share.svg", "dl_co2")
            with col_c2:
                st.altair_chart(chart_cost_ui, use_container_width=True)
                render_download_button(chart_cost_export, "cost_share.svg", "dl_cost")
                
        st.divider()
        
        # Results Tables
        col_res1, col_res2 = st.columns([1.5, 1])
        
        with col_res1:
            st.subheader("Plant Outcomes")
            
            # Reformat slightly for better display
            display_p_df = p_df[['plant_id', 'plant_name', 'selected', 'start_calendar_year', 'active_years', 'cumulative_captured_co2_mt', 'total_capture_cost_euro']].copy()
            st.dataframe(display_p_df, use_container_width=True)
            
        with col_res2:
            st.subheader("Hub Load by Year (Summary)")
            display_y_df = res["yearly_expanded_df"][['calendar_year', 'hub_load_mtpy', 'free_capacity_mtpy']].copy()
            st.dataframe(display_y_df, use_container_width=True)
            
        st.divider()
        
        # Save Results Input
        st.subheader("💾 Export Solution")
        export_format = st.radio("Export Format", ["Excel (.xlsx)", "JSON", "CSV Archive (.zip)"], horizontal=True)
        
        if export_format == "JSON":
            output_data = {
                "system_summary": asdict(res["summary"]),
                "plant_results": [asdict(pr) for pr in res["plants"]],
                "yearly_hub_load": res["yearly_expanded_df"].to_dict(orient="records"),
                "plant_year_contributions": res["plant_year_df"].to_dict(orient="records"),
                "decision_explanations": [asdict(e) for e in res["explanations"]]
            }
            res_json = json.dumps(output_data, indent=2, ensure_ascii=False)
            st.download_button("Download JSON Results", data=res_json, file_name="results.json", mime="application/json")
            
        elif export_format == "Excel (.xlsx)":
            import io
            b_io = io.BytesIO()
            save_results_to_excel(res["plants"], res["yearly"], res["summary"], res["plant_year_df"], res["yearly_expanded_df"], res["explanations"], b_io)
            st.download_button("Download Excel Results", data=b_io.getvalue(), file_name="results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
        elif export_format == "CSV Archive (.zip)":
            import io
            b_io = io.BytesIO()
            save_results_to_csv_zip(res["plants"], res["yearly"], res["summary"], res["plant_year_df"], res["yearly_expanded_df"], res["explanations"], b_io)
            st.download_button("Download CSV Archive", data=b_io.getvalue(), file_name="results.zip", mime="application/zip")

# ----------------- Tab 4: Detailed Analytics -----------------
with tab_analytics:
    st.header("Detailed System Analytics")
    
    if st.session_state.run_results is None:
        st.info("No results available. Please run the optimization first.")
    else:
        res = st.session_state.run_results
        py_df = res["plant_year_df"]
        ye_df = res["yearly_expanded_df"]
        sys_params = st.session_state.sys_params
        
        # --- GRAPHICS SECTION ---
        st.subheader("Visualizations")
        
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            # Filter to active only for cleaner stacked chart
            active_only_df = py_df[py_df['active_in_year'] == True]
            
            # Smart X-axis thinning for export
            total_years = active_only_df['calendar_year'].nunique() if not active_only_df.empty else 1
            yr_step = 5 if total_years > 20 else (2 if total_years > 10 else 1)
            
            # Uniform Hover Logic for Plant Name
            hover_plant = alt.selection_point(on='mouseover', empty=True, nearest=False, fields=['plant_name'])
            
            # Create base stacked bar chart
            def get_hub_chart(interactive=True):
                op = alt.condition(hover_plant, alt.value(1.0), alt.value(0.4)) if interactive else alt.value(1.0)
                # Force X-axis thinning if not interactive (export mode)
                x_axis = alt.Axis(labelAngle=0) if interactive else alt.Axis(labelAngle=0, labelExpr=f"datum.value % {yr_step} == 0 ? datum.value : ''")
                return alt.Chart(active_only_df).mark_bar(clip=False).encode(
                    x=alt.X('calendar_year:O', title='Calendar Year', axis=x_axis),
                    y=alt.Y('contribution_to_hub_load_mtpy:Q', title='Hub Load (Mt/y)'),
                    color=alt.Color('plant_name:N', title='Plant Name', scale=plant_color_scale),
                    opacity=op,
                    tooltip=['plant_name', 'calendar_year', 'contribution_to_hub_load_mtpy']
                )
            
            # Create rule for Annual Hub Capacity limit (Will remain fully opaque and clear)
            capacity_df = pd.DataFrame({'limit': [sys_params['annual_hub_capacity_mtpy']]})
            rule_chart = alt.Chart(capacity_df).mark_rule(color='red', strokeDash=[5, 5]).encode(
                y='limit:Q'
            )
            # Layer and display
            chart_hub_ui = apply_universal_chart_formatting((get_hub_chart(True).add_params(hover_plant) + rule_chart).properties(title="Hub Load Contributions by Plant (Stacked)"))
            chart_hub_export = apply_universal_chart_formatting((get_hub_chart(False) + rule_chart).properties(
                title="Hub Load Contributions by Plant (Stacked)", width=900, height=450
            ), force_black=True)
            
            st.altair_chart(chart_hub_ui, use_container_width=True)
            render_download_button(chart_hub_export, "hub_load.svg", "dl_hub")
            
        with col_g2:
            # Interactive Selection for X-axis (Years)
            hover_year = alt.selection_point(on='mouseover', empty=False, nearest=True, fields=['calendar_year'])
            
            total_years = ye_df['calendar_year'].nunique() if not ye_df.empty else 1
            yr_step = 5 if total_years > 20 else (2 if total_years > 10 else 1)
            
            def get_area_chart(interactive=True):
                x_axis = alt.Axis(labelAngle=0) if interactive else alt.Axis(labelAngle=0, labelExpr=f"datum.value % {yr_step} == 0 ? datum.value : ''")
                base = alt.Chart(ye_df).encode(x=alt.X('calendar_year:O', title='Calendar Year', axis=x_axis))
                return base.mark_area(opacity=0.6, color='steelblue', clip=False).encode(
                    y=alt.Y('cumulative_storage_used_mt:Q', title='Cumulative Storage (Mt)'),
                    tooltip=['calendar_year', 'cumulative_storage_used_mt', 'storage_remaining_mt']
                ), base
            
            area_chart_ui, base_area_ui = get_area_chart(True)
            area_chart_export, _ = get_area_chart(False)

            # Interactive elements for UI only
            selectors = alt.Chart(ye_df).mark_point().encode(
                x='calendar_year:O', opacity=alt.value(0),
            ).add_params(hover_year)
            
            rules = base_area_ui.mark_rule(strokeWidth=2).encode(
                opacity=alt.condition(hover_year, alt.value(1.0), alt.value(0.0))
            )
            
            points = base_area_ui.mark_circle(color='white', size=60, stroke='steelblue', strokeWidth=2).encode(
                y='cumulative_storage_used_mt:Q',
                opacity=alt.condition(hover_year, alt.value(1.0), alt.value(0.0))
            )
            
            storage_cap_df = pd.DataFrame({'limit': [sys_params['cumulative_storage_capacity_mt']]})
            storage_rule = alt.Chart(storage_cap_df).mark_rule(color='red', strokeDash=[5, 5]).encode(
                y='limit:Q'
            )
            
            # --- NUMERIC LABELS ---
            min_yr = int(ye_df['calendar_year'].min())
            limit_label_df = pd.DataFrame({'limit': [sys_params['cumulative_storage_capacity_mt']], 'text': [f"Limit: {sys_params['cumulative_storage_capacity_mt']:.1f} Mt"], 'x': [min_yr]})
            
            limit_text = alt.Chart(limit_label_df).mark_text(
                align='left', baseline='bottom', dy=-5, dx=5, fontWeight='bold', size=14, color='red'
            ).encode(x=alt.X('x:O'), y=alt.Y('limit:Q'), text='text:N')
            
            final_row = ye_df.iloc[[-1]].copy()
            final_row['text'] = final_row['cumulative_storage_used_mt'].apply(lambda v: f"Used: {v:.1f} Mt")
            
            def get_used_text(color_hex):
                return alt.Chart(final_row).mark_text(
                    align='right', baseline='bottom', dy=-15, dx=0, fontWeight='bold', size=14, color=color_hex
                ).encode(x=alt.X('calendar_year:O'), y=alt.Y('cumulative_storage_used_mt:Q'), text='text:N')
            
            chart_area_ui = apply_universal_chart_formatting((area_chart_ui + selectors + storage_rule + limit_text + rules + points + get_used_text('currentColor')).properties(title="Cumulative Storage Used vs. Capacity"))
            chart_area_export = apply_universal_chart_formatting((area_chart_export + storage_rule + limit_text + get_used_text('#000000')).properties(
                title="Cumulative Storage Used vs. Capacity", width=900, height=450
            ), force_black=True)
            
            st.altair_chart(chart_area_ui, use_container_width=True)
            render_download_button(chart_area_export, "cumulative_storage.svg", "dl_area")

        st.divider()

        # --- TABLES SECTION ---
        st.subheader("Yearly Pipeline Dynamics")
        st.dataframe(ye_df, use_container_width=True, hide_index=True)
        
        st.divider()
        
        st.subheader("Plant-Year Contributions Profiler")
        
        # Toolbar for table
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            plant_options = ["All Plants"] + list(py_df["plant_name"].unique())
            selected_plant = st.selectbox("Filter by Plant:", plant_options)
        with col_t2:
            # Range slider for years
            min_y = int(py_df["calendar_year"].min())
            max_y = int(py_df["calendar_year"].max())
            selected_years = st.slider("Filter by Calendar Year Range:", min_value=min_y, max_value=max_y, value=(min_y, max_y))
        with col_t3:
            show_inactive = st.checkbox("Show inactive years", value=False)
            
        # Apply filters
        filtered_py_df = py_df.copy()
        if selected_plant != "All Plants":
            filtered_py_df = filtered_py_df[filtered_py_df["plant_name"] == selected_plant]
            
        filtered_py_df = filtered_py_df[
            (filtered_py_df["calendar_year"] >= selected_years[0]) & 
            (filtered_py_df["calendar_year"] <= selected_years[1])
        ]
        
        if not show_inactive:
            filtered_py_df = filtered_py_df[filtered_py_df["active_in_year"] == True]
            
        st.dataframe(filtered_py_df, use_container_width=True, hide_index=True)

# ----------------- Tab 5: Decision Explanations -----------------
with tab_explain:
    st.header("💡 Why was this solution chosen?")
    st.markdown("Rule-based analysis explaining the fate of each plant based on system limits.")
    
    if st.session_state.run_results is None:
         st.info("No results available. Please run the optimization first.")
    else:
         explanations = st.session_state.run_results["explanations"]
         
         # Count summary
         num_selected = sum(1 for e in explanations if e.status == "Selected")
         num_not_selected = sum(1 for e in explanations if e.status == "Not Selected")
         num_filtered = sum(1 for e in explanations if e.status == "Filtered Out Early")
         st.markdown(f"**Total Plants:** {len(explanations)} | **Selected:** {num_selected} | **Not Selected:** {num_not_selected} | **Filtered:** {num_filtered}")
         st.divider()
         
         for exp in explanations:
             # Emoji Status
             emoji = "🟢" if exp.status == "Selected" else ("🔴" if exp.status == "Not Selected" else "⚪")
             expander_title = f"{emoji} [{exp.plant_id}] {exp.plant_name} — {exp.status}"
             
             with st.expander(expander_title, expanded=(exp.status == "Selected")):
                  col_a, col_b = st.columns(2)
                  
                  with col_a:
                       # 1. Core Explanation
                       st.markdown("### 📋 Core Explanation")
                       
                       if exp.reason_type == "exact":
                           badge = "🎯 **`Exact Reason`**"
                       elif exp.reason_type == "exact_in_current_schedule":
                           badge = "⏱️ **`Exact in Current Schedule`**"
                       else:
                           badge = "🧩 **`Inferred Reason`**"
                           
                       st.info(f"{badge}\n\n{exp.explanation_text}")
                       
                       # 2. Constraint Diagnostics
                       st.markdown("### 🩺 Constraint Diagnostics")
                       c_min = "✔️" if exp.passes_min_connection else "❌"
                       c_hub = "✔️" if exp.passes_hub_capacity_alone else "❌"
                       c_stor = "✔️" if exp.passes_storage_capacity_alone else "❌"
                       c_feas = "✔️" if exp.has_feasible_starts else "❌"
                       c_sel = "✔️" if exp.selected_in_final_optimum else "❌"
                       
                       st.markdown(f"{c_min} Passes minimum connection rule")
                       st.markdown(f"{c_hub} Passes annual hub capacity alone")
                       st.markdown(f"{c_stor} Passes global storage capacity alone")
                       st.markdown(f"{c_feas} Has feasible start years")
                       st.markdown(f"{c_sel} Selected in final optimum")

                  with col_b:
                       # 3. Supporting Facts
                       st.markdown("### 📊 Supporting Facts")
                       
                       facts_md = "| Metric | Value |\n|---|---|\n"
                       facts_md += f"| Earliest feasible start | {exp.earliest_feasible_start if exp.earliest_feasible_start else 'N/A'} |\n"
                       facts_md += f"| Latest feasible start | {exp.latest_feasible_start if exp.latest_feasible_start else 'N/A'} |\n"
                       facts_md += f"| Actual selected start | {exp.actual_selected_start if exp.actual_selected_start else 'N/A'} |\n"
                       
                       rem_life = exp.remaining_life_at_selected if exp.remaining_life_at_selected else exp.remaining_life_at_earliest
                       facts_md += f"| Remaining life at start | {rem_life if rem_life else 'N/A'} years |\n"
                       
                       facts_md += f"| Minimum connection time | {st.session_state.sys_params['minimum_connection_time_y']} years |\n"
                       facts_md += f"| Active years | {exp.active_years if exp.active_years else 'N/A'} |\n"
                       facts_md += f"| Annual captured CO2 | {exp.annual_captured_co2_mtpy:.3f} Mt/y |\n"
                       
                       min_stor_req = exp.annual_captured_co2_mtpy * st.session_state.sys_params['minimum_connection_time_y'] if exp.annual_captured_co2_mtpy else 0.0
                       facts_md += f"| Min. storage requirement | {min_stor_req:.3f} Mt |\n"
                       
                       if exp.max_possible_cumulative_co2_mt is not None:
                           facts_md += f"| Max possible cumulative | {exp.max_possible_cumulative_co2_mt:.3f} Mt |\n"
                       else:
                           facts_md += f"| Max possible cumulative | N/A |\n"
                           
                       facts_md += f"| Actual cumulative cap. | {exp.cumulative_captured_co2_mt if exp.cumulative_captured_co2_mt else '0.000'} Mt |\n"
                       
                       cap_cost = exp.capture_cost_euro_per_t if exp.capture_cost_euro_per_t is not None else 0.0
                       facts_md += f"| Capture cost | {cap_cost:.2f} €/t |\n"
                       
                       tot_cost = exp.total_capture_cost_euro if exp.total_capture_cost_euro else (exp.max_possible_cumulative_co2_mt * cap_cost * 1e6 if exp.max_possible_cumulative_co2_mt else 0.0)
                       tot_cost_label = "Total capture cost (Selected)" if exp.status == "Selected" else "Total capture cost (Potential)"
                       facts_md += f"| {tot_cost_label} | {tot_cost:,.0f} € |\n"
                       
                       st.markdown(facts_md)
                       
                       # 4. Feasible Start Analysis
                       st.markdown("### 📅 Feasible Start Analysis")
                       if exp.has_feasible_starts:
                           st.markdown(f"- **Feasible window:** {exp.earliest_feasible_start}–{exp.latest_feasible_start} ({exp.feasible_start_count} options)")
                           
                           if exp.status == "Selected" and exp.actual_selected_start == exp.earliest_feasible_start:
                               st.markdown("- **Earlier years blocked:** N/A")
                               st.markdown(f"- **Selected start:** {exp.actual_selected_start} (Earliest feasible year)")
                           else:
                               if exp.blocked_earlier_years:
                                   if len(exp.blocked_earlier_years) >= 2:
                                       block_str = f"{exp.blocked_earlier_years[0]}–{exp.blocked_earlier_years[-1]}"
                                   else:
                                       block_str = str(exp.blocked_earlier_years[0])
                                   st.markdown(f"- **Blocked earlier years in current schedule:** {block_str}")
                               else:
                                   if exp.status == "Selected":
                                       st.markdown("- **Blocked earlier years in current schedule:** None (Likely equivalent optimum)")
                                   else:
                                       st.markdown("- **Blocked earlier years in current schedule:** None")
                                       
                               st.markdown(f"- **Selected start:** {exp.actual_selected_start if exp.status == 'Selected' else 'Not Selected'}")
                       else:
                           st.markdown("- **Feasible window:** None available")
