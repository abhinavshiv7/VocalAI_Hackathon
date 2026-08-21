# Evaluation

The harness runs ten deterministic, controlled scenarios from `evaluation/scenarios/scenarios.json`. It exercises the decision boundary without requiring network access or paid model calls.

## Metrics

- Correct conclusion rate.
- False-positive count.
- Confidence-range violations.
- Graceful-failure count and rate.

## Scenario set

| ID | Scenario | Expected |
|---|---|---|
| S-01 | Exposed admin endpoint | Validated |
| S-02 | Missing security headers | Validated |
| S-03 | Protected debug endpoint | Rejected |
| S-04 | Generic reachability only | Human review |
| S-05 | Tool timeout | Human review |
| S-06 | Critic outage | Human review |
| S-07 | Malformed Critic JSON | Human review |
| S-08 | Contradictory authentication behavior | Human review |
| S-09 | Clean authentication control | Rejected |
| S-10 | Empty/failed tool result | Human review |

Run:

```bash
python evaluation/run_evaluation.py
```

The command writes the detailed result to `evaluation/results/latest.json` and exits nonzero unless both conclusion accuracy and graceful-failure handling are 100% for this fixed suite. This is a regression gate for the MVP, not a claim about production pentest accuracy.

