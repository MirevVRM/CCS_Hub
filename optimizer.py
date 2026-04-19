import pulp
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from models import Plant, SystemParameters, PlantOptResult, YearlyOptResult, SystemSummaryResult

# Epsilon parameter to ensure numerical stability when fixing maximum capacity for stage 2
EPSILON = 1e-5

@dataclass
class ModelData:
    plants: List[Plant]
    sys: SystemParameters
    
    # Derived parameters
    captured_co2_mtpy: Dict[int, float]
    residual_co2_mtpy: Dict[int, float]
    
    # Allowed starts
    allowed_starts: List[Tuple[int, int]]  # (plant_id, year_index)
    active_years_if_started: Dict[Tuple[int, int], int]
    captured_co2_if_started_mt: Dict[Tuple[int, int], float]
    capture_cost_if_started_euro: Dict[Tuple[int, int], float]

def prepare_model_data(plants: List[Plant], sys: SystemParameters) -> ModelData:
    captured_co2_mtpy = {}
    residual_co2_mtpy = {}
    
    allowed_starts = []
    active_years_if_started = {}
    captured_co2_if_started_mt = {}
    capture_cost_if_started_euro = {}

    for p in plants:
        captured_co2_mtpy[p.id] = p.co2_flow_mtpy * sys.capture_efficiency
        residual_co2_mtpy[p.id] = p.co2_flow_mtpy * (1 - sys.capture_efficiency)

        # Check all possible start years (1-indexed)
        # 1-indexed year_index = 1..T
        # We also want to skip plants if their Q_i > sys.annual_hub_capacity_mtpy
        if captured_co2_mtpy[p.id] > sys.annual_hub_capacity_mtpy:
            continue
            
        for t in range(1, sys.planning_horizon_y + 1):
            life_at_start = p.remaining_life_y - (t - 1)
            
            if life_at_start <= 0:
                continue
                
            l_pt = min(life_at_start, sys.planning_horizon_y - t + 1)
            # Apply minimum connection time condition
            if l_pt >= sys.minimum_connection_time_y:
                pt_tuple = (p.id, t)
                
                # Presolve step: Removes starts where a SINGLE plant exceeds the entire global storage
                cum_captured = captured_co2_mtpy[p.id] * l_pt
                if cum_captured <= sys.cumulative_storage_capacity_mt:
                    allowed_starts.append(pt_tuple)
                    active_years_if_started[pt_tuple] = l_pt
                    captured_co2_if_started_mt[pt_tuple] = cum_captured
                    capture_cost_if_started_euro[pt_tuple] = (
                        p.capture_cost_euro_per_t * captured_co2_mtpy[p.id] * l_pt * 1_000_000
                    )
                    
    return ModelData(
        plants=plants,
        sys=sys,
        captured_co2_mtpy=captured_co2_mtpy,
        residual_co2_mtpy=residual_co2_mtpy,
        allowed_starts=allowed_starts,
        active_years_if_started=active_years_if_started,
        captured_co2_if_started_mt=captured_co2_if_started_mt,
        capture_cost_if_started_euro=capture_cost_if_started_euro
    )

def build_and_solve_optimizations(model_data: ModelData) -> Optional[Dict[Tuple[int, int], float]]:
    if not model_data.allowed_starts:
        print("[Warning] No allowed starts after filtering. Returning empty solution without calling solver.")
        return {}

    # ------------------ STAGE 1: Maximize Captured CO2 ------------------
    stage1 = pulp.LpProblem("Max_Captured_CO2", pulp.LpMaximize)
    
    # Decision variables y_{i,t}
    start_decision = pulp.LpVariable.dicts(
        "start",
        model_data.allowed_starts,
        lowBound=0,
        upBound=1,
        cat=pulp.LpBinary
    )
    
    # Calculate Total Captured CO2
    total_captured_expr = pulp.lpSum(
        start_decision[pt] * model_data.captured_co2_if_started_mt[pt]
        for pt in model_data.allowed_starts
    )
    
    # Objective Stage 1
    stage1 += total_captured_expr

    # Constraints
    # 1. Single start per plant
    for p in model_data.plants:
        plant_starts = [pt for pt in model_data.allowed_starts if pt[0] == p.id]
        if plant_starts:
            stage1 += pulp.lpSum(start_decision[pt] for pt in plant_starts) <= 1, f"SingleStart_P{p.id}"

    # 2. Cumulative storage capacity
    stage1 += total_captured_expr <= model_data.sys.cumulative_storage_capacity_mt, "StorageLimit"

    # 3. Annual Hub Capacity
    for t in range(1, model_data.sys.planning_horizon_y + 1):
        # We need to sum Q_i * y_{i,s} for all active (i,s) in year t
        # (i,s) is active in year t if: s <= t <= s + l_{i,s} - 1
        active_in_t = []
        for pt in model_data.allowed_starts:
            i, s = pt
            l_is = model_data.active_years_if_started[pt]
            if s <= t <= s + l_is - 1:
                # Active!
                active_in_t.append(start_decision[pt] * model_data.captured_co2_mtpy[i])
                
        if active_in_t:
            stage1 += pulp.lpSum(active_in_t) <= model_data.sys.annual_hub_capacity_mtpy, f"HubCapacity_Y{t}"

    print(f"Solving Stage 1 with {len(model_data.allowed_starts)} possible start decisions...")
    solver_status_1 = stage1.solve(pulp.PULP_CBC_CMD(msg=False))
    
    print(f"[Solver Status Stage 1]: {pulp.LpStatus[solver_status_1]}")
    if pulp.LpStatus[solver_status_1] != "Optimal":
        print(f"[Optimization Error]: Stage 1 could not find an optimal solution (possible infeasibility).")
        return None
        
    max_total_captured_co2 = pulp.value(total_captured_expr)
    print(f"Stage 1 completed. Max Captured CO2: {max_total_captured_co2:.4f} Mt")

    # ------------------ STAGE 2: Minimize Cost ------------------
    # Now we minimize cost, subject to maintaining the max CO2 captured in Stage 1
    stage2 = pulp.LpProblem("Min_Cost", pulp.LpMinimize)
    
    start_decision_2 = pulp.LpVariable.dicts(
        "start",
        model_data.allowed_starts,
        lowBound=0,
        upBound=1,
        cat=pulp.LpBinary
    )

    total_captured_expr_2 = pulp.lpSum(
        start_decision_2[pt] * model_data.captured_co2_if_started_mt[pt]
        for pt in model_data.allowed_starts
    )
    
    total_cost_expr_2 = pulp.lpSum(
        start_decision_2[pt] * model_data.capture_cost_if_started_euro[pt]
        for pt in model_data.allowed_starts
    )

    # Objective Stage 2
    stage2 += total_cost_expr_2

    # Add constraints from stage 1
    for p in model_data.plants:
        plant_starts = [pt for pt in model_data.allowed_starts if pt[0] == p.id]
        if plant_starts:
            stage2 += pulp.lpSum(start_decision_2[pt] for pt in plant_starts) <= 1, f"SingleStart_P{p.id}"

    stage2 += total_captured_expr_2 <= model_data.sys.cumulative_storage_capacity_mt, "StorageLimit"

    for t in range(1, model_data.sys.planning_horizon_y + 1):
        active_in_t = []
        for pt in model_data.allowed_starts:
            i, s = pt
            l_is = model_data.active_years_if_started[pt]
            if s <= t <= s + l_is - 1:
                active_in_t.append(start_decision_2[pt] * model_data.captured_co2_mtpy[i])
                
        if active_in_t:
            stage2 += pulp.lpSum(active_in_t) <= model_data.sys.annual_hub_capacity_mtpy, f"HubCapacity_Y{t}"

    # New constraint: Ensure Q >= Q_max - epsilon to avoid float inaccuracies
    stage2 += total_captured_expr_2 >= max_total_captured_co2 - EPSILON, "MaxCapturedTarget"

    print("\nSolving Stage 2 (Minimize Cost)...")
    solver_status_2 = stage2.solve(pulp.PULP_CBC_CMD(msg=False))
    
    print(f"[Solver Status Stage 2]: {pulp.LpStatus[solver_status_2]}")
    if pulp.LpStatus[solver_status_2] != "Optimal":
        print(f"[Optimization Error]: Stage 2 could not find an optimal solution.")
        return None

    # NOTE ON MULTIPLE EQUIVALENT OPTIMA:
    # If there are combinations of start years across different plants that yield the exact same Max CO2 Capture
    # and the exact same Lowest Capture Cost, the MILP solver may return ANY of those equivalent solutions.
    # The current objective function does NOT strictly prefer the earliest possible connection year
    # among optimal solutions. 
    #
    # TIE-BREAKER FUTURE CONCEPT (To be discussed with business):
    # To intentionally force the model to prefer an earlier start when costs and volumes are equal, 
    # we could subtract a small deterministic penalty parameter in the Stage 2 objective function.
    # For instance: 
    # total_cost_expr_2 += pulp.lpSum(start_decision_2[(i, t)] * t * PENALTY_FACTOR ...)

    # Return solution
    print("[Success]: Both stages completed successfully.")
    solution = {}
    for pt in model_data.allowed_starts:
        solution[pt] = pulp.value(start_decision_2[pt])
        
    return solution

def generate_results(model_data: ModelData, solution: Dict[Tuple[int, int], float]) -> Tuple[List[PlantOptResult], List[YearlyOptResult], SystemSummaryResult]:
    plant_results = []
    
    # Store assigned start years
    assigned_starts = {}  # plant_id -> year_index
    for pt, val in solution.items():
        if val is not None and val > 0.5:  # Binary 1
            assigned_starts[pt[0]] = pt[1]

    total_captured = 0.0
    total_cost = 0.0

    # Build plant results
    for p in model_data.plants:
        start_t = assigned_starts.get(p.id)
        if start_t is not None:
            pt = (p.id, start_t)
            l_pt = model_data.active_years_if_started[pt]
            annual_cap = model_data.captured_co2_mtpy[p.id]
            annual_res = model_data.residual_co2_mtpy[p.id]
            cum_cap = model_data.captured_co2_if_started_mt[pt]
            cum_res = annual_res * l_pt
            cost = model_data.capture_cost_if_started_euro[pt]
            
            res = PlantOptResult(
                plant_id=p.id,
                plant_name=p.name,
                selected=True,
                start_year_index=start_t,
                start_calendar_year=model_data.sys.start_year + start_t - 1,
                active_years=l_pt,
                annual_generated_co2_mtpy=p.co2_flow_mtpy,
                annual_captured_co2_mtpy=annual_cap,
                annual_residual_co2_mtpy=annual_res,
                cumulative_captured_co2_mt=cum_cap,
                cumulative_residual_co2_mt=cum_res,
                total_capture_cost_euro=cost
            )
            total_captured += cum_cap
            total_cost += cost
        else:
            res = PlantOptResult(
                plant_id=p.id,
                plant_name=p.name,
                selected=False,
                start_year_index=None,
                start_calendar_year=None,
                active_years=0,
                annual_generated_co2_mtpy=p.co2_flow_mtpy,
                annual_captured_co2_mtpy=0.0,
                annual_residual_co2_mtpy=p.co2_flow_mtpy,
                cumulative_captured_co2_mt=0.0,
                cumulative_residual_co2_mt=p.co2_flow_mtpy * min(p.remaining_life_y, model_data.sys.planning_horizon_y),
                total_capture_cost_euro=0.0
            )
        plant_results.append(res)

    # Build yearly results
    yearly_results = []
    for t in range(1, model_data.sys.planning_horizon_y + 1):
        hub_load = 0.0
        for p_id, start_s in assigned_starts.items():
            l_is = model_data.active_years_if_started[(p_id, start_s)]
            # Check if plant runs in year index t
            if start_s <= t <= start_s + l_is - 1:
                hub_load += model_data.captured_co2_mtpy[p_id]
                
        yearly_results.append(YearlyOptResult(
            year_index=t,
            calendar_year=model_data.sys.start_year + t - 1,
            hub_load_mtpy=hub_load,
            free_capacity_mtpy=model_data.sys.annual_hub_capacity_mtpy - hub_load
        ))

    # Summary
    avg_cost = (total_cost / (total_captured * 1e6)) if total_captured > 0 else 0.0
    summary = SystemSummaryResult(
        total_captured_co2_mt=total_captured,
        total_capture_cost_euro=total_cost,
        average_capture_cost_euro_per_t=avg_cost,
        storage_used_mt=total_captured,
        storage_remaining_mt=model_data.sys.cumulative_storage_capacity_mt - total_captured
    )

    return plant_results, yearly_results, summary
