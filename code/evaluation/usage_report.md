# Token Usage and Cost Report

## Summary

This solution uses a **fully deterministic** pipeline.
No LLM API calls are made during processing.

## Model Usage

| Metric | Value |
|--------|-------|
| Model Provider | None (deterministic) |
| Model Name | N/A |
| Model Calls | 0 |
| Input Tokens | 0 |
| Output Tokens | 0 |
| Total Tokens | 0 |
| Average Tokens per Request | 0 |
| Estimated Total Cost | $0.00 |
| Estimated Cost per Request | $0.00 |

## Processing Details

| Metric | Value |
|--------|-------|
| Total Requests Processed | 250 |
| Total Runtime | 3.9s |
| Avg Time per Request | 0.02s |

## Notes

- Image amounts were extracted via visual inspection and hardcoded deterministically.
- Message parsing uses regex-based deterministic extraction.
- Financial forecasting is fully deterministic (no LLM involvement).
- Explanations are generated using template-based rules.
- No API keys or external services are required.
