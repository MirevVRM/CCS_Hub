from dataclasses import dataclass, asdict
from typing import List, Optional
import pandas as pd
from models import Plant, SystemParameters, PlantOptResult, YearlyOptResult

@dataclass
class DecisionExplanation:
    plant_id: int
    plant_name: str
    status: str # "Selected", "Not Selected", "Filtered Out Early"
    reason_type: str # "exact", "exact_in_current_schedule", "inferred"
    explanation_text: str
    
    # Supporting Facts
    earliest_feasible_start: Optional[int] = None
    latest_feasible_start: Optional[int] = None
    actual_selected_start: Optional[int] = None
    remaining_life_at_earliest: Optional[int] = None
    remaining_life_at_selected: Optional[int] = None
    active_years: Optional[int] = None
    annual_captured_co2_mtpy: Optional[float] = None
    max_possible_cumulative_co2_mt: Optional[float] = None
    cumulative_captured_co2_mt: Optional[float] = None
    capture_cost_euro_per_t: Optional[float] = None
    total_capture_cost_euro: Optional[float] = None
    
    # Constraint Diagnostics
    passes_min_connection: bool = False
    passes_hub_capacity_alone: bool = False
    passes_storage_capacity_alone: bool = False
    has_feasible_starts: bool = False
    selected_in_final_optimum: bool = False
    
    # Feasible Start Analysis
    feasible_start_count: int = 0
    blocked_earlier_years: Optional[List[int]] = None

def generate_explanations(plants: List[Plant], 
                          opt_results: List[PlantOptResult], 
                          sys_params: SystemParameters, 
                          yearly_expanded_df: pd.DataFrame,
                          total_storage_remaining: float) -> List[DecisionExplanation]:
    
    explanations = []
    
    # Create a quick lookup for results
    result_dict = {res.plant_id: res for res in opt_results}
    
    for plant in plants:
        res = result_dict.get(plant.id)
        
        # Determine theoretically allowed starts purely based on plant limits (Pre-processing check)
        min_conn = sys_params.minimum_connection_time_y
        max_active = min(plant.remaining_life_y, sys_params.planning_horizon_y)
        theoretical_allowed_starts = []
        
        cap_eff = sys_params.capture_efficiency
        annual_cap = plant.co2_flow_mtpy * cap_eff
        
        # Hard limits check exactly as in optimizer
        passes_min_conn = max_active >= min_conn
        passes_hub_cap = annual_cap <= sys_params.annual_hub_capacity_mtpy
        passes_storage = (annual_cap * min_conn) <= sys_params.cumulative_storage_capacity_mt
        
        failed_min_time = not passes_min_conn
        failed_hub_cap = not passes_hub_cap
        failed_storage = not passes_storage
        
        # Status A: Filtered Out Early
        if failed_min_time or failed_hub_cap or failed_storage:
            reason = []
            if failed_min_time:
                reason.append(f"remaining life ({plant.remaining_life_y}y) < minimum connection time ({min_conn}y)")
            if failed_hub_cap:
                reason.append(f"annual capture ({annual_cap:.2f} Mt) > hub capacity ({sys_params.annual_hub_capacity_mtpy:.2f} Mt)")
            if failed_storage:
                reason.append(f"minimum absolute storage volume needed > total system storage capacity")
                
            reason_text = " and ".join(reason)
            exp = DecisionExplanation(
                plant_id=plant.id,
                plant_name=plant.name,
                status="Filtered Out Early",
                reason_type="exact",
                explanation_text=f"Plant was excluded before optimization because {reason_text}.",
                annual_captured_co2_mtpy=annual_cap,
                capture_cost_euro_per_t=plant.capture_cost_euro_per_t,
                passes_min_connection=passes_min_conn,
                passes_hub_capacity_alone=passes_hub_cap,
                passes_storage_capacity_alone=passes_storage,
                has_feasible_starts=False,
                selected_in_final_optimum=False
            )
            explanations.append(exp)
            continue
            
        # Calculate earliest feasible start based on horizon
        for calendar_year in range(sys_params.start_year, sys_params.start_year + sys_params.planning_horizon_y):
            t_index = calendar_year - sys_params.start_year + 1
            life_at_start = plant.remaining_life_y - (t_index - 1)
            
            if life_at_start <= 0:
                continue
                
            years_active = min(life_at_start, sys_params.start_year + sys_params.planning_horizon_y - calendar_year)
            if years_active >= sys_params.minimum_connection_time_y:
                theoretical_allowed_starts.append(calendar_year)
                
        if not theoretical_allowed_starts:
            exp = DecisionExplanation(
                plant_id=plant.id, plant_name=plant.name, status="Filtered Out Early", reason_type="exact",
                explanation_text="Plant cannot meet minimum connection time within the planning horizon.",
                annual_captured_co2_mtpy=annual_cap,
                capture_cost_euro_per_t=plant.capture_cost_euro_per_t,
                passes_min_connection=passes_min_conn,
                passes_hub_capacity_alone=passes_hub_cap,
                passes_storage_capacity_alone=passes_storage,
                has_feasible_starts=False,
                selected_in_final_optimum=False
            )
            explanations.append(exp)
            continue
            
        earliest_start = theoretical_allowed_starts[0]
        latest_start = theoretical_allowed_starts[-1]
        early_life = plant.remaining_life_y - (earliest_start - sys_params.start_year)
        max_possible_cum = min(early_life, sys_params.start_year + sys_params.planning_horizon_y - earliest_start) * annual_cap
        
        # Status B/C: Reached optimizer
        if res and res.selected:
            # Plant is Selected
            actual_start = res.start_calendar_year
            rem_life_sel = plant.remaining_life_y - (actual_start - sys_params.start_year)
            
            exp = DecisionExplanation(
                plant_id=plant.id, plant_name=plant.name, status="Selected",
                earliest_feasible_start=earliest_start,
                latest_feasible_start=latest_start,
                actual_selected_start=actual_start,
                remaining_life_at_earliest=early_life,
                remaining_life_at_selected=rem_life_sel,
                active_years=res.active_years,
                annual_captured_co2_mtpy=res.annual_captured_co2_mtpy,
                max_possible_cumulative_co2_mt=max_possible_cum,
                cumulative_captured_co2_mt=res.cumulative_captured_co2_mt,
                capture_cost_euro_per_t=plant.capture_cost_euro_per_t,
                total_capture_cost_euro=res.total_capture_cost_euro,
                reason_type="exact",
                explanation_text="",
                passes_min_connection=passes_min_conn,
                passes_hub_capacity_alone=passes_hub_cap,
                passes_storage_capacity_alone=passes_storage,
                has_feasible_starts=True,
                selected_in_final_optimum=True,
                feasible_start_count=len(theoretical_allowed_starts),
                blocked_earlier_years=[]
            )
            
            if actual_start == earliest_start:
                exp.explanation_text = "Plant was selected and started at the earliest feasible year. There were no conflicting constraints blocking early connection."
            else:
                # Need to check why it was delayed
                blocked_years = []
                for y in theoretical_allowed_starts:
                    if y >= actual_start:
                        break
                    # check capacity in that year
                    cap_in_y = yearly_expanded_df.loc[yearly_expanded_df['calendar_year'] == y, 'free_capacity_mtpy'].values[0]
                    if cap_in_y < res.annual_captured_co2_mtpy:
                         blocked_years.append(y)
                
                exp.blocked_earlier_years = blocked_years
                
                if blocked_years:
                     exp.explanation_text = f"Start was delayed to {actual_start}. In the currently selected optimal schedule, earlier connection in years {blocked_years} is blocked because the Annual Hub Capacity is saturated. Note this constraint is relative to the optimum found."
                     exp.reason_type = "exact_in_current_schedule"
                else:
                     exp.explanation_text = f"Start was delayed to {actual_start} even though earlier years appear feasible based on Hub Capacity alone. This indicates an equivalent optimum where shifting the start year did not change the objective, or it was pushed to accommodate another plant."
                     exp.reason_type = "inferred"
                     
            explanations.append(exp)
            
        else:
            # Plant is Not Selected
            exp = DecisionExplanation(
                plant_id=plant.id, plant_name=plant.name, status="Not Selected",
                earliest_feasible_start=earliest_start,
                latest_feasible_start=latest_start,
                remaining_life_at_earliest=early_life,
                annual_captured_co2_mtpy=annual_cap,
                max_possible_cumulative_co2_mt=max_possible_cum,
                capture_cost_euro_per_t=plant.capture_cost_euro_per_t,
                reason_type="", explanation_text="",
                passes_min_connection=passes_min_conn,
                passes_hub_capacity_alone=passes_hub_cap,
                passes_storage_capacity_alone=passes_storage,
                has_feasible_starts=True,
                selected_in_final_optimum=False,
                feasible_start_count=len(theoretical_allowed_starts),
                blocked_earlier_years=[]
            )
            
            # Why was it rejected?
            min_storage_needed = annual_cap * sys_params.minimum_connection_time_y
            
            if total_storage_remaining < min_storage_needed:
                exp.reason_type = "inferred"
                exp.explanation_text = f"The plant had {len(theoretical_allowed_starts)} feasible start options but was not included. The global Cumulative Storage Capacity was nearly exhausted, and this plant likely lost its place to a more cost-effective combination of competitors."
            else:
                exp.reason_type = "inferred"
                exp.explanation_text = f"The plant had {len(theoretical_allowed_starts)} feasible start options but was not included in the optimal solution. Under the current system-wide limits (Hub Capacity), other combinations provided a better objective value (more CO2 captured or lower cost)."
                
            explanations.append(exp)

    return explanations
