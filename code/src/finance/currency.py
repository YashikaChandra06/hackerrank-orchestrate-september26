"""Currency conversion using fixed exchange rates from exchange_rates.csv."""
import pandas as pd
from datetime import datetime, timedelta


class CurrencyConverter:
    """Convert amounts between currencies using dated exchange rates."""

    def __init__(self, exchange_rates_df):
        self.rates = {}
        for _, row in exchange_rates_df.iterrows():
            date = row['rate_date']
            if isinstance(date, str):
                date = pd.Timestamp(date)
            from_c = str(row['from_currency']).strip()
            to_c = str(row['to_currency']).strip()
            rate = float(row['rate'])
            key = (from_c, to_c)
            if key not in self.rates:
                self.rates[key] = []
            self.rates[key].append((date, rate))

        # Sort by date for each pair
        for key in self.rates:
            self.rates[key].sort(key=lambda x: x[0])

    def get_rate(self, from_currency, to_currency, rate_date):
        """Get exchange rate for a currency pair on a specific date.

        Uses exact date match first, then closest available date.
        Supports direct and inverse lookups.
        """
        if from_currency == to_currency:
            return 1.0

        if isinstance(rate_date, str):
            rate_date = pd.Timestamp(rate_date)

        # Direct lookup
        direct = self._find_rate(from_currency, to_currency, rate_date)
        if direct is not None:
            return direct

        # Inverse lookup
        inverse = self._find_rate(to_currency, from_currency, rate_date)
        if inverse is not None and inverse != 0:
            return 1.0 / inverse

        # Try cross-rate via USD
        for mid_currency in ['USD', 'EUR']:
            if mid_currency in (from_currency, to_currency):
                continue
            r1 = self.get_rate(from_currency, mid_currency, rate_date)
            r2 = self.get_rate(mid_currency, to_currency, rate_date)
            if r1 is not None and r2 is not None:
                return r1 * r2

        return None

    def _find_rate(self, from_c, to_c, target_date):
        """Find rate for exact pair, using closest date if exact match unavailable."""
        key = (from_c, to_c)
        entries = self.rates.get(key, [])
        if not entries:
            return None

        # Try exact date match first
        for date, rate in entries:
            if date == target_date:
                return rate

        # Use closest date
        best = None
        best_diff = None
        for date, rate in entries:
            diff = abs((date - target_date).days)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = rate
        return best

    def convert(self, amount, from_currency, to_currency, rate_date):
        """Convert an amount from one currency to another."""
        if from_currency == to_currency:
            return amount
        rate = self.get_rate(from_currency, to_currency, rate_date)
        if rate is None:
            print(f"  [Currency] WARNING: No rate for {from_currency}->{to_currency} on {rate_date}")
            return amount  # fallback: return as-is
        return round(amount * rate, 2)
