"""
Test Refined Financial Engine on sample_requests.csv.
Incorporates:
1. Scheduled confirmed salary (+ recurring monthly projection)
2. Category-level recurrence detection for variable expenses (groceries, transport, dining)
3. Proper calendar-month projection without day-drifting or duplicate charges
4. Exact closed-form amount_safe_to_pay
5. Salary-date targeting for earliest_date_for_full_payment
6. Accurate spending-change evaluation
"""
import sys, os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import calendar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion.csv_loader import DataStore
from src.ingestion.image_parser import resolve_blank_amounts
from src.ingestion.message_parser import parse_messages
from src.finance.currency import CurrencyConverter
from src.config import FORECAST_DAYS, SAMPLE_REQUESTS_CSV

def add_calendar_months(dt, n_months, target_day=None):
    """Add n_months to dt, snapping to target_day (or dt.day) and clamping to month length."""
    day = target_day if target_day is not None else dt.day
    year = dt.year + (dt.month + n_months - 1) // 12
    month = (dt.month + n_months - 1) % 12 + 1
    max_days = calendar.monthrange(year, month)[1]
    return pd.Timestamp(year=year, month=month, day=min(day, max_days))

def resolve_user_financials(u_events, user_amendments, req_date, home_currency, converter, min_balance):
    """Refined event resolver."""
    forecast_end = req_date + timedelta(days=FORECAST_DAYS)

    # Process message amendments
    salary_override = None
    salary_reduced = None
    salary_date_override = None
    contract_ended = False

    for a in user_amendments:
        t = a['type']
        if t == 'salary_change':
            salary_override = a['details'].get('new_salary')
        elif t == 'salary_reduced':
            salary_reduced = a['details'].get('reduced_salary')
        elif t == 'salary_date_change':
            salary_date_override = a['details'].get('new_date')
        elif t == 'contract_ended':
            contract_ended = True

    # 1. Separate events
    settled_debits_by_cat = defaultdict(list)
    settled_salary_events = []
    scheduled_credits = []
    scheduled_debits = []
    pending_debits = []

    # Map for latest event of each category/subscription
    latest_flexible_by_cat = {}

    for ev in u_events:
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

        if status in ('cancelled', 'failed', 'unrealized'):
            continue
        if ev_type == 'investment_valuation':
            continue
        if pd.isna(amt) or amt is None:
            continue
        amt = float(amt)
        if amt <= 0:
            continue

        # Convert currency
        if cur.upper() != home_currency.upper() and s_date is not None:
            amt = converter.convert(amt, cur.upper(), home_currency.upper(), s_date)

        # Track latest flexible event
        if flex in ('stoppable', 'reducible', 'reducible_or_stoppable'):
            key = (cat, desc) if cat in ('streaming', 'subscription', 'cloud_storage', 'gym', 'music_subscription', 'delivery_membership') else cat
            if key not in latest_flexible_by_cat or s_date > latest_flexible_by_cat[key]['date']:
                latest_flexible_by_cat[key] = {
                    'event_id': eid, 'category': cat, 'description': desc,
                    'amount': amt, 'flexibility': flex, 'minimum_allowed': min_allowed,
                    'date': s_date
                }

        # Handle scheduled credits (salary)
        if status == 'scheduled' and direction == 'credit' and ev_type == 'income':
            scheduled_credits.append({
                'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat, 'description': desc
            })

        # Handle scheduled / pending debits in forecast window
        elif status in ('scheduled', 'pending') and direction == 'debit':
            if req_date <= s_date <= forecast_end:
                if status == 'pending':
                    pending_debits.append({'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat})
                else:
                    scheduled_debits.append({'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat})

        # Settled debits in the past
        elif status == 'settled' and direction == 'debit':
            if s_date < req_date:
                # Key by (category, desc) for fixed subscriptions/utilities, or by category for variable spending
                if cat in ('groceries', 'transport', 'dining'):
                    key = cat
                else:
                    key = f"{cat}_{desc}"
                settled_debits_by_cat[key].append({
                    'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat,
                    'flexibility': flex, 'min_allowed': min_allowed, 'description': desc
                })

        # Settled salary in the past
        elif status == 'settled' and direction == 'credit' and ev_type == 'income':
            if 'salary' in desc.lower() or 'payroll' in desc.lower() or cat == 'salary':
                settled_salary_events.append({
                    'event_id': eid, 'date': s_date, 'amount': amt, 'category': cat, 'description': desc
                })

    # 2. Determine Salary Schedule
    projected_credits = []
    salary_settlement_dates = []

    if not contract_ended:
        # Check if there is a scheduled confirmed salary
        salary_amt = None
        salary_day = 15 # default

        if scheduled_credits:
            # Use the first scheduled salary
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
        else:
            base_date = None

        if salary_override is not None:
            salary_amt = salary_override
        if salary_reduced is not None:
            salary_amt = salary_reduced
        if salary_date_override is not None:
            try:
                salary_day = pd.Timestamp(salary_date_override).day
            except:
                pass

        if salary_amt is not None and base_date is not None:
            # Project monthly salary across forecast window
            # Start from the next occurrence on or after req_date
            # Check month of req_date
            for m_offset in range(-1, 5):
                cur_sal_date = add_calendar_months(req_date, m_offset, target_day=salary_day)
                if req_date <= cur_sal_date <= forecast_end:
                    projected_credits.append({
                        'date': cur_sal_date, 'amount': salary_amt, 'category': 'salary'
                    })
                    salary_settlement_dates.append(cur_sal_date)

    # 3. Project Recurring Debits
    projected_debits = []
    all_flexible_streams = []

    for key, entries in settled_debits_by_cat.items():
        if len(entries) == 0:
            continue
        entries.sort(key=lambda x: x['date'])
        cat = entries[0]['category']

        # Determine recurrence
        if len(entries) == 1:
            # If it's a fixed monthly category (rent, utilities, subscription), still recurs monthly!
            if cat in ('rent', 'utilities', 'debt_repayment', 'streaming', 'music_subscription',
                        'cloud_storage', 'delivery_membership', 'gym', 'insurance', 'education'):
                latest = entries[-1]
                target_day = latest['date'].day
                amt = latest['amount']
                eid = latest['event_id']
                flex = latest['flexibility']
                min_a = latest['min_allowed']

                for m_offset in range(0, 4):
                    p_date = add_calendar_months(req_date, m_offset, target_day=target_day)
                    if req_date <= p_date <= forecast_end:
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

        # If >= 2 entries, calculate intervals
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
                p_date = add_calendar_months(req_date, m_offset, target_day=target_day)
                if req_date <= p_date <= forecast_end:
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
            # Periodic recurrence (e.g. weekly ~7d, bi-weekly ~14d, 21d)
            step_days = int(round(median_interval))
            if step_days < 5:
                step_days = 7
            cur_date = latest['date']
            while cur_date <= forecast_end:
                cur_date = cur_date + timedelta(days=step_days)
                if req_date <= cur_date <= forecast_end:
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
        'latest_flexible_by_cat': latest_flexible_by_cat,
        'all_flexible_streams': all_flexible_streams,
    }

def simulate_daily_forecast(balance, req_date, resolved, extra_payments=None):
    """Simulate 90 days and return list of (date, balance) and min_balance."""
    forecast_end = req_date + timedelta(days=FORECAST_DAYS)
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
    cur = req_date
    while cur <= forecast_end:
        cur_bal += daily_net.get(cur, 0.0)
        traj.append((cur, cur_bal))
        min_bal = min(min_bal, cur_bal)
        cur += timedelta(days=1)

    return traj, min_bal

def evaluate_refined_on_samples():
    store = DataStore()
    store.load_all()

    # Images
    image_amounts = resolve_blank_amounts(store.events, store.images)
    for event_id, amount in image_amounts.items():
        mask = store.events['event_id'] == event_id
        store.events.loc[mask, 'amount'] = amount

    amendments = parse_messages(store.messages, store.events)
    converter = CurrencyConverter(store.exchange_rates)

    sample_df = pd.read_csv(SAMPLE_REQUESTS_CSV)

    msgs_by_user = defaultdict(list)
    for a in amendments:
        msgs_by_user[a['user_id']].append(a)

    options_by_request = defaultdict(list)
    for _, row in store.payment_options.iterrows():
        options_by_request[str(row['request_id']).strip()].append(row)

    matches = defaultdict(int)
    total = len(sample_df)

    print("=" * 75)
    print("Evaluating Refined Engine on 25 Samples")
    print("=" * 75)

    for _, row in sample_df.iterrows():
        rid = row['request_id']
        uid = str(row['user_id']).strip()
        req_date = pd.Timestamp(row['request_date'])
        req_amt = float(row['requested_amount'])
        desired_completion = pd.Timestamp(row['desired_completion_date'])
        allows_partial = bool(row.get('allows_partial_payment', False))

        prof = store.profiles[store.profiles['user_id'] == uid].iloc[0]
        cur_bal = float(prof['current_available_balance'])
        min_bal = float(prof['minimum_balance_to_keep'])
        home_cur = str(prof['home_currency']).strip()

        # Prefs
        from src.pipeline import parse_pipe_list, format_date, format_amount
        pay_methods = parse_pipe_list(prof.get('payment_methods_user_will_consider', ''))
        reduce_cats = parse_pipe_list(prof.get('expense_categories_user_is_willing_to_reduce', ''))
        stop_cats = parse_pipe_list(prof.get('expense_categories_user_is_willing_to_stop', ''))
        max_inst = prof.get('max_installment_months')
        max_inst = int(float(max_inst)) if pd.notna(max_inst) and str(max_inst).strip() != '' else None

        u_events = store.events[store.events['user_id'] == uid].to_dict('records')
        u_amends = msgs_by_user[uid]

        resolved = resolve_user_financials(u_events, u_amends, req_date, home_cur, converter, min_bal)

        # Baseline forecast
        traj, min_seen = simulate_daily_forecast(cur_bal, req_date, resolved)

        # 1. Closed-form amount_safe_to_pay
        min_surplus = min(b - min_bal for dt, b in traj)
        amount_safe = max(0.0, min(req_amt, min_surplus))
        amount_safe = round(amount_safe, 2)

        # 2. Earliest date for full payment
        earliest_full = None
        if amount_safe >= req_amt:
            earliest_full = req_date
        else:
            # Test dates where balance increases (salary dates)
            for s_date in resolved['salary_dates']:
                if s_date < req_date:
                    continue
                # Check if paying req_amt on s_date is safe for all subsequent days
                traj_at_s, min_at_s = simulate_daily_forecast(cur_bal, req_date, resolved, extra_payments=[(s_date, req_amt)])
                if min_at_s >= min_bal:
                    earliest_full = s_date
                    break

        # 3. Generate Candidates
        candidates = []

        # (a) Full payment now
        if 'full_payment' in pay_methods and amount_safe >= req_amt:
            candidates.append({
                'amount_safe_to_pay': amount_safe,
                'affordability_status': 'affordable_now',
                'recommended_payment_method': 'full_payment',
                'payment_plan': f"{format_date(req_date)}:{format_amount(req_amt)}",
                'earliest_date_for_full_payment': format_date(req_date),
                'spending_changes_needed': 'none',
                '_completes_by_deadline': True,
                '_no_spending_changes': True,
                '_total_cost': req_amt,
                '_first_payment_date': req_date,
                '_num_payments': 1,
                '_payment_option_id': 'payment_option_00',
            })

        # (b) Installments without changes
        opts = options_by_request[rid]
        if 'installments' in pay_methods:
            for opt in opts:
                method = str(opt.get('payment_method', '')).strip().lower()
                if method != 'installments':
                    continue
                opt_id = str(opt['payment_option_id']).strip()
                p_amt = float(opt['payment_amount'])
                n_p = int(opt['number_of_payments'])
                f_date = pd.Timestamp(opt['first_payment_date'])
                freq = opt.get('payment_frequency_days')
                freq = int(float(freq)) if pd.notna(freq) else 30
                tot_p = float(opt['total_payable_amount'])

                if max_inst is not None:
                    tot_m = (n_p - 1) * freq / 30.0
                    if tot_m > max_inst:
                        continue

                sched = []
                c_d = f_date
                for i in range(n_p):
                    sched.append((c_d, p_amt))
                    c_d = c_d + timedelta(days=freq)

                _, min_inst = simulate_daily_forecast(cur_bal, req_date, resolved, extra_payments=sched)
                if rid == 'request_12':
                    print(f"  [DEBUG r12] opt={opt_id}, min_inst={min_inst}, min_bal={min_bal}, n_p={n_p}, tot_m={(n_p-1)*freq/30.0}, max_inst={max_inst}")
                if min_inst >= min_bal:

                    last_d = sched[-1][0]
                    plan_str = "|".join(f"{format_date(d)}:{format_amount(a)}" for d, a in sched)
                    candidates.append({
                        'amount_safe_to_pay': amount_safe,
                        'affordability_status': 'affordable_with_plan',
                        'recommended_payment_method': 'installments',
                        'payment_plan': plan_str,
                        'earliest_date_for_full_payment': format_date(earliest_full) if earliest_full else '',
                        'spending_changes_needed': 'none',
                        '_completes_by_deadline': last_d <= desired_completion,
                        '_no_spending_changes': True,
                        '_total_cost': tot_p,
                        '_first_payment_date': f_date,
                        '_num_payments': n_p,
                        '_payment_option_id': opt_id,
                    })

        # (c) Partial payment
        if allows_partial and 'partial_payment' in pay_methods:
            if 0 < amount_safe < req_amt and earliest_full is not None:
                if earliest_full <= desired_completion:
                    rem = round(req_amt - amount_safe, 2)
                    # Check safety of partial schedule
                    part_sched = [(req_date, amount_safe), (earliest_full, rem)]
                    _, min_part = simulate_daily_forecast(cur_bal, req_date, resolved, extra_payments=part_sched)
                    if min_part >= min_bal:
                        plan_str = f"{format_date(req_date)}:{format_amount(amount_safe)}|{format_date(earliest_full)}:{format_amount(rem)}"
                        candidates.append({
                            'amount_safe_to_pay': amount_safe,
                            'affordability_status': 'affordable_with_plan',
                            'recommended_payment_method': 'partial_payment',
                            'payment_plan': plan_str,
                            'earliest_date_for_full_payment': format_date(earliest_full),
                            'spending_changes_needed': 'none',
                            '_completes_by_deadline': True,
                            '_no_spending_changes': True,
                            '_total_cost': req_amt,
                            '_first_payment_date': req_date,
                            '_num_payments': 2,
                            '_payment_option_id': 'payment_option_zz',
                        })

        # (d) Wait
        if 'full_payment' in pay_methods and earliest_full is not None and earliest_full > req_date:
            candidates.append({
                'amount_safe_to_pay': amount_safe,
                'affordability_status': 'affordable_later',
                'recommended_payment_method': 'wait',
                'payment_plan': f"{format_date(earliest_full)}:{format_amount(req_amt)}",
                'earliest_date_for_full_payment': format_date(earliest_full),
                'spending_changes_needed': 'none',
                '_completes_by_deadline': earliest_full <= desired_completion,
                '_no_spending_changes': True,
                '_total_cost': req_amt,
                '_first_payment_date': earliest_full,
                '_num_payments': 1,
                '_payment_option_id': 'payment_option_zz',
            })

        # (e) Try spending changes if no candidate completes by deadline
        if not candidates or not any(c['_completes_by_deadline'] for c in candidates):
            # Try spending changes
            # Collect flexible items
            flex_items = resolved['latest_flexible_by_cat']
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
                    # Check unique eids
                    if len(set(c['eid'] for c in combo)) != len(combo):
                        continue

                    # Apply to resolved
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

                    # Check if full payment now becomes safe
                    traj_m, min_m = simulate_daily_forecast(cur_bal, req_date, mod_resolved, extra_payments=[(req_date, req_amt)])
                    if min_m >= min_bal and 'full_payment' in pay_methods:
                        chg_str = "|".join(c['str'] for c in combo)
                        candidates.append({
                            'amount_safe_to_pay': amount_safe,
                            'affordability_status': 'affordable_with_plan',
                            'recommended_payment_method': 'full_payment',
                            'payment_plan': f"{format_date(req_date)}:{format_amount(req_amt)}",
                            'earliest_date_for_full_payment': format_date(earliest_full) if earliest_full else '',
                            'spending_changes_needed': chg_str,
                            '_completes_by_deadline': True,
                            '_no_spending_changes': False,
                            '_total_cost': req_amt,
                            '_first_payment_date': req_date,
                            '_num_payments': 1,
                            '_payment_option_id': 'payment_option_00',
                        })

        # Rank candidates
        best = None
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
                'amount_safe_to_pay': amount_safe,
                'affordability_status': 'not_affordable',
                'recommended_payment_method': 'not_recommended',
                'payment_plan': 'none',
                'earliest_date_for_full_payment': format_date(earliest_full) if earliest_full else '',
                'spending_changes_needed': 'none',
            }

        # Compare with ground truth
        diffs = []
        fields = ['amount_safe_to_pay', 'affordability_status', 'recommended_payment_method',
                  'payment_plan', 'earliest_date_for_full_payment', 'spending_changes_needed']

        for f in fields:
            exp = str(row.get(f, '')).strip()
            if exp == 'nan': exp = ''
            act = str(best.get(f, '')).strip()
            if act == 'nan': act = ''

            if f == 'amount_safe_to_pay':
                try:
                    m = abs(float(exp) - float(act)) < 0.1
                except:
                    m = (exp == act)
            else:
                m = (exp == act)

            if m:
                matches[f] += 1
            else:
                diffs.append((f, exp, act))

        if diffs:
            print(f"[{rid}] DIFFS ({len(diffs)}):")
            for f, e, a in diffs:
                print(f"    {f:30s} | EXP: {e:25s} | GOT: {a:25s}")
        else:
            print(f"[{rid}] 100% MATCH! ({best['affordability_status']}, {best['recommended_payment_method']})")

    print("\n" + "=" * 75)
    print("REFINED ENGINE ACCURACY RESULTS")
    print("=" * 75)
    for f in fields:
        print(f"  {f:32s}: {matches[f]:2d}/{total:2d} ({matches[f]/total*100:5.1f}%)")

if __name__ == '__main__':
    evaluate_refined_on_samples()

