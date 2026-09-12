"""
Diagnostic script: Deep-dive into a specific request calculation.
"""
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion.csv_loader import DataStore
from src.ingestion.image_parser import resolve_blank_amounts
from src.ingestion.message_parser import parse_messages
from src.finance.currency import CurrencyConverter
from src.config import SAMPLE_REQUESTS_CSV

def inspect_req(target_rid):
    store = DataStore()
    store.load_all()

    # Images
    image_amounts = resolve_blank_amounts(store.events, store.images)
    for event_id, amount in image_amounts.items():
        mask = store.events['event_id'] == event_id
        store.events.loc[mask, 'amount'] = amount

    # Messages
    amendments = parse_messages(store.messages, store.events)
    converter = CurrencyConverter(store.exchange_rates)

    sample_df = pd.read_csv(SAMPLE_REQUESTS_CSV)
    req_row = sample_df[sample_df['request_id'] == target_rid].iloc[0]

    uid = str(req_row['user_id']).strip()
    profile = store.profiles[store.profiles['user_id'] == uid].iloc[0]

    print("=" * 60)
    print(f"DIAGNOSTIC FOR {target_rid} (User: {uid})")
    print("=" * 60)
    print("Request details:")
    for col in ['request_date', 'requested_amount', 'desired_completion_date', 'allows_partial_payment', 'request_type']:
        print(f"  {col}: {req_row[col]}")

    print("\nUser Profile:")
    for col in ['home_currency', 'current_available_balance', 'minimum_balance_to_keep',
                'payment_methods_user_will_consider', 'max_installment_months',
                'expense_categories_to_protect', 'expense_categories_user_is_willing_to_reduce',
                'expense_categories_user_is_willing_to_stop']:
        print(f"  {col}: {profile[col]}")

    print("\nExpected ground truth:")
    for col in ['amount_safe_to_pay', 'affordability_status', 'recommended_payment_method',
                'payment_plan', 'earliest_date_for_full_payment', 'spending_changes_needed', 'decision_explanation']:
        print(f"  {col}: {req_row[col]}")

    # Inspect events
    u_events = store.events[store.events['user_id'] == uid]
    print(f"\nUser total events: {len(u_events)}")
    print("Events near request_date:")
    req_date = pd.Timestamp(req_row['request_date'])
    for _, ev in u_events.iterrows():
        s_date = pd.Timestamp(ev['settlement_date'])
        days_diff = (s_date - req_date).days
        if -30 <= days_diff <= 90:
            print(f"  {ev['event_id']} | date={ev['settlement_date']} ({days_diff:+3d}d) | status={ev['status']} | type={ev['event_type']} | dir={ev['direction']} | amt={ev['amount']} {ev['currency']} | desc={ev['description']}")

    # Messages for user
    u_msgs = store.messages[store.messages['user_id'] == uid]
    print(f"\nUser messages ({len(u_msgs)}):")
    for _, m in u_msgs.iterrows():
        print(f"  {m['message_id']} | date={m['message_date']} | sender={m['source_type']} | rel_event={m['related_event_id']} | text={m['message_text']}")

    # Run pipeline on this row
    from src.pipeline import resolve_events, build_forecast, process_request
    from collections import defaultdict

    profiles_by_user = {uid: profile}
    events_by_user = {uid: u_events.to_dict('records')}
    options_by_request = {target_rid: store.payment_options[store.payment_options['request_id'] == target_rid].to_dict('records')}
    msgs_by_user = defaultdict(list)
    for a in amendments:
        if a['user_id'] == uid:
            msgs_by_user[uid].append(a)

    print("\n--- Running pipeline ---")
    result = process_request(req_row, profiles_by_user, events_by_user,
                             options_by_request, msgs_by_user, converter)
    for k, v in result.items():
        print(f"  {k}: {v}")

    # Inspect resolved events and forecast
    balance = float(profile['current_available_balance'])
    min_bal = float(profile['minimum_balance_to_keep'])
    resolved = resolve_events(events_by_user[uid], msgs_by_user[uid], req_date,
                              str(profile['home_currency']), converter, min_bal)
    print("\nResolved recurring debits:", len(resolved['recurring_debits']))
    for d in resolved['recurring_debits']:
        print(f"  Debit: date={d[0].strftime('%Y-%m-%d')} amt={d[1]} cat={d[2]} eid={d[3]}")
    print("Resolved recurring credits:", len(resolved['recurring_credits']))
    for c in resolved['recurring_credits']:
        print(f"  Credit: date={c[0].strftime('%Y-%m-%d')} amt={c[1]} cat={c[2]}")
    print("Resolved scheduled events:", len(resolved['scheduled_events']))
    for s in resolved['scheduled_events']:
        print(f"  Sched: date={s[0].strftime('%Y-%m-%d')} amt={s[1]} dir={s[2]} cat={s[3]}")
    print("Resolved one-time debits:", len(resolved['one_time_debits']))
    for d in resolved['one_time_debits']:
        print(f"  One-time: date={d[0].strftime('%Y-%m-%d')} amt={d[1]} cat={d[2]}")

    traj, min_seen = build_forecast(balance, min_bal, req_date,
                                    resolved['recurring_debits'],
                                    resolved['recurring_credits'],
                                    resolved['one_time_debits'],
                                    resolved['one_time_credits'],
                                    resolved['scheduled_events'])
    print(f"\nBaseline min balance seen: {min_seen} (min_to_keep: {min_bal})")
    # Print days where balance dips lowest
    sorted_traj = sorted(traj, key=lambda x: x[1])
    print("Lowest 5 balance days:")
    for dt, b in sorted_traj[:5]:
        print(f"  {dt.strftime('%Y-%m-%d')}: {b:.2f}")

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'request_01'
    inspect_req(target)
