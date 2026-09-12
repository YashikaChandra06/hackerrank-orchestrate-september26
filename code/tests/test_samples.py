"""
Validation script: Evaluate pipeline against sample_requests.csv ground truth.
"""
import sys
import os
import pandas as pd
import numpy as np
from collections import defaultdict

# Add code directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion.csv_loader import DataStore
from src.ingestion.image_parser import resolve_blank_amounts
from src.ingestion.message_parser import parse_messages
from src.finance.currency import CurrencyConverter
from src.config import SAMPLE_REQUESTS_CSV
from src.pipeline import process_request, make_fallback_result


def evaluate_samples():
    print("=" * 70)
    print("Evaluating Pipeline against sample_requests.csv Ground Truth")
    print("=" * 70)

    store = DataStore()
    store.load_all()

    # Resolve blank amounts from images
    image_amounts = resolve_blank_amounts(store.events, store.images)
    for event_id, amount in image_amounts.items():
        mask = store.events['event_id'] == event_id
        store.events.loc[mask, 'amount'] = amount

    # Parse messages
    amendments = parse_messages(store.messages, store.events)

    # Converter
    converter = CurrencyConverter(store.exchange_rates)

    # Build indices
    profiles_by_user = {}
    for _, row in store.profiles.iterrows():
        uid = str(row['user_id']).strip()
        profiles_by_user[uid] = row

    events_by_user = defaultdict(list)
    for _, row in store.events.iterrows():
        uid = str(row['user_id']).strip()
        events_by_user[uid].append(row)

    options_by_request = defaultdict(list)
    for _, row in store.payment_options.iterrows():
        rid = str(row['request_id']).strip()
        options_by_request[rid].append(row)

    msgs_by_user = defaultdict(list)
    for a in amendments:
        uid = a['user_id']
        msgs_by_user[uid].append(a)

    sample_df = pd.read_csv(SAMPLE_REQUESTS_CSV)

    fields_to_compare = [
        'amount_safe_to_pay',
        'affordability_status',
        'recommended_payment_method',
        'payment_plan',
        'earliest_date_for_full_payment',
        'spending_changes_needed'
    ]

    matches = {f: 0 for f in fields_to_compare}
    total = len(sample_df)

    print(f"\nEvaluating {total} sample requests...\n")

    for idx, row in sample_df.iterrows():
        rid = row['request_id']
        pred = process_request(
            row, profiles_by_user, events_by_user,
            options_by_request, msgs_by_user, converter
        )

        row_diffs = []
        for f in fields_to_compare:
            actual = str(row.get(f, '')).strip()
            if actual == 'nan':
                actual = ''
            predicted = str(pred.get(f, '')).strip()
            if predicted == 'nan':
                predicted = ''

            # Float comparison for amount_safe_to_pay
            if f == 'amount_safe_to_pay':
                try:
                    act_f = float(actual)
                    pred_f = float(predicted)
                    is_match = abs(act_f - pred_f) < 0.1 or (act_f > 0 and abs(act_f - pred_f) / act_f < 0.05)
                except:
                    is_match = (actual == predicted)
            else:
                is_match = (actual == predicted)

            if is_match:
                matches[f] += 1
            else:
                row_diffs.append((f, actual, predicted))

        if row_diffs:
            print(f"[{rid}] MISMATCHES ({len(row_diffs)}):")
            for f, act, prd in row_diffs:
                print(f"    {f:30s} | EXPECTED: {act:25s} | GOT: {prd:25s}")
        else:
            print(f"[{rid}] ALL MATCH! (status={pred['affordability_status']}, method={pred['recommended_payment_method']})")


    print("\n" + "=" * 70)
    print("ACCURACY SUMMARY")
    print("=" * 70)
    for f in fields_to_compare:
        acc = matches[f] / total * 100
        print(f"  {f:32s}: {matches[f]:2d}/{total:2d} ({acc:5.1f}%)")


if __name__ == '__main__':
    evaluate_samples()
