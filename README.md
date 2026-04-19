# CCS Hub Optimization Tool (v1.0)

## Overview
This project provides an optimization model (Two-Stage MILP) designed to determine the optimal schedule for retrofitting industrial sources with CO₂ capture and connecting them to a central CCS hub. 

The model maximizes the total captured CO₂ volume over a specified planning horizon, and then minimizes the total cumulative capture cost, while strictly complying with constraints on the annual hub capacity, the cumulative storage capacity, and the minimum connection duration.

---

## I/O Formats

### Input Formats (Importing Scenarios)
**Note on the `Remaining Life` parameter:** Within the optimization model, a source's remaining lifetime is measured strictly from the **start of the planning horizon** (e.g., from 2025), not from the moment the connection is established. For example, if the planning horizon is 25 years and a source's remaining lifetime is `L = 15`, connecting it in year 5 means it will only be able to operate within the CCS network for $15 - 5 = 10$ years.

- **JSON (`.json`)**: The standard format for storing the full session state. It includes the system parameters and the entire source portfolio with all precalculated limits.
- **Excel (`.xlsx`)**: The primary and most user-friendly format. The file must consist of two sheets:
  - `SystemParameters` (Columns: `Parameter`, `Value`)
  - `Plants` (Columns: `id`, `name`, `co2_flow_mtpy`, `capture_cost_euro_per_t`, `remaining_life_y`)
- **CSV (`.csv`)**: Supported exclusively for importing your source portfolio (equivalent to the `Plants` sheet). This is convenient for bulk uploading of emission sources. System parameters are not overwritten during this process and can be configured separately in the UI.

### Output Formats (Exporting Results)
Regardless of the format, the exported results contain detailed analytics combining overall aggregates, annual hub dynamics, and specific decision explanations for each source (Rule-Based Explainer).
- **JSON (`.json`)**: A complete machine-readable export of all tables and structures packed into a single file.
- **Excel (`.xlsx`)**: An export to a single Excel file containing 5 sheets:
  1. `Summary` — System metrics (total cost, volumes, remaining storage).
  2. `PlantResults` — The selected decision for each source (selection status, cost, start year).
  3. `YearlyResults` — The hub's dynamics over the years (capacity utilization, available space).
  4. `PlantYearContributions` — An activity matrix (showing which source contributes in a specific year).
  5. `DecisionExplanations` — A text-based explanation detailing why a source was assigned a specific feasible start year (or why it was rejected).
- **CSV ZIP Archive (`.zip`)**: A bundled download of raw `.csv` files (one for each table listed above) packed into a single ZIP archive.

---

## Web UI Execution
The project includes a graphical web interface built with Streamlit.
1. Open a terminal in the project folder.
2. Activate your virtual environment: `.\venv\Scripts\activate`
3. Launch the application:
   ```bash
   streamlit run app.py
   ```
4. The tool will open in your browser (usually at `http://localhost:8501`).
5. For a quick start, upload the `example_scenario.xlsx` file or download the blank template ("Download Excel Template") via the sidebar. The calculation is triggered by clicking the primary button in the "Optimization Summary" tab.

---

## CLI Execution
If you wish to run a case study without the graphical interface (headless mode):
```bash
python main.py example_scenario.xlsx
```
*The `.json` and `.xlsx` formats are supported. The script prints the solution process to the console and saves the final result in the current directory as `results.json`.*

---

## Dependencies
The project expects Python 3.9+ and relies on the frameworks listed in the `requirements.txt` file:
- `streamlit` (UI framework)
- `pandas` (Data manipulation and filtering)
- `pulp` (Mathematical core for mixed-integer linear programming (MILP) with the CBC solver)
- `altair` (Interactive charts and statistics)
- `openpyxl` & `xlsxwriter` (Engines for generating and reading Excel files)

To install all dependencies:
```bash
pip install -r requirements.txt
```

---

## Known Limitations (v1.0)
1. **Rule-Based Explainer**: The text explanations (on the *Decision Explanations* tab) are based on rigid heuristics and the metrics of the optimal solution. If a source's start was delayed due to general competition amidst an otherwise unconstrained pipeline, the system classifies it as an "Inferred / Likely tie-breaker", since it does not parse the solver's decision tree directly.
2. **Input Typing**: When uploading Excel or CSV files, the column headers must strictly match the English variable names (`co2_flow_mtpy`, `capture_cost_euro_per_t`, etc.).
3. **Equivalent Optima (Tie-Breaker)**: There is currently no penalty for late starts. If a source needs only 10 years to operate within a 25-year planning horizon (and the hub capacity is unconstrained), the CBC solver will select absolutely **any** mathematically feasible start year. This penalty is intentionally disabled within the mathematical core to preserve the intended objective structure of the model.
