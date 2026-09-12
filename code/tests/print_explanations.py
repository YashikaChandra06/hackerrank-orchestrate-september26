import pandas as pd
df = pd.read_csv('dataset/sample_requests.csv')
for i, r in df.iterrows():
    print(f"[{r['request_id']}] ({r['affordability_status']}, {r['recommended_payment_method']}):")
    print(f"  {r['decision_explanation']}\n")
