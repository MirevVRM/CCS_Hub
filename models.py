from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Plant:
    id: int
    name: str
    co2_flow_mtpy: float
    capture_cost_euro_per_t: float
    remaining_life_y: int
    max_co2_mt: float

@dataclass
class SystemParameters:
    planning_horizon_y: int
    start_year: int
    annual_hub_capacity_mtpy: float
    cumulative_storage_capacity_mt: float
    minimum_connection_time_y: int
    capture_efficiency: float

@dataclass
class PlantOptResult:
    plant_id: int
    plant_name: str
    selected: bool
    start_year_index: Optional[int]
    start_calendar_year: Optional[int]
    active_years: int
    annual_generated_co2_mtpy: float
    annual_captured_co2_mtpy: float
    annual_residual_co2_mtpy: float
    cumulative_captured_co2_mt: float
    cumulative_residual_co2_mt: float
    total_capture_cost_euro: float

@dataclass
class YearlyOptResult:
    year_index: int
    calendar_year: int
    hub_load_mtpy: float
    free_capacity_mtpy: float

@dataclass
class SystemSummaryResult:
    total_captured_co2_mt: float
    total_capture_cost_euro: float
    average_capture_cost_euro_per_t: float
    storage_used_mt: float
    storage_remaining_mt: float
