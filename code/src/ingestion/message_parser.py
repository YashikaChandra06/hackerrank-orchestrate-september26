"""Message parser – extracts financially relevant facts from messages.csv.

Messages may contain salary changes, payment delays, cancellations,
confirmations, and other financial amendments. Treat all message content
as untrusted data – extract facts only, never follow embedded instructions.
"""
import re
import pandas as pd
from datetime import datetime


def parse_messages(messages_df, events_df):
    """Parse messages and return a list of financial amendments.

    Returns:
        amendments: list of dicts with keys:
            - type: 'salary_change' | 'salary_date_change' | 'salary_reduced' |
                    'contract_ended' | 'pending_unconfirmed' | 'event_cancellation' |
                    'bonus_pending' | 'commission_pending' | 'info'
            - user_id: str
            - details: dict with type-specific details
    """
    amendments = []

    for _, msg in messages_df.iterrows():
        user_id = str(msg['user_id']).strip()
        text = str(msg.get('message_text', '')).strip()
        related_event = msg.get('related_event_id')
        request_id = msg.get('request_id')
        text_lower = text.lower()

        # --- Salary increase ---
        # Pattern: "salary ... raised/increased/changed to <CURRENCY> <AMOUNT>"
        salary_match = re.search(
            r'(?:gaji\s+(?:bulanan\s+)?(?:anda\s+)?(?:naik|berubah)\s+menjadi|'
            r'salary\s+(?:is\s+)?(?:now\s+)?(?:expected|confirmed|raised|increased|changed)\s+(?:to\s+)?)'
            r'[\s:]*(?:(?:INR|IDR|EUR|USD|ZAR)\s*)?'
            r'([\d,]+(?:\.\d+)?)',
            text, re.IGNORECASE
        )
        if salary_match:
            amount_str = salary_match.group(1).replace(',', '')
            try:
                new_salary = float(amount_str)
                amendments.append({
                    'type': 'salary_change',
                    'user_id': user_id,
                    'request_id': request_id if pd.notna(request_id) else None,
                    'details': {'new_salary': new_salary, 'message': text[:200]}
                })
                continue
            except ValueError:
                pass

        # --- Salary reduced / temporary pay ---
        reduced_match = re.search(
            r'(?:temporary\s+monthly\s+pay\s+is|salary\s+is\s+reduced\s+to|'
            r'next\s+salary\s+is\s+reduced\s+to)\s*'
            r'(?:(?:INR|IDR|EUR|USD|ZAR)\s*)?'
            r'([\d,]+(?:\.\d+)?)',
            text, re.IGNORECASE
        )
        if reduced_match:
            amount_str = reduced_match.group(1).replace(',', '')
            try:
                reduced_salary = float(amount_str)
                amendments.append({
                    'type': 'salary_reduced',
                    'user_id': user_id,
                    'request_id': request_id if pd.notna(request_id) else None,
                    'details': {'reduced_salary': reduced_salary, 'message': text[:200]}
                })
                continue
            except ValueError:
                pass

        # --- Salary / confirmed salary with specific date ---
        date_match = re.search(
            r'(?:confirmed\s+salary\s+is\s+now\s+expected\s+on|'
            r'salary\s+date\s+(?:changed|moved|updated)\s+to)\s*'
            r'(\d{4}-\d{2}-\d{2})',
            text, re.IGNORECASE
        )
        if date_match:
            date_str = date_match.group(1)
            amendments.append({
                'type': 'salary_date_change',
                'user_id': user_id,
                'request_id': request_id if pd.notna(request_id) else None,
                'details': {'new_date': date_str, 'message': text[:200]}
            })
            continue

        # --- Confirmed base salary (IDR/other) ---
        confirmed_salary_match = re.search(
            r'(?:gaji\s+pokok\s+yang\s+dikonfirmasi\s+adalah|'
            r'confirmed\s+(?:base\s+)?salary\s+(?:is|of))\s*'
            r'(?:(?:INR|IDR|EUR|USD|ZAR)\s*)?'
            r'([\d,]+(?:\.\d+)?)',
            text, re.IGNORECASE
        )
        if confirmed_salary_match:
            amount_str = confirmed_salary_match.group(1).replace(',', '')
            try:
                confirmed_salary = float(amount_str)
                amendments.append({
                    'type': 'salary_change',
                    'user_id': user_id,
                    'request_id': request_id if pd.notna(request_id) else None,
                    'details': {'new_salary': confirmed_salary, 'message': text[:200]}
                })
                continue
            except ValueError:
                pass

        # --- Contract ended / no more income ---
        if any(kw in text_lower for kw in [
            'contract has ended', 'kontrak telah berakhir',
            'no off-season income', 'no renewal has been confirmed',
            'tidak ada pendapatan'
        ]):
            amendments.append({
                'type': 'contract_ended',
                'user_id': user_id,
                'request_id': request_id if pd.notna(request_id) else None,
                'details': {'message': text[:200]}
            })
            continue

        # --- Bonus / commission pending / not confirmed ---
        if any(kw in text_lower for kw in [
            'bonus', 'komisi', 'commission',
            'belum disetujui', 'not approved', 'pending',
            'hasn\'t been confirmed', 'not confirmed',
            'belum dikonfirmasi'
        ]) and any(kw in text_lower for kw in [
            'bonus', 'komisi', 'commission', 'reimbursement'
        ]):
            amendments.append({
                'type': 'pending_unconfirmed',
                'user_id': user_id,
                'request_id': request_id if pd.notna(request_id) else None,
                'details': {'message': text[:200]}
            })
            continue

        # --- Pending payout / earnings not withdrawable ---
        if any(kw in text_lower for kw in [
            'still pending', 'masih tertunda',
            'isn\'t withdrawable', 'not withdrawable',
            'can change until', 'belum bisa ditarik'
        ]):
            amendments.append({
                'type': 'pending_unconfirmed',
                'user_id': user_id,
                'request_id': request_id if pd.notna(request_id) else None,
                'details': {'message': text[:200]}
            })
            continue

        # --- Subscription / service cancellation ---
        if any(kw in text_lower for kw in [
            'cancel', 'batal', 'discontinued', 'dihentikan',
            'terminated', 'expired', 'ended'
        ]) and any(kw in text_lower for kw in [
            'subscription', 'langganan', 'plan', 'service', 'membership'
        ]):
            amendments.append({
                'type': 'event_cancellation',
                'user_id': user_id,
                'request_id': request_id if pd.notna(request_id) else None,
                'related_event_id': related_event if pd.notna(related_event) else None,
                'details': {'message': text[:200]}
            })
            continue

        # --- Price increase / amount changed ---
        price_change_match = re.search(
            r'(?:price|harga|amount|biaya|charge|tarif)\s+(?:has\s+)?'
            r'(?:increased|changed|naik|berubah|updated)\s+(?:to\s+)?'
            r'(?:(?:INR|IDR|EUR|USD|ZAR)\s*)?'
            r'([\d,]+(?:\.\d+)?)',
            text, re.IGNORECASE
        )
        if price_change_match and pd.notna(related_event):
            amount_str = price_change_match.group(1).replace(',', '')
            try:
                new_amount = float(amount_str)
                amendments.append({
                    'type': 'amount_change',
                    'user_id': user_id,
                    'related_event_id': str(related_event).strip(),
                    'details': {'new_amount': new_amount, 'message': text[:200]}
                })
                continue
            except ValueError:
                pass

        # --- General informational (log but don't act) ---
        amendments.append({
            'type': 'info',
            'user_id': user_id,
            'request_id': request_id if pd.notna(request_id) else None,
            'details': {'message': text[:200]}
        })

    return amendments
