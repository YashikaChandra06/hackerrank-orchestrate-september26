import pandas as pd
df = pd.read_csv('dataset/sample_requests.csv')
for i, r in df.iterrows():
    print(f"{r['request_id']} | user={r['user_id']} | date={r['request_date']} | req_amt={r['requested_amount']} | safe={r['amount_safe_to_pay']} | status={r['affordability_status']} | method={r['recommended_payment_method']} | earliest={r['earliest_date_for_full_payment']} | changes={r['spending_changes_needed']}")
