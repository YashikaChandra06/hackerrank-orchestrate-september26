import sys, os
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.ingestion.csv_loader import DataStore

store = DataStore()
store.load_all()

u21 = store.events[store.events['user_id'] == 'user_21']
prof5 = store.profiles[store.profiles['user_id'] == 'user_05'].iloc[0]
sample = pd.read_csv('dataset/sample_requests.csv')
req5 = sample[sample['request_id'] == 'request_05'].iloc[0]
u5 = store.events[store.events['user_id'] == 'user_05']
m5 = store.messages[store.messages['user_id'] == 'user_05']

print("user_05 Profile:")
for col in ['current_available_balance', 'minimum_balance_to_keep', 'home_currency']:
    print(f"  {col}: {prof5[col]}")

from src.pipeline import resolve_events, simulate_forecast
from src.finance.currency import CurrencyConverter
converter = CurrencyConverter(store.exchange_rates)

u6 = store.events[store.events['user_id'] == 'user_06'].to_dict('records')
p6 = store.profiles[store.profiles['user_id'] == 'user_06'].iloc[0]
req6 = sample[sample['request_id'] == 'request_06'].iloc[0]
req_date = pd.Timestamp(req6['request_date'])
req_amt = float(req6['requested_amount'])
min_bal = float(p6['minimum_balance_to_keep'])
cur_bal = float(p6['current_available_balance'])

resolved6 = resolve_events(u6, [], req_date, 'EUR', converter, min_bal)
traj, min_b = simulate_forecast(cur_bal, req_date, resolved6, extra_payments=[(req_date, req_amt)])
print(f"user_06 baseline with payment: min_b = {min_b} (min_bal: {min_bal})")

# Remove event_476
mod_debits = [d for d in resolved6['projected_debits'] if d['event_id'] != 'event_476']
mod_res = dict(resolved6)
mod_res['projected_debits'] = mod_debits
traj_m, min_m = simulate_forecast(cur_bal, req_date, mod_res, extra_payments=[(req_date, req_amt)])
print(f"user_06 with stop:event_476: min_m = {min_m} (min_bal: {min_bal})")
u6_din = [ev for ev in u6 if ev.get('category') == 'dining']
print("user_06 dining events:")
for ev in u6_din:
    print(f"  {ev['event_id']} | {ev['settlement_date']} | {ev['amount']} | {ev['description']}")


























