import sys
import os
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion.csv_loader import DataStore
from src.finance.currency import CurrencyConverter
from src.pipeline import resolve_events, build_forecast

store = DataStore()
store.load_all()
converter = CurrencyConverter(store.exchange_rates)

profile = store.profiles[store.profiles['user_id'] == 'user_04'].iloc[0]
u_events = store.events[store.events['user_id'] == 'user_04'].to_dict('records')
req_date = pd.Timestamp('2024-06-04')
min_bal = float(profile['minimum_balance_to_keep'])
balance = float(profile['current_available_balance'])

resolved = resolve_events(u_events, [], req_date, 'IDR', converter, min_bal)
traj, min_seen = build_forecast(balance, min_bal, req_date,
                                resolved['recurring_debits'],
                                resolved['recurring_credits'],
                                resolved['one_time_debits'],
                                resolved['one_time_credits'],
                                resolved['scheduled_events'])

print(f"Current balance: {balance:,.2f}")
print(f"Min balance to keep: {min_bal:,.2f}")
print("\nDaily trajectory from request_date to 2024-06-20:")
for dt, b in traj[:20]:
    # check what flows occurred on this day
    print(f"  {dt.strftime('%Y-%m-%d')}: balance={b:,.2f}")

print(f"\nDays where balance dips below min_balance ({min_bal:,.2f}):")
for dt, b in traj:
    if b < min_bal + 5000000:
        print(f"  {dt.strftime('%Y-%m-%d')}: {b:,.2f}")

