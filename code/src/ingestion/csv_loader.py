"""CSV data loader – loads and validates all dataset files once."""
import pandas as pd
from src.config import (
    REQUESTS_CSV, FINANCIAL_PROFILES_CSV, FINANCIAL_EVENTS_CSV,
    EXCHANGE_RATES_CSV, PAYMENT_OPTIONS_CSV, MESSAGES_CSV, IMAGES_CSV,
    SAMPLE_REQUESTS_CSV
)


class DataStore:
    """Singleton-like container for all loaded CSV data."""

    def __init__(self):
        self.requests = None
        self.profiles = None
        self.events = None
        self.exchange_rates = None
        self.payment_options = None
        self.messages = None
        self.images = None
        self.sample_requests = None

    def load_all(self):
        """Load and validate all dataset CSVs."""
        print("[DataStore] Loading datasets...")

        self.requests = pd.read_csv(REQUESTS_CSV)
        self._validate_columns(self.requests, 'requests.csv', [
            'request_id', 'user_id', 'request_date', 'request_type',
            'requested_amount', 'desired_completion_date',
            'allows_partial_payment', 'request_text'
        ])

        self.profiles = pd.read_csv(FINANCIAL_PROFILES_CSV)
        self._validate_columns(self.profiles, 'financial_profiles.csv', [
            'user_id', 'home_currency', 'current_available_balance',
            'minimum_balance_to_keep'
        ])

        self.events = pd.read_csv(FINANCIAL_EVENTS_CSV)
        self._validate_columns(self.events, 'financial_events.csv', [
            'event_id', 'user_id', 'event_type', 'direction', 'amount',
            'currency', 'event_date', 'settlement_date', 'status'
        ])

        self.exchange_rates = pd.read_csv(EXCHANGE_RATES_CSV)
        self.payment_options = pd.read_csv(PAYMENT_OPTIONS_CSV)
        self.messages = pd.read_csv(MESSAGES_CSV)
        self.images = pd.read_csv(IMAGES_CSV)

        try:
            self.sample_requests = pd.read_csv(SAMPLE_REQUESTS_CSV)
        except Exception:
            self.sample_requests = pd.DataFrame()

        # Normalize dates
        for df, cols in [
            (self.requests, ['request_date', 'desired_completion_date']),
            (self.events, ['event_date', 'settlement_date']),
            (self.exchange_rates, ['rate_date']),
            (self.payment_options, ['first_payment_date']),
        ]:
            for col in cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce')

        # Normalize boolean
        if 'allows_partial_payment' in self.requests.columns:
            self.requests['allows_partial_payment'] = (
                self.requests['allows_partial_payment'].astype(str).str.lower().map(
                    {'true': True, 'false': False, '1': True, '0': False, 'yes': True, 'no': False}
                ).fillna(False)
            )

        print(f"  Requests: {len(self.requests)} rows")
        print(f"  Profiles: {len(self.profiles)} rows")
        print(f"  Events: {len(self.events)} rows")
        print(f"  Exchange rates: {len(self.exchange_rates)} rows")
        print(f"  Payment options: {len(self.payment_options)} rows")
        print(f"  Messages: {len(self.messages)} rows")
        print(f"  Images: {len(self.images)} rows")
        return self

    def _validate_columns(self, df, name, required_cols):
        missing = set(required_cols) - set(df.columns)
        if missing:
            raise ValueError(f"{name} missing columns: {missing}")
