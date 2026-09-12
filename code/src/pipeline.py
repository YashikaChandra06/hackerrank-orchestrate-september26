"""
Buy or Wait? — AI Financial Affordability Agent Pipeline.

Fully deterministic, high-accuracy financial engine conforming to the HackerRank Orchestrate contract.
Reconstructs user financial position, detects recurring patterns, evaluates payment options,
optimizes spending changes, and generates validated output.csv.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import calendar
import math
import os
import sys
import traceback

from src.config import (
    FORECAST_DAYS, OUTPUT_COLUMNS, VALID_STATUSES, VALID_METHODS, OUTPUT_PATH,
    ROOT_OUTPUT_PATH, REQUESTS_CSV, FINANCIAL_PROFILES_CSV, FINANCIAL_EVENTS_CSV,
    EXCHANGE_RATES_CSV, PAYMENT_OPTIONS_CSV, MESSAGES_CSV, IMAGES_CSV
)
from src.ingestion.csv_loader import DataStore
from src.ingestion.image_parser import resolve_blank_amounts
from src.ingestion.message_parser import parse_messages
from src.finance.currency import CurrencyConverter


def add_calendar_months(dt, n_months, target_day=None):
    """Add n_months to dt, snapping to target_day and clamping to month end."""
    day = target_day if target_day is not None else dt.day
    year = dt.year + (dt.month + n_months - 1) // 12
    month = (dt.month + n_months - 1) % 12 + 1
    max_days = calendar.monthrange(year, month)[1]
    return pd.Timestamp(year=year, month=month, day=min(day, max_days))


def format_date(dt):
    """Format a Timestamp as YYYY-MM-DD."""
    if dt is None or pd.isna(dt):
        return ''
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime('%Y-%m-%d')


def format_amount(amt):
    """Format an amount according to challenge rules."""
    if amt is None or pd.isna(amt):
        return '0'
    f_amt = float(amt)
    if f_amt.is_integer():
        return str(int(f_amt))
    # If standard 2 decimal places has trailing zero after 2 decimals
    s = f"{f_amt:.2f}"
    return s


def parse_pipe_list(val):
    """Parse a pipe-separated string into a set of stripped strings."""
    if pd.isna(val) or val is None:
        return set()
    return {x.strip() for x in str(val).split('|') if x.strip()}


def resolve_events(raw_events, user_amendments, request_date, home_currency,
                   converter, min_balance):
    """Resolve user financial events into categorized cash flows.

    Filters out invalid events, converts currencies, detects recurring patterns.
    Returns dict with categorized event lists.
    """
    forecast_end = request_date + timedelta(days=FORECAST_DAYS)

    # Process message amendments
    salary_override = None
    salary_reduced = None
    salary_date_override = None
    contract_ended = False

    for a in user_amendments:
        atype = a.get('type')
        if atype == 'salary_change':
            salary_override = a['details'].get('new_salary')
        elif atype == 'salary_reduced':
            salary_reduced = a['details'].get('reduced_salary')
        elif atype == 'salary_date_change':
            salary_date_override = a['details'].get('new_date')
        elif atype == 'contract_ended':
            contract_ended = True

    settled_debits_by_key = defaultdict(list)
    settled_salary_events = []
    scheduled_credits = []
    scheduled_debits = []
    pending_debits = []

    latest_flexible_by_key = {}

    for ev in raw_events:
        eid = str(ev['event_id']).strip()
        status = str(ev.get('status', '')).strip().lower()
        direction = str(ev.get('direction', '')).strip().lower()
        ev_type = str(ev.get('event_type', '')).strip().lower()
        cat = str(ev.get('category', '')).strip().lower()
        amt = ev.get('amount')
        cur = str(ev.get('currency', home_currency)).strip()
        s_date = pd.Timestamp(ev['settlement_date']) if pd.notna(ev.get('settlement_date')) else pd.Timestamp(ev['event_date'])
        flex = str(ev.get('flexibility', 'fixed')).strip().lower()
        min_allowed = ev.get('minimum_allowed_amount')
        min_allowed = float(min_allowed) if pd.notna(min_allowed) else None
        desc = str(ev.get('description', '')).strip()

        # Skip invalid / unrealized events
        if status in ('cancelled', 'failed', 'unrealized'):
            continue
        if ev_type == 'investment_valuation':
            continue
        if pd.isna(amt) or amt is None:
            continue
        amt = float(amt)
        if amt <= 0:
            continue

        # Currency conversion
        if cur.upper() != home_currency.upper() and s_date is not None:
            amt = converter.convert(amt, cur.upper(), home_currency.upper(), s_date)

        # Check for final payroll indicator
        if 'final employer payroll' in desc.lower():
            contract_ended = True

        # Track latest flexible event
        if flex in ('stoppable', 'reducible', 'reducible_or_stoppable'):
            flex_key = (cat, desc) if cat in ('streaming', 'subscription', 'cloud_storage', 'gym', 'music_subscription', 'delivery_membership') else cat
            if flex_key not in latest_flexible_by_key or s_date > latest_flexible_by_key[flex_key]['date']:
                latest_flexible_by_key[flex_key] = {
                    'event_id': eid, 'category': cat, 'description': desc,
                    'amount': amt, 'flexibility': flex, 'minimum_allowed': min_allowed,
                    'date': s_date
                }

        # Scheduled confirmed salary credits
        if status == 'scheduled' and direction == 'credit' and ev_type == 'income':
            scheduled_credits.append({
                'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat, 'description': desc
            })

        # Scheduled / pending debits in forecast window
        elif status in ('scheduled', 'pending') and direction == 'debit':
            if request_date <= s_date <= forecast_end:
                if status == 'pending':
                    pending_debits.append({'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat, 'eid': eid})
                else:
                    scheduled_debits.append({'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat, 'eid': eid})

        # Settled debits in the past
        elif status == 'settled' and direction == 'debit':
            if s_date < request_date:
                # Group variable essential spending by category, fixed commitments by category+desc
                if cat in ('groceries', 'transport', 'dining'):
                    group_key = cat
                else:
                    group_key = f"{cat}_{desc}"
                settled_debits_by_key[group_key].append({
                    'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat,
                    'flexibility': flex, 'min_allowed': min_allowed, 'description': desc
                })

        # Settled salary in the past
        elif status == 'settled' and direction == 'credit' and ev_type == 'income':
            if 'salary' in desc.lower() or 'payroll' in desc.lower() or cat == 'salary':
                settled_salary_events.append({
                    'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat, 'description': desc
                })

    # ── Determine Salary Projection ──
    projected_credits = []
    salary_settlement_dates = []

    if not contract_ended:
        salary_amt = None
        salary_day = 15
        base_date = None

        if scheduled_credits:
            first_sched = sorted(scheduled_credits, key=lambda x: x['date'])[0]
            salary_amt = first_sched['amount']
            salary_day = first_sched['date'].day
            base_date = first_sched['date']
        elif settled_salary_events:
            settled_salary_events.sort(key=lambda x: x['date'])
            latest_sal = settled_salary_events[-1]
            salary_amt = latest_sal['amount']
            salary_day = latest_sal['date'].day
            base_date = latest_sal['date']

        if salary_override is not None:
            salary_amt = salary_override
        if salary_reduced is not None:
            salary_amt = salary_reduced
        if salary_date_override is not None:
            try:
                salary_day = pd.Timestamp(salary_date_override).day
            except Exception:
                pass

        if salary_amt is not None and base_date is not None:
            for m_offset in range(-1, 5):
                cur_sal_date = add_calendar_months(request_date, m_offset, target_day=salary_day)
                if request_date <= cur_sal_date <= forecast_end:
                    projected_credits.append({
                        'date': cur_sal_date, 'amount': salary_amt, 'category': 'salary'
                    })
                    salary_settlement_dates.append(cur_sal_date)

    # ── Project Recurring Debits ──
    projected_debits = []
    all_flexible_streams = []

    for group_key, entries in settled_debits_by_key.items():
        if not entries:
            continue
        entries.sort(key=lambda x: x['date'])
        cat = entries[0]['category']

        # Skip one-time categories that should not recur
        if cat in ('shopping', 'work_expense', 'windfall', 'investment', 'family_transfer'):
            continue

        if len(entries) == 1:
            # Fixed monthly commitments still recur monthly
            if cat in ('rent', 'utilities', 'debt_repayment', 'streaming', 'music_subscription',
                       'cloud_storage', 'delivery_membership', 'gym', 'insurance', 'education'):
                latest = entries[-1]
                target_day = latest['date'].day
                amt = latest['amount']
                eid = latest['event_id']
                flex = latest['flexibility']
                min_a = latest['min_allowed']

                for m_offset in range(0, 4):
                    p_date = add_calendar_months(request_date, m_offset, target_day=target_day)
                    if request_date <= p_date <= forecast_end:
                        projected_debits.append({
                            'date': p_date, 'amount': amt, 'category': cat,
                            'event_id': eid, 'flexibility': flex, 'min_allowed': min_a
                        })
                        if flex in ('stoppable', 'reducible', 'reducible_or_stoppable'):
                            all_flexible_streams.append({
                                'event_id': eid, 'category': cat, 'amount': amt,
                                'flexibility': flex, 'min_allowed': min_a, 'date': p_date
                            })
            continue

        intervals = [(entries[i]['date'] - entries[i-1]['date']).days for i in range(1, len(entries))]
        median_interval = np.median(intervals)
        latest = entries[-1]
        amt = latest['amount']
        eid = latest['event_id']
        flex = latest['flexibility']
        min_a = latest['min_allowed']

        if 25 <= median_interval <= 35:
            # Monthly recurrence
            target_day = latest['date'].day
            for m_offset in range(0, 4):
                p_date = add_calendar_months(request_date, m_offset, target_day=target_day)
                if request_date <= p_date <= forecast_end:
                    projected_debits.append({
                        'date': p_date, 'amount': amt, 'category': cat,
                        'event_id': eid, 'flexibility': flex, 'min_allowed': min_a
                    })
                    if flex in ('stoppable', 'reducible', 'reducible_or_stoppable'):
                        all_flexible_streams.append({
                            'event_id': eid, 'category': cat, 'amount': amt,
                            'flexibility': flex, 'min_allowed': min_a, 'date': p_date
                        })
        elif median_interval > 0:
            # Periodic recurrence (weekly, bi-weekly, etc.)
            step_days = int(round(median_interval))
            if step_days < 5:
                step_days = 7
            cur_date = latest['date']
            while cur_date <= forecast_end:
                cur_date = cur_date + timedelta(days=step_days)
                if request_date <= cur_date <= forecast_end:
                    projected_debits.append({
                        'date': cur_date, 'amount': amt, 'category': cat,
                        'event_id': eid, 'flexibility': flex, 'min_allowed': min_a
                    })
                    if flex in ('stoppable', 'reducible', 'reducible_or_stoppable'):
                        all_flexible_streams.append({
                            'event_id': eid, 'category': cat, 'amount': amt,
                            'flexibility': flex, 'min_allowed': min_a, 'date': cur_date
                        })

    return {
        'projected_debits': projected_debits,
        'projected_credits': projected_credits,
        'scheduled_debits': scheduled_debits,
        'pending_debits': pending_debits,
        'salary_dates': sorted(salary_settlement_dates),
        'latest_flexible_by_key': latest_flexible_by_key,
        'all_flexible_streams': all_flexible_streams,
    }


def simulate_forecast(balance, request_date, resolved, extra_payments=None):
    """Simulate 90 days and return list of (date, balance) and minimum balance."""
    forecast_end = request_date + timedelta(days=FORECAST_DAYS)
    daily_net = defaultdict(float)

    for d in resolved['projected_debits']:
        daily_net[d['date']] -= d['amount']

    for c in resolved['projected_credits']:
        daily_net[c['date']] += c['amount']

    for d in resolved['scheduled_debits']:
        daily_net[d['date']] -= d['amount']

    for d in resolved['pending_debits']:
        daily_net[d['date']] -= d['amount']

    if extra_payments:
        for dt, amt in extra_payments:
            daily_net[dt] -= amt

    traj = []
    cur_bal = balance
    min_bal = balance
    cur = request_date
    while cur <= forecast_end:
        cur_bal += daily_net.get(cur, 0.0)
        traj.append((cur, cur_bal))
        min_bal = min(min_bal, cur_bal)
        cur += timedelta(days=1)

    return traj, min_bal


def process_request(req_row, profiles_by_user, events_by_user,
                    options_by_request, msgs_by_user, converter):
    """Process a single financial request and return an output row dict."""
    request_id = str(req_row['request_id']).strip()
    user_id = str(req_row['user_id']).strip()
    request_date = pd.Timestamp(req_row['request_date'])
    requested_amount = float(req_row['requested_amount'])
    desired_completion = pd.Timestamp(req_row['desired_completion_date'])
    allows_partial = bool(req_row.get('allows_partial_payment', False))

    profile = profiles_by_user.get(user_id)
    if profile is None:
        return make_fallback_result(req_row)

    home_currency = str(profile['home_currency']).strip()
    balance = float(profile['current_available_balance'])
    min_balance = float(profile['minimum_balance_to_keep'])

    payment_methods = parse_pipe_list(profile.get('payment_methods_user_will_consider', ''))
    reduce_cats = parse_pipe_list(profile.get('expense_categories_user_is_willing_to_reduce', ''))
    stop_cats = parse_pipe_list(profile.get('expense_categories_user_is_willing_to_stop', ''))
    max_install_months = profile.get('max_installment_months')
    max_install_months = int(float(max_install_months)) if pd.notna(max_install_months) and str(max_install_months).strip() != '' else None

    raw_events = events_by_user.get(user_id, [])
    user_amendments = msgs_by_user.get(user_id, [])

    # Resolve financial position
    resolved = resolve_events(raw_events, user_amendments, request_date, home_currency, converter, min_balance)

    # 1. Baseline forecast & exact closed-form amount_safe_to_pay
    traj, baseline_min = simulate_forecast(balance, request_date, resolved)
    min_surplus = min(b - min_balance for dt, b in traj)
    amount_safe = max(0.0, min(requested_amount, min_surplus))
    amount_safe = round(amount_safe, 2)

    # 2. Earliest date for full payment
    earliest_full = None
    if amount_safe >= requested_amount:
        earliest_full = request_date
    else:
        for s_date in resolved['salary_dates']:
            if s_date < request_date:
                continue
            traj_s, min_s = simulate_forecast(balance, request_date, resolved, extra_payments=[(s_date, requested_amount)])
            if min_s >= min_balance:
                earliest_full = s_date
                break

    # 3. Evaluate candidate payment plans
    candidates = []

    # (a) Full payment today without spending changes
    if 'full_payment' in payment_methods and amount_safe >= requested_amount:
        candidates.append({
            'request_id': request_id,
            'amount_safe_to_pay': amount_safe,
            'affordability_status': 'affordable_now',
            'recommended_payment_method': 'full_payment',
            'payment_plan': f"{format_date(request_date)}:{format_amount(requested_amount)}",
            'earliest_date_for_full_payment': format_date(request_date),
            'spending_changes_needed': 'none',
            '_completes_by_deadline': True,
            '_no_spending_changes': True,
            '_total_cost': requested_amount,
            '_first_payment_date': request_date,
            '_num_payments': 1,
            '_payment_option_id': 'payment_option_00',
        })

    # (b) Installments without spending changes
    payment_opts = options_by_request.get(request_id, [])
    if 'installments' in payment_methods:
        for opt in payment_opts:
            method = str(opt.get('payment_method', '')).strip().lower()
            if method != 'installments':
                continue
            opt_id = str(opt['payment_option_id']).strip()
            pay_amount = float(opt['payment_amount'])
            n_payments = int(opt['number_of_payments'])
            first_date = pd.Timestamp(opt['first_payment_date'])
            freq_days = opt.get('payment_frequency_days')
            freq_days = int(float(freq_days)) if pd.notna(freq_days) else 30
            total_payable = float(opt['total_payable_amount'])

            if max_install_months is not None:
                total_duration_months = (n_payments - 1) * freq_days / 30.0
                if total_duration_months > max_install_months:
                    continue

            schedule = []
            cd = first_date
            for i in range(n_payments):
                schedule.append((cd, pay_amount))
                cd = cd + timedelta(days=freq_days)

            _, min_inst = simulate_forecast(balance, request_date, resolved, extra_payments=schedule)
            if min_inst >= min_balance:
                last_payment_date = schedule[-1][0]
                plan_str = "|".join(f"{format_date(d)}:{format_amount(a)}" for d, a in schedule)
                candidates.append({
                    'request_id': request_id,
                    'amount_safe_to_pay': amount_safe,
                    'affordability_status': 'affordable_with_plan',
                    'recommended_payment_method': 'installments',
                    'payment_plan': plan_str,
                    'earliest_date_for_full_payment': format_date(earliest_full) if earliest_full else '',
                    'spending_changes_needed': 'none',
                    '_completes_by_deadline': last_payment_date <= desired_completion,
                    '_no_spending_changes': True,
                    '_total_cost': total_payable,
                    '_first_payment_date': first_date,
                    '_num_payments': n_payments,
                    '_payment_option_id': opt_id,
                })

    # (c) Partial payment without spending changes
    if allows_partial and 'partial_payment' in payment_methods:
        if 0 < amount_safe < requested_amount and earliest_full is not None:
            if earliest_full <= desired_completion:
                remainder = round(requested_amount - amount_safe, 2)
                part_sched = [(request_date, amount_safe), (earliest_full, remainder)]
                _, min_part = simulate_forecast(balance, request_date, resolved, extra_payments=part_sched)
                if min_part >= min_balance:
                    plan_str = f"{format_date(request_date)}:{format_amount(amount_safe)}|{format_date(earliest_full)}:{format_amount(remainder)}"
                    candidates.append({
                        'request_id': request_id,
                        'amount_safe_to_pay': amount_safe,
                        'affordability_status': 'affordable_with_plan',
                        'recommended_payment_method': 'partial_payment',
                        'payment_plan': plan_str,
                        'earliest_date_for_full_payment': format_date(earliest_full),
                        'spending_changes_needed': 'none',
                        '_completes_by_deadline': True,
                        '_no_spending_changes': True,
                        '_total_cost': requested_amount,
                        '_first_payment_date': request_date,
                        '_num_payments': 2,
                        '_payment_option_id': 'payment_option_zz',
                    })

    # (d) Wait without spending changes
    if 'full_payment' in payment_methods and earliest_full is not None and earliest_full > request_date:
        candidates.append({
            'request_id': request_id,
            'amount_safe_to_pay': amount_safe,
            'affordability_status': 'affordable_later',
            'recommended_payment_method': 'wait',
            'payment_plan': f"{format_date(earliest_full)}:{format_amount(requested_amount)}",
            'earliest_date_for_full_payment': format_date(earliest_full),
            'spending_changes_needed': 'none',
            '_completes_by_deadline': earliest_full <= desired_completion,
            '_no_spending_changes': True,
            '_total_cost': requested_amount,
            '_first_payment_date': earliest_full,
            '_num_payments': 1,
            '_payment_option_id': 'payment_option_zz',
        })

    # (e) Evaluate spending changes if needed
    if not candidates or not any(c['_completes_by_deadline'] for c in candidates):
        flex_items = resolved['latest_flexible_by_key']
        candidate_actions = []
        for k, f_info in flex_items.items():
            cat = f_info['category']
            eid = f_info['event_id']
            amt = f_info['amount']
            fl = f_info['flexibility']
            ma = f_info['minimum_allowed']

            if cat in stop_cats and fl in ('stoppable', 'reducible_or_stoppable'):
                candidate_actions.append({
                    'type': 'stop', 'event_id': eid, 'category': cat,
                    'str': f"stop:{eid}", 'new_amt': 0.0, 'eid': eid
                })
            if cat in reduce_cats and fl in ('reducible', 'reducible_or_stoppable'):
                if ma is not None and ma < amt:
                    candidate_actions.append({
                        'type': 'reduce', 'event_id': eid, 'category': cat,
                        'str': f"reduce_to:{eid}:{format_amount(ma)}", 'new_amt': ma, 'eid': eid
                    })

        from itertools import combinations
        for n in range(1, min(4, len(candidate_actions) + 1)):
            for combo in combinations(candidate_actions, n):
                if len(set(c['eid'] for c in combo)) != len(combo):
                    continue

                stop_eids = {c['eid'] for c in combo if c['type'] == 'stop'}
                reduce_map = {c['eid']: c['new_amt'] for c in combo if c['type'] == 'reduce'}

                mod_debits = []
                for d in resolved['projected_debits']:
                    if d['event_id'] in stop_eids:
                        continue
                    elif d['event_id'] in reduce_map:
                        mod_d = dict(d)
                        mod_d['amount'] = reduce_map[d['event_id']]
                        mod_debits.append(mod_d)
                    else:
                        mod_debits.append(d)

                mod_resolved = dict(resolved)
                mod_resolved['projected_debits'] = mod_debits

                # Try full payment today with changes
                traj_m, min_m = simulate_forecast(balance, request_date, mod_resolved, extra_payments=[(request_date, requested_amount)])
                if min_m >= min_balance and 'full_payment' in payment_methods:
                    chg_str = "|".join(c['str'] for c in combo)
                    candidates.append({
                        'request_id': request_id,
                        'amount_safe_to_pay': amount_safe,
                        'affordability_status': 'affordable_with_plan',
                        'recommended_payment_method': 'full_payment',
                        'payment_plan': f"{format_date(request_date)}:{format_amount(requested_amount)}",
                        'earliest_date_for_full_payment': format_date(earliest_full) if earliest_full else '',
                        'spending_changes_needed': chg_str,
                        '_completes_by_deadline': True,
                        '_no_spending_changes': False,
                        '_total_cost': requested_amount,
                        '_first_payment_date': request_date,
                        '_num_payments': 1,
                        '_payment_option_id': 'payment_option_00',
                    })

    # 4. Rank candidates and pick best plan
    if candidates:
        def rank_key(c):
            return (
                0 if c['_completes_by_deadline'] else 1,
                0 if c['_no_spending_changes'] else 1,
                c['_total_cost'],
                c['_first_payment_date'],
                c['_num_payments'],
                c['_payment_option_id']
            )
        candidates.sort(key=rank_key)
        best = candidates[0]
    else:
        best = {
            'request_id': request_id,
            'amount_safe_to_pay': amount_safe,
            'affordability_status': 'not_affordable',
            'recommended_payment_method': 'not_recommended',
            'payment_plan': 'none',
            'earliest_date_for_full_payment': format_date(earliest_full) if earliest_full else '',
            'spending_changes_needed': 'none',
        }

    # Generate explanation
    best['decision_explanation'] = generate_explanation(
        best['affordability_status'],
        best['recommended_payment_method'],
        best['amount_safe_to_pay'],
        requested_amount,
        min_balance,
        balance,
        home_currency,
        request_date,
        earliest_full,
        desired_completion,
        best,
        best['spending_changes_needed']
    )

    return {k: v for k, v in best.items() if not k.startswith('_')}


def generate_explanation(status, method, amount_safe, requested_amount,
                         min_balance, balance, currency, request_date,
                         earliest_full, desired_completion, plan, spending_changes):
    """Generate concise, grounded decision explanation."""
    req_formatted = f"{currency} {format_amount(requested_amount)}"
    min_formatted = f"{currency} {format_amount(min_balance)}"
    safe_formatted = f"{currency} {format_amount(amount_safe)}"

    if status == 'affordable_now':
        return f"Pay {req_formatted} today. This leaves at least {min_formatted} available over the next 90 days."

    elif status == 'affordable_with_plan':
        if method == 'installments':
            plan_str = plan.get('payment_plan', '')
            parts = plan_str.split('|') if plan_str != 'none' else []
            n_inst = len(parts)
            inst_amt = parts[0].split(':')[1] if parts else '0'
            start_date = parts[0].split(':')[0] if parts else format_date(request_date)
            try:
                start_dt = pd.Timestamp(start_date).strftime('%d %B %Y').lstrip('0')
            except:
                start_dt = start_date
            return f"Use {n_inst} installments of {currency} {inst_amt}, starting {start_dt}. This leaves at least {min_formatted} available."

        elif method == 'partial_payment':
            plan_str = plan.get('payment_plan', '')
            parts = plan_str.split('|') if plan_str != 'none' else []
            second_date = parts[1].split(':')[0] if len(parts) > 1 else ''
            second_amt = parts[1].split(':')[1] if len(parts) > 1 else ''
            try:
                sec_dt = pd.Timestamp(second_date).strftime('%d %B %Y').lstrip('0')
            except:
                sec_dt = second_date
            return f"Pay {safe_formatted} today and the remaining {currency} {second_amt} on {sec_dt}. This completes the full request and keeps the {min_formatted} minimum protected."

        elif method == 'full_payment' and spending_changes != 'none':
            actions = spending_changes.split('|')
            action_descs = []
            for act in actions:
                if act.startswith('stop:'):
                    eid = act.split(':')[1]
                    action_descs.append(f"stop {eid}")
                elif act.startswith('reduce_to:'):
                    parts = act.split(':')
                    eid, new_a = parts[1], parts[2]
                    action_descs.append(f"reduce {eid} to {currency} {new_a}")
            changes_desc = " and ".join(action_descs)
            return f"Apply spending changes ({changes_desc}), then pay {req_formatted} today. This leaves at least {min_formatted} available."

    elif status == 'affordable_later':
        earliest_str = plan.get('earliest_date_for_full_payment', '')
        try:
            earliest_dt = pd.Timestamp(earliest_str).strftime('%d %B %Y').lstrip('0')
        except:
            earliest_dt = earliest_str
        return f"Wait until {earliest_dt}, then pay {req_formatted} in full. Paying sooner would put the {min_formatted} minimum at risk."

    # not_affordable
    if amount_safe > 0:
        return f"Do not proceed with the {req_formatted} request. Although {safe_formatted} is available today, the full amount cannot be completed safely within 90 days."
    else:
        deadline_str = format_date(desired_completion)
        try:
            dl_dt = pd.Timestamp(deadline_str).strftime('%d %B %Y').lstrip('0')
            return f"Do not make this payment by {dl_dt}. None of the available options keeps the {min_formatted} minimum protected."
        except:
            return f"Do not proceed. None of the available options keeps the {min_formatted} minimum protected within the forecast period."


def make_fallback_result(req_row):
    """Fallback result when a request encounters an unrecoverable error."""
    rid = str(req_row['request_id']).strip()
    return {
        'request_id': rid,
        'amount_safe_to_pay': 0.0,
        'affordability_status': 'not_affordable',
        'recommended_payment_method': 'not_recommended',
        'payment_plan': 'none',
        'earliest_date_for_full_payment': '',
        'spending_changes_needed': 'none',
        'decision_explanation': 'Do not proceed. Insufficient financial data to verify affordability.',
    }


def validate_output(output_df, requests_df):
    """Strict validation of output.csv according to challenge contract."""
    errors = []

    # Check row count
    if len(output_df) != len(requests_df):
        errors.append(f"Row count mismatch: output has {len(output_df)}, expected {len(requests_df)}")

    # Check columns
    if list(output_df.columns) != OUTPUT_COLUMNS:
        errors.append(f"Column mismatch: got {list(output_df.columns)}, expected {OUTPUT_COLUMNS}")

    req_map = {str(r['request_id']).strip(): r for _, r in requests_df.iterrows()}

    for idx, row in output_df.iterrows():
        rid = str(row['request_id']).strip()
        req = req_map.get(rid)
        if req is None:
            errors.append(f"Row {idx}: unknown request_id '{rid}'")
            continue

        req_amount = float(req['requested_amount'])

        # amount_safe_to_pay
        safe = row['amount_safe_to_pay']
        try:
            safe = float(safe)
            if safe < 0:
                errors.append(f"[{rid}] amount_safe_to_pay ({safe}) < 0")
            if safe > req_amount + 0.01:
                errors.append(f"[{rid}] amount_safe_to_pay ({safe}) > requested_amount ({req_amount})")
        except:
            errors.append(f"[{rid}] amount_safe_to_pay is not a number: '{safe}'")

        # affordability_status
        status = str(row['affordability_status']).strip()
        if status not in VALID_STATUSES:
            errors.append(f"[{rid}] invalid affordability_status: '{status}'")

        # recommended_payment_method
        method = str(row['recommended_payment_method']).strip()
        if method not in VALID_METHODS:
            errors.append(f"[{rid}] invalid recommended_payment_method: '{method}'")

        # earliest_date_for_full_payment for affordable_now
        earliest = str(row.get('earliest_date_for_full_payment', '')).strip()
        req_date = format_date(req['request_date'])
        if status == 'affordable_now' and earliest != req_date:
            errors.append(f"[{rid}] affordable_now requires earliest_date == request_date ({req_date}), got '{earliest}'")

        # payment_plan format
        plan = str(row.get('payment_plan', '')).strip()
        if method == 'not_recommended' and plan != 'none':
            errors.append(f"[{rid}] not_recommended requires payment_plan 'none', got '{plan}'")

    return errors


def print_summary(output_df):
    """Print summary statistics for pipeline run."""
    print("\n" + "=" * 60)
    print("PIPELINE EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Total requests processed: {len(output_df)}")
    print("\nAffordability Statuses:")
    for status, count in output_df['affordability_status'].value_counts().items():
        pct = count / len(output_df) * 100
        print(f"  {status:25s}: {count:4d} ({pct:5.1f}%)")

    print("\nRecommended Payment Methods:")
    for method, count in output_df['recommended_payment_method'].value_counts().items():
        pct = count / len(output_df) * 100
        print(f"  {method:25s}: {count:4d} ({pct:5.1f}%)")

    has_spending = (output_df['spending_changes_needed'] != 'none').sum()
    print(f"\nRequests requiring spending changes: {has_spending}")
    print("=" * 60)


def run_pipeline():
    """Execute the full Buy or Wait pipeline."""
    print("=" * 60)
    print("Buy or Wait? — Financial Affordability Agent")
    print("=" * 60)

    # Phase 1: Load data
    store = DataStore()
    store.load_all()

    # Phase 2: Resolve blank amounts from images
    print("\n[Phase 2] Resolving blank amounts from images...")
    image_amounts = resolve_blank_amounts(store.events, store.images)
    for event_id, amount in image_amounts.items():
        mask = store.events['event_id'] == event_id
        store.events.loc[mask, 'amount'] = amount
    remaining_blanks = store.events['amount'].isna().sum()
    print(f"  Resolved {len(image_amounts)} amounts, {remaining_blanks} still blank")

    # Phase 3: Parse messages
    print("\n[Phase 3] Parsing messages...")
    amendments = parse_messages(store.messages, store.events)
    msg_types = defaultdict(int)
    for a in amendments:
        msg_types[a['type']] += 1
    for t, c in sorted(msg_types.items()):
        print(f"  {t}: {c}")

    # Phase 4: Currency converter
    print("\n[Phase 4] Setting up currency converter...")
    converter = CurrencyConverter(store.exchange_rates)

    # Phase 5: Build indices
    print("\n[Phase 5] Building indices...")
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

    # Phase 6: Process each request in requests.csv
    print(f"\n[Phase 6] Processing {len(store.requests)} requests...")
    results = []
    for idx, req_row in store.requests.iterrows():
        try:
            result = process_request(
                req_row, profiles_by_user, events_by_user,
                options_by_request, msgs_by_user, converter
            )
            results.append(result)
        except Exception as e:
            print(f"  ERROR on {req_row['request_id']}: {e}")
            traceback.print_exc()
            results.append(make_fallback_result(req_row))

        if (idx + 1) % 50 == 0:
            print(f"  Processed {idx + 1}/{len(store.requests)} requests...")

    # Phase 7: Build, validate, and write output
    print(f"\n[Phase 7] Building output ({len(results)} rows)...")
    output_df = pd.DataFrame(results, columns=OUTPUT_COLUMNS)

    errors = validate_output(output_df, store.requests)
    if errors:
        print(f"\n  VALIDATION WARNINGS ({len(errors)}):")
        for e in errors[:20]:
            print(f"    {e}")
    else:
        print("  All validation checks PASSED perfectly!")

    output_df.to_csv(OUTPUT_PATH, index=False)
    output_df.to_csv(ROOT_OUTPUT_PATH, index=False)
    print(f"\n  Output written to: {OUTPUT_PATH}")
    print(f"  Output written to: {ROOT_OUTPUT_PATH}")

    print_summary(output_df)

    return output_df
