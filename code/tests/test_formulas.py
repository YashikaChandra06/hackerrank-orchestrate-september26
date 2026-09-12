import sys, os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.ingestion.csv_loader import DataStore
from src.finance.currency import CurrencyConverter
from tests.test_refined_pipeline import resolve_user_financials, simulate_daily_forecast

store = DataStore()
store.load_all()
converter = CurrencyConverter(store.exchange_rates)
sample = pd.read_csv('dataset/sample_requests.csv')

print("Testing protected-expenses formula on all 25 samples:")
print(f"{'rid':10s} | {'EXP':12s} | {'FORMULA_1':12s} | {'FORMULA_2':12s} | {'DIFF_1':10s}")
print("-" * 65)

for _, r in sample.iterrows():
    rid = r['request_id']
    uid = r['user_id']
    req_date = pd.Timestamp(r['request_date'])
    req_amt = float(r['requested_amount'])
    exp_safe = float(r['amount_safe_to_pay'])

    prof = store.profiles[store.profiles['user_id'] == uid].iloc[0]
    cur_bal = float(prof['current_available_balance'])
    min_bal = float(prof['minimum_balance_to_keep'])
    protect_cats = set(str(prof.get('expense_categories_to_protect', '')).split('|'))

    u_events = store.events[store.events['user_id'] == uid].to_dict('records')
    resolved = resolve_user_financials(u_events, [], req_date, str(prof['home_currency']), converter, min_bal)

    # Formula 1: all projected debits
    traj_all, min_all = simulate_daily_forecast(cur_bal, req_date, resolved)
    safe_all = max(0.0, min(req_amt, min(b - min_bal for dt, b in traj_all)))

    # Formula 2: only protected debits (and pending/scheduled)
    resolved_prot = dict(resolved)
    resolved_prot['projected_debits'] = [d for d in resolved['projected_debits'] if d['category'] in protect_cats]
    traj_prot, min_prot = simulate_daily_forecast(cur_bal, req_date, resolved_prot)
    safe_prot = max(0.0, min(req_amt, min(b - min_bal for dt, b in traj_prot)))

    print(f"{rid:10s} | {exp_safe:12.2f} | {safe_all:12.2f} | {safe_prot:12.2f} | {safe_all - exp_safe:10.2f}")
