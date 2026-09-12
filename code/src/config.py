"""Configuration and paths for the Buy or Wait engine."""
import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(BASE_DIR)
DATASET_DIR = os.path.join(REPO_ROOT, 'dataset')
OUTPUT_PATH = os.path.join(DATASET_DIR, 'output.csv')
ROOT_OUTPUT_PATH = os.path.join(REPO_ROOT, 'output.csv')
MEDIA_DIR = os.path.join(DATASET_DIR, 'media', 'images')
EVAL_DIR = os.path.join(BASE_DIR, 'evaluation')

# Dataset file paths
REQUESTS_CSV = os.path.join(DATASET_DIR, 'requests.csv')
SAMPLE_REQUESTS_CSV = os.path.join(DATASET_DIR, 'sample_requests.csv')
FINANCIAL_PROFILES_CSV = os.path.join(DATASET_DIR, 'financial_profiles.csv')
FINANCIAL_EVENTS_CSV = os.path.join(DATASET_DIR, 'financial_events.csv')
EXCHANGE_RATES_CSV = os.path.join(DATASET_DIR, 'exchange_rates.csv')
PAYMENT_OPTIONS_CSV = os.path.join(DATASET_DIR, 'request_payment_options.csv')
MESSAGES_CSV = os.path.join(DATASET_DIR, 'messages.csv')
IMAGES_CSV = os.path.join(DATASET_DIR, 'images.csv')

# Financial constants
FORECAST_DAYS = 90

# Output columns in exact order
OUTPUT_COLUMNS = [
    'request_id', 'amount_safe_to_pay', 'affordability_status',
    'recommended_payment_method', 'payment_plan',
    'earliest_date_for_full_payment', 'spending_changes_needed',
    'decision_explanation'
]

VALID_STATUSES = ['affordable_now', 'affordable_with_plan', 'affordable_later', 'not_affordable']
VALID_METHODS = ['full_payment', 'partial_payment', 'installments', 'wait', 'not_recommended']
