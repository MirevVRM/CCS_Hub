import json
import math
import dataclasses
import io
import zipfile
import pandas as pd
from typing import Tuple, List, Dict
from models import Plant, SystemParameters, PlantOptResult, YearlyOptResult, SystemSummaryResult

def load_data_from_json(filepath: str) -> Tuple[List[Plant], SystemParameters]:
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    sys_params_data = data["system_parameters"]
    system_parameters = SystemParameters(
        planning_horizon_y=sys_params_data["planning_horizon_y"],
        start_year=sys_params_data["start_year"],
        annual_hub_capacity_mtpy=sys_params_data["annual_hub_capacity_mtpy"],
        cumulative_storage_capacity_mt=sys_params_data["cumulative_storage_capacity_mt"],
        minimum_connection_time_y=sys_params_data["minimum_connection_time_y"],
        capture_efficiency=sys_params_data["capture_efficiency"]
    )

    plants = []
    for p_data in data["plants"]:
        plant = Plant(
            id=p_data["id"],
            name=p_data["name"],
            co2_flow_mtpy=p_data["co2_flow_mtpy"],
            capture_cost_euro_per_t=p_data["capture_cost_euro_per_t"],
            remaining_life_y=p_data["remaining_life_y"],
            max_co2_mt=p_data.get("max_co2_mt", p_data["co2_flow_mtpy"] * p_data["remaining_life_y"])
        )
        plants.append(plant)

    return plants, system_parameters

def validate_input_data(plants: List[Plant], sys: SystemParameters):
    if sys.planning_horizon_y <= 0:
        raise ValueError("planning_horizon_y must be > 0")
    if sys.annual_hub_capacity_mtpy <= 0:
        raise ValueError("annual_hub_capacity_mtpy must be > 0")
    if sys.cumulative_storage_capacity_mt <= 0:
        raise ValueError("cumulative_storage_capacity_mt must be > 0")
    if sys.minimum_connection_time_y <= 0:
        raise ValueError("minimum_connection_time_y must be > 0")
    if not (0 < sys.capture_efficiency <= 1):
        raise ValueError("capture_efficiency must be between 0 and 1")

    for p in plants:
        if p.co2_flow_mtpy <= 0:
            raise ValueError(f"Plant {p.id}: co2_flow_mtpy must be > 0")
        if p.capture_cost_euro_per_t <= 0:
            raise ValueError(f"Plant {p.id}: capture_cost_euro_per_t must be > 0")
        if p.remaining_life_y <= 0:
            raise ValueError(f"Plant {p.id}: remaining_life_y must be > 0")
        
        # Check consistency of user-provided max_co2_mt against generated co2
        # Note: According to TS, max_co2_mt = co2_flow_mtpy * remaining_life_y stands for generating CO2, 
        # NOT captured CO2. Models will use captured CO2 via capture efficiency instead.
        expected_max_co2 = p.co2_flow_mtpy * p.remaining_life_y
        if not math.isclose(p.max_co2_mt, expected_max_co2, rel_tol=1e-3):
            print(f"[Validation Warning]: Plant {p.id} max_co2_mt ({p.max_co2_mt}) differs from "
                  f"generated CO2 flow * remaining_life_y ({expected_max_co2}).")

def print_results(plant_results: List[PlantOptResult], yearly_results: List[YearlyOptResult], summary: SystemSummaryResult):
    print("\n" + "="*80)
    print("PLANT RESULTS:")
    print("="*80)
    for pr in plant_results:
        status = 'Selected' if pr.selected else 'Not Selected'
        print(f"[{pr.plant_id}] {pr.plant_name} | {status}")
        if pr.selected:
            print(f"  -> Start Year: {pr.start_calendar_year} (Index: {pr.start_year_index})")
            print(f"  -> Active Years: {pr.active_years}")
            print(f"  -> Annual Captured CO2: {pr.annual_captured_co2_mtpy:.3f} Mt/y (Remaining: {pr.annual_residual_co2_mtpy:.3f} Mt/y)")
            print(f"  -> Cumul. Captured CO2: {pr.cumulative_captured_co2_mt:.3f} Mt (Remaining: {pr.cumulative_residual_co2_mt:.3f} Mt)")
            print(f"  -> Total Capture Cost: {pr.total_capture_cost_euro:,.2f} Euro")
        print("-" * 80)

    print("\n" + "="*80)
    print("YEARLY HUB LOAD:")
    print("="*80)
    print(f"{'Year Index':<12} | {'Calendar Year':<15} | {'Hub Load (Mt/y)':<20} | {'Free Capacity (Mt/y)':<20}")
    print("-" * 80)
    for yr in yearly_results:
        print(f"{yr.year_index:<12} | {yr.calendar_year:<15} | {yr.hub_load_mtpy:<20.3f} | {yr.free_capacity_mtpy:<20.3f}")

    print("\n" + "="*80)
    print("SYSTEM SUMMARY:")
    print("="*80)
    print(f"Total Captured CO2: {summary.total_captured_co2_mt:.3f} Mt")
    print(f"Total Capture Cost: {summary.total_capture_cost_euro:,.2f} Euro")
    print(f"Average Capture Cost: {summary.average_capture_cost_euro_per_t:.2f} Euro/t")
    print(f"Storage Used: {summary.storage_used_mt:.3f} Mt")
    print(f"Storage Remaining: {summary.storage_remaining_mt:.3f} Mt")
    print("="*80 + "\n")

def save_results_to_json(plant_results: List[PlantOptResult], yearly_results: List[YearlyOptResult], summary: SystemSummaryResult, plant_year_df, yearly_expanded_df, explanations, filepath: str):
    output_data = {
        "system_summary": dataclasses.asdict(summary),
        "plant_results": [dataclasses.asdict(pr) for pr in plant_results],
        "yearly_hub_load": yearly_expanded_df.to_dict(orient="records"),
        "plant_year_contributions": plant_year_df.to_dict(orient="records"),
        "decision_explanations": [dataclasses.asdict(e) for e in explanations]
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

def load_scenario_from_excel(file_stream) -> Tuple[List[Plant], SystemParameters]:
    try:
        sys_df = pd.read_excel(file_stream, sheet_name="SystemParameters")
        sys_dict = dict(zip(sys_df.iloc[:, 0], sys_df.iloc[:, 1]))
        
        system_parameters = SystemParameters(
            planning_horizon_y=int(sys_dict["planning_horizon_y"]),
            start_year=int(sys_dict["start_year"]),
            annual_hub_capacity_mtpy=float(sys_dict["annual_hub_capacity_mtpy"]),
            cumulative_storage_capacity_mt=float(sys_dict["cumulative_storage_capacity_mt"]),
            minimum_connection_time_y=int(sys_dict["minimum_connection_time_y"]),
            capture_efficiency=float(sys_dict["capture_efficiency"])
        )
    except Exception as e:
        raise ValueError(f"Error parsing SystemParameters sheet: {e}")
        
    try:
        plants_df = pd.read_excel(file_stream, sheet_name="Plants")
        plants = []
        for _, row in plants_df.iterrows():
            plant = Plant(
                id=int(row["id"]),
                name=str(row["name"]),
                co2_flow_mtpy=float(row["co2_flow_mtpy"]),
                capture_cost_euro_per_t=float(row["capture_cost_euro_per_t"]),
                remaining_life_y=int(row["remaining_life_y"]),
                max_co2_mt=float(row.get("max_co2_mt", float(row["co2_flow_mtpy"]) * int(row["remaining_life_y"])))
            )
            plants.append(plant)
    except Exception as e:
        raise ValueError(f"Error parsing Plants sheet: {e}")
        
    return plants, system_parameters

def load_plants_from_csv(file_stream) -> List[Plant]:
    try:
        plants_df = pd.read_csv(file_stream)
        plants = []
        for _, row in plants_df.iterrows():
            plant = Plant(
                id=int(row["id"]),
                name=str(row["name"]),
                co2_flow_mtpy=float(row["co2_flow_mtpy"]),
                capture_cost_euro_per_t=float(row["capture_cost_euro_per_t"]),
                remaining_life_y=int(row["remaining_life_y"]),
                max_co2_mt=float(row.get("max_co2_mt", float(row["co2_flow_mtpy"]) * int(row["remaining_life_y"])))
            )
            plants.append(plant)
        return plants
    except Exception as e:
        raise ValueError(f"Error parsing Plants CSV: {e}")

def save_results_to_excel(plant_results, yearly_results, summary, plant_year_df, yearly_expanded_df, explanations, file_stream):
    with pd.ExcelWriter(file_stream, engine='xlsxwriter') as writer:
        summary_df = pd.DataFrame([dataclasses.asdict(summary)])
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        
        pr_df = pd.DataFrame([dataclasses.asdict(pr) for pr in plant_results])
        pr_df.to_excel(writer, sheet_name="PlantResults", index=False)
        
        yearly_expanded_df.to_excel(writer, sheet_name="YearlyResults", index=False)
        plant_year_df.to_excel(writer, sheet_name="PlantYearContributions", index=False)
        
        exp_df = pd.DataFrame([dataclasses.asdict(e) for e in explanations])
        exp_df.to_excel(writer, sheet_name="DecisionExplanations", index=False)

def save_results_to_csv_zip(plant_results, yearly_results, summary, plant_year_df, yearly_expanded_df, explanations, file_stream):
    with zipfile.ZipFile(file_stream, 'w', zipfile.ZIP_DEFLATED) as zf:
        summary_df = pd.DataFrame([dataclasses.asdict(summary)])
        zf.writestr('summary.csv', summary_df.to_csv(index=False))
        
        pr_df = pd.DataFrame([dataclasses.asdict(pr) for pr in plant_results])
        zf.writestr('plant_results.csv', pr_df.to_csv(index=False))
        
        zf.writestr('yearly_results.csv', yearly_expanded_df.to_csv(index=False))
        zf.writestr('plant_year_contributions.csv', plant_year_df.to_csv(index=False))
        
        exp_df = pd.DataFrame([dataclasses.asdict(e) for e in explanations])
        zf.writestr('decision_explanations.csv', exp_df.to_csv(index=False))

def create_excel_template() -> io.BytesIO:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        sys_data = {
            "Parameter": [
                "planning_horizon_y", "start_year", "annual_hub_capacity_mtpy", 
                "cumulative_storage_capacity_mt", "minimum_connection_time_y", "capture_efficiency"
            ],
            "Value": [25, 2025, 50.0, 1000.0, 10, 0.9]
        }
        pd.DataFrame(sys_data).to_excel(writer, sheet_name="SystemParameters", index=False)
        
        plants_data = {
            "id": [1, 2],
            "name": ["Example Plant A", "Example Plant B"],
            "co2_flow_mtpy": [5.0, 3.0],
            "capture_cost_euro_per_t": [45.0, 50.0],
            "remaining_life_y": [20, 15]
        }
        pd.DataFrame(plants_data).to_excel(writer, sheet_name="Plants", index=False)
    output.seek(0)
    return output
