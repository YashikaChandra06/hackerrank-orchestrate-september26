# Buy or Wait? — AI Financial Affordability Agent

[![HackerRank Orchestrate](https://img.shields.io/badge/HackerRank-Orchestrate%202026-brightgreen.svg)](https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Verified%20%26%20Packaged-success.svg)](#)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

A fully deterministic, production-grade financial affordability engine built for the **HackerRank Orchestrate: Buy or Wait?** challenge. The system evaluates purchase and payment requests across 250 users by reconstructing each user's financial position, simulating daily 90-day cash-flow trajectories, resolving multi-modal financial evidence (invoices, salary slips, messages), and recommending optimal, mathematically sound payment strategies.

---

## 📑 Table of Contents

- [🛠 Setup Instructions](#-setup-instructions)
  - [Prerequisites](#prerequisites)
  - [Installation & Environment Setup](#installation--environment-setup)
  - [Running the Full Pipeline](#running-the-full-pipeline)
  - [Running Validation & Benchmark Tests](#running-validation--benchmark-tests)
  - [Packaging the Final Submission](#packaging-the-final-submission)
  - [Inspecting Individual Requests](#inspecting-individual-requests)
- [🧠 Approach Overview](#-approach-overview)
  - [1. Problem Formulation & Financial Solvency Model](#1-problem-formulation--financial-solvency-model)
  - [2. Closed-Form Mathematical Safety Limit](#2-closed-form-mathematical-safety-limit)
  - [3. Inflow Scheduling & Recurrence Detection](#3-inflow-scheduling--recurrence-detection)
  - [4. Multi-Modal Evidence Reconciliation](#4-multi-modal-evidence-reconciliation)
  - [5. Six-Tier Plan Ranking Hierarchy](#5-six-tier-plan-ranking-hierarchy)
  - [6. Permitted Spending Changes](#6-permitted-spending-changes)
- [🏛 Architecture & Directory Structure](#-architecture--directory-structure)
- [📊 Token Usage & Cost Report](#-token-usage--cost-report)
- [📦 Submission Package & Verification](#-submission-package--verification)

---

## 🛠 Setup Instructions

### Prerequisites
- **Python Version:** Python 3.10 or higher
- **Package Manager:** `pip`
- **Supported Operating Systems:** Windows, macOS, Linux (cross-platform compatible)

### Installation & Environment Setup

1. **Clone or navigate to the repository:**
   ```bash
   cd hackerrank-orchestrate-september26
   ```

2. **(Optional) Create and activate a virtual environment:**
   ```bash
   # On macOS/Linux:
   python3 -m venv venv
   source venv/bin/activate

   # On Windows (PowerShell):
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   *Core dependencies:* `pandas>=2.0.0`, `numpy>=1.24.0`.

4. **Configure Environment Variables (Optional):**
   Copy the `.env.example` template:
   ```bash
   # On Linux/macOS:
   cp .env.example .env

   # On Windows:
   copy .env.example .env
   ```
   *(All inference is completely local and deterministic; no third-party API keys are required).*

---

### Running the Full Pipeline

Execute the entire end-to-end evaluation pipeline with a single command from the project root:

```bash
python run.py
```

- **Execution Time:** ~3.9 seconds for all 250 evaluation requests (~0.016s per request).
- **Generated Outputs:**
  - `output.csv` (in repository root) — Primary submission file containing 250 predicted rows.
  - `dataset/output.csv` (inside dataset folder) — Synchronized output copy.
  - `code/evaluation/usage_report.md` — Auto-generated token usage and cost summary.

---

### Running Validation & Benchmark Tests

To verify accuracy and consistency against the 25 public solved examples in `dataset/sample_requests.csv`:

```bash
python code/tests/test_samples.py
```

This benchmark verifies:
- `amount_safe_to_pay` numerical precision
- `affordability_status` classification alignment
- `recommended_payment_method` policy compliance
- `payment_plan` syntax and date-amount accuracy
- `earliest_date_for_full_payment` feasibility
- `spending_changes_needed` syntax and constraint adherence

---

### Packaging the Final Submission

Run the packaging script to generate a verified, ready-to-upload `code.zip`:

```bash
python package_submission.py
```

This script verifies:
- Exactly 250 rows in `output.csv` with the required 8-column header.
- Zero empty `request_id`, `amount_safe_to_pay`, `affordability_status`, or `recommended_payment_method` fields.
- `0 <= amount_safe_to_pay <= requested_amount` across all rows.
- Inclusion of `evaluation/usage_report.md` in the root of the zip archive.

---

### Inspecting Individual Requests

To run diagnostic analysis and view day-by-day cash flows for any single request:

```bash
python code/tests/inspect_request.py request_01
```

---

## 🧠 Approach Overview

The solution models financial affordability not as a generic LLM prompt, but as a **rigorous, deterministic cash-flow solvency system** grounded in conservative financial planning principles.

```text
┌─────────────────────────┐     ┌────────────────────────┐     ┌────────────────────────┐
│ Structured Data (CSVs)  │     │ Images (16 Documents)  │     │ Messages (215 Updates) │
│ - Financial Profiles    │     │ - Invoices & Bills     │     │ - Salary Adjustments   │
│ - Financial Events      │     │ - Salary Slips         │     │ - Contract End Notices │
│ - Payment Options       │     │ - Triangulated FX      │     │ - Cancellations        │
└────────────┬────────────┘     └───────────┬────────────┘     └───────────┬────────────┘
             │                              │                              │
             └──────────────────────┬───────┴──────────────────────────────┘
                                    ▼
                     ┌─────────────────────────────┐
                     │ Cash-Flow Solvency Engine   │
                     │ - 90-Day Daily Simulation   │
                     │ - Closed-Form Safe Payment  │
                     │ - Recurring Spending Model  │
                     │ - Six-Tier Plan Ranking     │
                     └──────────────┬──────────────┘
                                    ▼
                     ┌─────────────────────────────┐
                     │        output.csv           │
                     │ 250 Validated Predictions   │
                     └─────────────────────────────┘
```

### 1. Problem Formulation & Financial Solvency Model
For every evaluation request on `request_date`, the system reconstructs the user's daily cash balance trajectory over $t \in [0, 90]$ days:

$$\text{balance}(t) = \text{current\_available\_balance} + \sum_{\tau \le t} \text{net\_cash\_flow}(\tau)$$

A financial action or payment plan is defined as **mathematically safe** if and only if:

$$\min_{t \in [0, 90]} \text{balance}(t) \ge \text{minimum\_balance\_to\_keep}$$

Key financial accounting rules enforced:
- **Pending Debits:** Held in reserve immediately upon request date.
- **Pending Credits:** Excluded from cash until settlement date (no speculative windfalls).
- **Confirmed Salary:** Counted on verified settlement dates and projected monthly according to confirmed employment status.
- **Unrealized Assets:** Excluded from liquid cash.

---

### 2. Closed-Form Mathematical Safety Limit
Rather than relying on iterative heuristic guesswork or binary search, `amount_safe_to_pay` is computed in exact closed form:

1. Let $B_{\min} = \min_{t \in [0, 90]} \text{balance}(t)$ be the minimum projected balance without the purchase.
2. The maximum cash that can be withdrawn on `request_date` without violating `minimum_balance_to_keep` at any point during the forecast horizon is:
   $$X_{\text{safe}} = \max\left(0.0, \; B_{\min} - \text{minimum\_balance\_to\_keep}\right)$$
3. The safe amount is bounded by the purchase price:
   $$\text{amount\_safe\_to\_pay} = \min\left(\text{requested\_amount}, \; X_{\text{safe}}\right)$$

---

### 3. Inflow Scheduling & Recurrence Detection
- **Salary Projection:** Historical settled salaries and scheduled future salaries are detected per user. The engine projects recurring salary dates at calendar-month intervals.
- **Contract Termination Handling:** If messages or transaction descriptions contain `"contract_ended"` or `"Final employer payroll"` (e.g., user_05), future recurring salaries are immediately halted.
- **Variable Essential Spending:** Variable non-discretionary expenses (`dining`, `groceries`, `transport`) often vary in description ("Bakery", "Supermarket") but exhibit regular cadence (e.g., 21-day cycles). The engine groups expenses by category to accurately forecast future non-negotiable living costs.

---

### 4. Multi-Modal Evidence Reconciliation
Messages and images represent untrusted evidence that must be validated against structured financial reality:
- **Document Images (`code/src/ingestion/image_parser.py`):** 16 events in `financial_events.csv` have missing transaction amounts linked to images in `dataset/media/images/`. All 16 documents (salary slips, utility receipts, medical bills, tuition invoices) were mapped and validated deterministically.
- **Natural Language Communications (`code/src/ingestion/message_parser.py`):** 215 messages are parsed to detect salary increases/decreases, rescheduled pay dates, canceled transactions, and merchant payment modifications.

---

### 5. Six-Tier Plan Ranking Hierarchy
When multiple candidate payment options (full payment, installments, partial payment, wait) maintain safety, the engine selects the optimal plan by strictly evaluating the challenge's 6-tier preference rules:
1. **Completion Deadline:** Must finish on or before `desired_completion_date`.
2. **Spending Changes:** Plans requiring no spending changes are strictly preferred.
3. **Total Cost:** Lowest total cash outlay (including interest, setup fees, and financing charges).
4. **Earlier Start:** Earliest first payment date.
5. **Fewer Payments:** Lower payment frequency / fewer installments.
6. **Tie-Breaker:** Lexicographically lowest `payment_option_id`.

---

### 6. Permitted Spending Changes
If a request is not immediately affordable:
- The engine explores spending changes up to 3 non-protected, flexible transactions in categories the user permits (`financial_profiles.csv`).
- Generates compliant actions: `stop:<event_id>` or `reduce_to:<event_id>:<new_amount>`.
- If safe with these modifications, the status becomes `affordable_with_plan`.

---

## 🏛 Architecture & Directory Structure

```text
hackerrank-orchestrate-september26/
├── run.py                           # Root entry point: runs pipeline and outputs results
├── package_submission.py            # Automated packaging script for code.zip
├── requirements.txt                 # Runtime dependencies (pandas, numpy)
├── .env.example                     # Environment configuration template
├── README.md                        # Documentation: setup instructions & approach
├── log.txt                          # AGENTS.md compliant conversation log
├── output.csv                       # Final generated predictions (repo root)
├── dataset/
│   ├── requests.csv                 # 250 evaluation requests
│   ├── output.csv                   # Validated output copy in dataset/
│   ├── sample_requests.csv          # 25 ground-truth benchmark examples
│   ├── financial_profiles.csv       # User balances, priorities, preferences
│   ├── financial_events.csv         # Historical, pending, scheduled events
│   ├── request_payment_options.csv  # Merchant financing offers
│   ├── exchange_rates.csv           # Fixed historical conversion rates
│   ├── messages.csv                 # Natural language communications
│   ├── images.csv                   # Document image metadata
│   └── media/images/                # 16 PNG statements/receipts
└── code/
    ├── main.py                      # Core engine entry point & report generator
    ├── evaluation/
    │   └── usage_report.md          # Token usage and cost analysis ($0.00)
    ├── src/
    │   ├── config.py                # System paths, constants, and column schemas
    │   ├── pipeline.py              # Main decision engine & 90-day simulator
    │   ├── ingestion/
    │   │   ├── csv_loader.py        # Robust multi-table data ingestion
    │   │   ├── image_parser.py      # Deterministic document amount extraction
    │   │   └── message_parser.py    # NLP/regex message amendment parser
    │   └── finance/
    │       └── currency.py          # Multi-currency FX conversion & triangulation
    └── tests/
        ├── test_samples.py          # Benchmark test against sample ground truth
        └── inspect_request.py       # Single-request diagnostic inspection tool
```

---

## 📊 Token Usage & Cost Report

Because the decision engine operates deterministically with zero remote API dependencies, inference is completely free and reproducible:

| Metric | Value |
|---|---|
| **Model Provider** | Fully Deterministic Native Pipeline |
| **Model Calls** | 0 |
| **Input Tokens** | 0 |
| **Output Tokens** | 0 |
| **Total Cost** | **$0.00** |
| **Requests Processed** | 250 |
| **Total Pipeline Runtime** | ~3.9 seconds |
| **Average Latency / Request** | 0.016 seconds |

Full details are documented in [`code/evaluation/usage_report.md`](./code/evaluation/usage_report.md).

---

## 📦 Submission Package & Verification

The final submission package conforms strictly to the HackerRank Orchestrate contract:

1. **`output.csv`**: Contains exactly 250 rows matching the 8 required columns in order:
   ```text
   request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
   ```
2. **`code.zip`**: Complete source code package including `run.py`, `requirements.txt`, `README.md`, all source modules, tests, and `evaluation/usage_report.md`.
3. **`chat_transcript` (`log.txt`)**: Verbatim, timestamped session record following the `AGENTS.md` protocol.

**Official Submission Portal:**
[HackerRank Buy or Wait Challenge Submission](https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission)
