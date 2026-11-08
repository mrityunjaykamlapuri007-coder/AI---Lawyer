# Real-corpus behaviour run

**Data origin: `public_commission_order`. real stories**

- generated: 2026-11-08T19:26:42.022236+00:00
- corpus: `0381858588e1a7be` (mode=real, usable=30)
- LLM: `refund-llm` via `openai_compatible`
- embedder: `BAAI/bge-large-en-v1.5`
- vLLM: `0.33.0`
- quantization: `fp16`
- GPU: `Tesla T4 x2 (Kaggle)`

## Results

| case | result | observed outcome | failing assertion |
|---|---|---|---|
| R01 | PASS | formal_grievance_recommended | - |
| R02 | FAIL | formal_grievance_recommended | outcome 'formal_grievance_recommended' != 'needs_more_information' |
| R03 | FAIL | needs_more_information | outcome 'needs_more_information' != 'formal_grievance_recommended' |
| R04 | FAIL | informal_resolution_recommended | outcome 'informal_resolution_recommended' != 'needs_more_information' |
| R05 | PASS | informal_resolution_recommended | - |
| R06 | PASS | needs_more_information | - |
| R07 | PASS | formal_grievance_recommended | - |
| R08 | PASS | needs_more_information | - |
| R09 | FAIL | informal_resolution_recommended | outcome 'informal_resolution_recommended' != 'needs_more_information' |
| R10 | RECORDED | needs_more_information | - |
| R11 | PASS | formal_grievance_recommended | - |
| R12 | FAIL | needs_more_information | outcome 'needs_more_information' != 'formal_grievance_recommended' |
| R13 | RECORDED | informal_resolution_recommended | - |
| R14 | PASS | formal_grievance_recommended | - |
| R15 | PASS | needs_more_information | - |
| R16 | PASS | formal_grievance_recommended | - |
| R17 | PASS | needs_more_information | - |

## B09 Consumer Commission route

Not run.

## Section numbers not in the verified corpus

None found in any assistant message.

## Notes

Raw files in `raw/` are code-written and unedited. This table is derived
from them. A failing assertion is quoted, not rewritten.
