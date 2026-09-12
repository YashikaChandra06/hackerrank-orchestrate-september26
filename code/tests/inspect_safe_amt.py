import sys, os
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.ingestion.csv_loader import DataStore

store = DataStore()
store.load_all()

sample = pd.read_csv('dataset/sample_requests.csv')

print(f"{'rid':10s} | {'user':7s} | {'cur_bal':12s} | {'min_bal':10s} | {'diff':12s} | {'req_amt':12s} | {'safe_amt':12s} | {'status':20s}")
print("-" * 105)

for _, r in sample.iterrows():
    uid = r['user_id']
    prof = store.profiles[store.profiles['user_id'] == uid].iloc[0]
    cur_bal = float(prof['current_available_balance'])
    min_bal = float(prof['minimum_balance_to_keep'])
    diff = cur_bal - min_bal
    req_amt = float(r['requested_amount'])
    safe_amt = float(r['amount_safe_to_pay'])
    status = r['affordability_status']
    print(f"{r['request_id']:10s} | {uid:7s} | {cur_bal:12.2f} | {min_bal:10.2f} | {diff:12.2f} | {req_amt:12.2f} | {safe_amt:12.2f} | {status:20s}")
