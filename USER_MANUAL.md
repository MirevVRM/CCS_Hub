# User Manual: CCS Hub Optimization Tool

Welcome to the user manual for the CCS Hub optimization tool!

This tool is designed to help engineers, analysts, and technical leads determine the optimal schedule for connecting industrial plants to a shared CO₂ transport pipeline. Using this application, you can maximize captured CO₂ volumes and minimize total system cost while complying with strict physical and temporal system constraints.

---

## 🚀 Quick Start

If you already have Python 3.9+ installed, complete just three steps to get started:

**1. Open a terminal in your project folder (`case_one`).**

**2. Set up the environment and install dependencies:**
```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

**3. Launch the visual interface:**
```bash
streamlit run app.py
```

After this, the application window will open in your browser (default is `http://localhost:8501`). You can click `"Download Excel Template"` in the left panel, fill out the template with your source portfolio data, and immediately upload it back for the calculation. You're set!

---

## 🛠️ System Requirements and Installation

If you need a detailed installation guide:

### 1. System Requirements
- Operating System: Windows, macOS, or Linux.
- Installed **Python version 3.9** (or newer). If Python is not installed, download it from the [official website](https://www.python.org/downloads/). *Make sure to check the "Add Python to PATH" box during installation.*

### 2. Step-by-Step Installation
Open a built-in terminal (e.g., in VS Code, PyCharm, or a standard Windows PowerShell console), navigate to the `case_one` project folder, and run the following commands one by one:

1. **Create a virtual environment** (this is an isolated environment for the program to prevent conflicts with your operating system):
   ```bash
   python -m venv venv
   ```
2. **Activate the virtual environment:** 
   ```bash
   .\venv\Scripts\activate
   ```
   *(You should see the `(venv)` prefix in your command prompt before entering further commands).*
3. **Install all required libraries:**
   ```bash
   pip install -r requirements.txt
   ```

The application is now completely ready for use.

---

## 🏁 First Launch

After successful installation, launch the application's web interface. First, ensure your virtual environment is activated (the `(venv)` prefix is present):

```bash
streamlit run app.py
```

The command will start a local web server and automatically open the page `http://localhost:8501` in your default browser.

> **💡 How to stop the program:**
> When you are finished working with the interface, return to the terminal where you entered the command and press `Ctrl + C`. The server will shut down.
> If you are using PowerShell and the process does not close, run:
> ```powershell
> Stop-Process -Id (Get-NetTCPConnection -LocalPort 8501).OwningProcess -Force
> ```

---

## 📁 Data Preparation

Although you can enter plant information manually directly in the interface, for practical scenarios it is much more convenient to upload prepared files via the left sidebar (**Scenario Management**).

There are three upload formats available, each with its own specific purpose:

### 1. Working with Excel (`.xlsx`) — Primary Format
> The most recommended starting option. You can download a blank template by clicking the `"Download Excel Template"` button in the left panel of the window.

The template consists of two sheets:
- **`SystemParameters`**: Your basic constraints. Start year (e.g., 2025), annual hub capacity (Mt/y), cumulative storage capacity (Mt), etc.
- **`Plants`**: Your source portfolio. Here you specify their identifiers, names, annual CO₂ emissions, the cost of capturing a ton of CO₂, and their remaining lifetime. This information will be loaded into the system and replace the current data.

### 2. Working with CSV (`.csv`) — Portfolio Input Format
- **Purpose:** Use this if you want to upload only your **source portfolio** from an external corporate database (only the data that belongs on the `Plants` sheet).
- **Behavior:** Uploading a CSV file **does not reset** the system parameters. The properties for the pipeline and storage will remain exactly as you configured them previously in the interface.

### 3. Working with JSON (`.json`) — Session Save
- **Purpose:** A format for fully saving the state of your working session. It includes absolutely everything: both system parameters and the source portfolio.
- Use the `"Download JSON Scenario"` button in the left panel to export your work, and then restore it at any time by uploading it again.

### ⏳ How to interpret "Remaining Lifetime" (`Remaining Life`)?
An important detail when populating the `Remaining Life` parameter for a plant is how it is measured.

> **Example:** 
> Your total planning horizon is 25 years (from 2025 to 2050). 
> Suppose the physical remaining lifetime of the "Cement #1" plant is **15 years** — the counting of this period always starts strictly from the *start of the planning horizon* (from 2025). 
> 
> If the optimization model decides to apply a CO₂ capture retrofit to the plant and connect it to the pipeline immediately in 2025, it will remain active in the CCS network for the full 15 years.
> However, if the system decides to delay connecting this plant by 5 years (until 2030), it will only be able to remain active in the CCS network for **$15 - 5 = 10$ years**, since its physical operational life will expire at the exact same time (by 2040).

---

## 🗺️ Working in the Interface: Tab Guide

The central part of the application is divided into five main tabs.

### Tab 1: ⚙️ System Parameters
**What you do here:** Set the main system constraints for your infrastructure. Configure the overall planning horizon in years, the start year, the annual hub capacity, and the cumulative storage capacity.
*A special parameter here is "Minimum Connection Time" (minimum connection duration) — this is a strict minimum operational requirement. A plant will not undergo a CO₂ capture retrofit and be connected at all if the system is unable to keep it in the pipeline for at least the specified number of years.*

### Tab 2: 🏭 Plants Configuration
**What you do here:** Manage your source portfolio directly in the browser. You can add new rows, edit names, emission volumes, and costs. The table will automatically calculate the absolute maximum emissions of a plant over its entire remaining lifetime.

### Tab 3: 🚀 Optimization Summary
**What you do here:** Launch the calculation process!
1. Click the large **Run Two-Stage Optimization** button.
2. The optimization model (using mixed-integer linear programming (MILP)) will evaluate feasible retrofit schedules and provide the optimal connection schedule.
3. **How to interpret the results:** Here you will see the main business metrics: total captured CO₂ volume and the total system cost in €. If `Total Captured CO₂` is less than the sum generated by the entire source portfolio, it means some sources did not fit within the constraints of the annual hub capacity or cumulative storage capacity. Below, you will see two charts showing the share of each plant in the total volume and total costs.

### Tab 4: 📊 Detailed Analytics
**What you do here:** Graphically analyze the system's dynamics over the years:
- Left (Hub Load Contributions): A stacked bar chart showing which plants were filling the pipeline in each specific year, and whether you hit the annual limit (the red dashed line representing annual hub capacity).
- Right (Cumulative Storage): A line chart showing the rate at which the cumulative storage capacity is being used. You will clearly see the year when the cumulative storage capacity is definitively exhausted.

### Tab 5: 💡 Decision Explanations
**What you do here:** Read detailed explanations of why the optimization model made a specific decision for each individual plant.
- 🟢 **Selected**: The plant is selected for a CO₂ capture retrofit. Its start year is indicated, along with an analysis of whether it could have started earlier.
- 🔴 **Not Selected**: The plant was discarded. Typically, this means that more optimal competitors (e.g., with lower capture costs) have taken up the available capacity.
- ⚪ **Filtered Out Early**: The plant did not even reach the mathematical calculation stage, as its characteristics (e.g., a remaining lifetime that is too short to meet the minimum connection duration) violate the strict system constraints from Tab 1.

---

## 💾 Exporting Results

After completing your case study on **Tab 3** (Optimization Summary), you can save the finished project to your computer. Scroll down Tab 3 to the "Export Solution" section.

The following download formats are available:
1. **Excel (.xlsx)**: The most reader-friendly report format. A single file contains 5 different sheets with figures covering your entire operational scheme, costs, and an explanation of the plants' behavior.
2. **JSON**: An infrastructure format. The complete solution is stored in this format (convenient for developers).
3. **CSV Archive (.zip)**: 5 separate `.csv` tables packed into a zip archive (excellent for loading into analytics systems like Power BI or Tableau).

---

## ❓ Troubleshooting

### 1. "Error loading file..." when uploading Excel or CSV
**Cause:** The program cannot recognize the columns. The column names (Headers) in your file must strictly match the English names expected by the system (e.g., `co2_flow_mtpy`).
👉 **Fix:** Use the `"Download Excel Template"` button in the left panel of the interface, and copy your data into the downloaded template, keeping the original English headers.

### 2. The calculation button throws a red error: "No valid connection options found"
**Cause:** This is a logical (not programmatic) situation. It means your system constraints (annual hub capacity, cumulative storage capacity, or minimum connection duration) are too strict. Not a single plant from your source portfolio can physically be connected while satisfying all your constraints simultaneously.
👉 **Fix:** Go to Tab 1. Try increasing the pipeline/storage capacity or lowering the "Minimum Connection Time (years)" requirement — then run the calculation again.

### 3. Terminal error "streamlit is not recognized..."
**Cause:** The Windows system does not recognize the Streamlit command because you have not activated the virtual environment.
👉 **Fix:** Before calling Streamlit, type `.\venv\Scripts\activate` into the terminal. Ensure the `(venv)` marker appears on the left in the command prompt.

### 4. Why is plant B selected instead of plant A, even though plant A is cheaper per ton?
**Cause:** The logic of the optimization model (MILP) is designed as follows: first, it **maximizes the volume** (CO₂), and only then does it minimize the costs (Cost). If plant B emits a massive volume of CO₂ (better utilizing the pipeline's annual hub capacity), the program will prefer it over plant A—even if it is slightly more expensive per ton—to ensure the total captured CO₂ volume is as high as possible.
