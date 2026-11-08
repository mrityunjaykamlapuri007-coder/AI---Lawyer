# Annotation guidelines (FIXTURE)

**Every row in `development.jsonl` and `test.jsonl` is FIXTURE data.** It was
written by the coding agent against the synthetic `TEST_ACT` corpus, only to
exercise the metrics and the retrieval harness. It is not a real legal
evaluation and must not be presented as one.

## Row schema

| field | meaning |
| --- | --- |
| `test_id` | unique row id |
| `split` | `development` or `test` |
| `scenario_id` | groups rows that describe the same story; must not appear in both splits |
| `category` | short issue label |
| `user_query` | the query sent to retrieval |
| `case_facts` | structured facts fed to applicability (fact type -> value) |
| `as_of_date` | date used for source validity and elapsed-day rules |
| `expected_provision_ids` | provisions a human says are relevant |
| `essential_provision_ids` | the subset whose absence is a critical omission; may be empty |
| `relevance_by_provision` | human grade 0-3 per provision |
| `applicability_by_provision` | `applicable`, `not_applicable` or `unknown` per provision |
| `expected_retrieval_status` | `ANSWERED`, `ABSTAIN` or `TODO_human` for real rows |
| `required_context_ids` | provisos/exceptions that must accompany a result |
| `labeling_status` | `FIXTURE` here; real rows must be `human_verified` only after a human reviews them |
| `annotation_author` | who labelled the row |

## Rules for real rows

1. A human must read the provision text in `provisions.json` before assigning a
   grade or applicability label.
2. Never copy a label from a model output.
3. Keep `essential_provision_ids` empty when the correct answer is an
   abstention or when no single provision is essential.
4. Real rows must stay `TODO_human` until reviewed. Do not relabel them as
   verified to make a metric look better.
5. Never tune on `test.jsonl`. Use `development.jsonl` only for diagnostics.
