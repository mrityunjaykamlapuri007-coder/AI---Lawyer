# Real-corpus behaviour run

**Data origin: `public_commission_order`. real stories**

- generated: 2026-11-08T22:09:44.925139+00:00
- corpus: `0381858588e1a7be` (mode=real, usable=30)
- LLM: `refund-llm` via `openai_compatible`
- embedder: `BAAI/bge-large-en-v1.5`
- vLLM: `0.33.0`
- quantization: `fp16`
- GPU: `Tesla_T4_x2_Kaggle`

## Results

| case | result | observed outcome | failing assertion |
|---|---|---|---|
| H01 | PASS | formal_grievance_recommended | - |
| H02 | PASS | formal_grievance_recommended | - |
| H03 | FAIL | out_of_scope | outcome 'out_of_scope' != 'formal_grievance_recommended' |
| H04 | PASS | needs_more_information | - |

## B09 Consumer Commission route

Not run.

## Section numbers not in the verified corpus

None found in any assistant message.

## Notes

Raw files in `raw/` are code-written and unedited. This table is derived
from them. A failing assertion is quoted, not rewritten.
