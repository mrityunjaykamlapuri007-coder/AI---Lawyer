# Real-corpus behaviour run

**Data origin: `public_commission_order`. real stories**

- generated: 2026-11-08T19:54:40.516656+00:00
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
| R02 | FAIL |  | pipeline crashed: UserSafeError: The drafting step returned an invalid response. No legal conclusion was produced.; outcome None != 'needs_more_information' |
| R03 | FAIL |  | pipeline crashed: UserSafeError: The drafting step returned an invalid response. No legal conclusion was produced.; outcome None != 'formal_grievance_recommended' |
| R04 | PASS | needs_more_information | - |
| R05 | FAIL | needs_more_information | outcome 'needs_more_information' != 'informal_resolution_recommended' |
| R06 | PASS | needs_more_information | - |
| R07 | FAIL | needs_more_information | outcome 'needs_more_information' != 'formal_grievance_recommended' |
| R08 | PASS | needs_more_information | - |
| R09 | PASS | needs_more_information | - |
| R10 | RECORDED | needs_more_information | - |
| R11 | FAIL | needs_more_information | outcome 'needs_more_information' != 'formal_grievance_recommended' |
| R12 | FAIL | needs_more_information | outcome 'needs_more_information' != 'formal_grievance_recommended' |
| R13 | RECORDED | needs_more_information | - |
| R14 | PASS | formal_grievance_recommended | - |
| R15 | FAIL |  | pipeline crashed: LLMUnavailable: The model endpoint returned HTTP 530 after 3 attempt(s).; outcome None != 'needs_more_information' |
| R16 | FAIL |  | pipeline crashed: EmbedderUnavailable: embedder returned HTTP 530; outcome None != 'formal_grievance_recommended' |
| R17 | FAIL |  | pipeline crashed: EmbedderUnavailable: embedder returned HTTP 530; outcome None != 'needs_more_information' |

## B09 Consumer Commission route

Not run.

## Section numbers not in the verified corpus

None found in any assistant message.

## Notes

Raw files in `raw/` are code-written and unedited. This table is derived
from them. A failing assertion is quoted, not rewritten.
