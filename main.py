import sys
from data_io import load_data_from_json, load_scenario_from_excel, validate_input_data, print_results, save_results_to_json
from optimizer import prepare_model_data, build_and_solve_optimizations, generate_results
from explainer import generate_explanations

def main():
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = "test_scenario.json"
        
    print(f"Loading data from {file_path}...")
    try:
        if file_path.endswith('.xlsx'):
            plants, sys_params = load_scenario_from_excel(file_path)
        else:
            plants, sys_params = load_data_from_json(file_path)
    except FileNotFoundError:
        print(f"Error: File {file_path} not found.")
        return
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    try:
        validate_input_data(plants, sys_params)
    except Exception as e:
        print(f"Data validation failed: {e}")
        return

    print("Data validated successfully. Preparing model data...")
    model_data = prepare_model_data(plants, sys_params)

    if not model_data.allowed_starts:
        print("No valid connection options (minimum connection time or capacity failures). Exiting.")
        return

    print("Executing Optimization Stages...")
    solution = build_and_solve_optimizations(model_data)

    if solution is None:
        print("\nOptimization could not find a feasible solution.")
        print("This could be due to too restrictive constraints (e.g., storage capacity is too low, or minimum connection time cannot be satisfied with the limits).")
        return

    # Extract results
    plant_results, yearly_results, summary = generate_results(model_data, solution)
    
    # Save results to JSON
    output_filename = "results.json"
    print(f"\nSaving results to {output_filename}...")
    
    import pandas as pd
    from dataclasses import asdict
    # Convert similarly to how we did for Streamlit Analytics
    y_df = pd.DataFrame([asdict(y) for y in yearly_results])
    y_df['cumulative_storage_used_mt'] = y_df['hub_load_mtpy'].cumsum()
    y_df['storage_remaining_mt'] = sys_params.cumulative_storage_capacity_mt - y_df['cumulative_storage_used_mt']
    flat_data = []
    for p in plant_results:
        cum_cap_plant = 0.0
        for yr in yearly_results:
            is_active = False
            contribution = 0.0
            if p.selected and p.start_calendar_year is not None:
                if p.start_calendar_year <= yr.calendar_year < (p.start_calendar_year + p.active_years):
                    is_active = True
                    contribution = p.annual_captured_co2_mtpy
                    cum_cap_plant += contribution
            flat_data.append({
                "plant_id": p.plant_id, "plant_name": p.plant_name, "calendar_year": yr.calendar_year,
                "selected": p.selected, "active_in_year": is_active,
                "generated_co2_mtpy": p.annual_generated_co2_mtpy if is_active else 0.0,
                "captured_co2_mtpy": p.annual_captured_co2_mtpy if is_active else 0.0,
                "residual_co2_mtpy": p.annual_residual_co2_mtpy if is_active else 0.0,
                "contribution_to_hub_load_mtpy": contribution,
                "cumulative_captured_to_date_by_plant": cum_cap_plant
            })
    flat_df = pd.DataFrame(flat_data)
    
    # Generate explanations
    explanations = generate_explanations(plants, plant_results, sys_params, y_df, summary.storage_remaining_mt)
    
    save_results_to_json(plant_results, yearly_results, summary, flat_df, y_df, explanations, output_filename)
    
    # Print out nicely
    print_results(plant_results, yearly_results, summary)

if __name__ == "__main__":
    main()
