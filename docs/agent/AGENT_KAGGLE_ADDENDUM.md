# AGENT_KAGGLE_ADDENDUM.md: the LLM runs on a Kaggle GPU

Read after AGENT_REAL_MODE_RUNBOOK.md. This replaces R4 (real LLM wiring) and amends R5 and R8.
All hard rules in AGENTS.md still apply. Never print or store tokens; secrets go in Kaggle Secrets (notebook) and `.env` (repo), never in code or notebook cells.

## Architecture
- Kaggle notebook (GPU): runs an OpenAI-compatible LLM server (vLLM) and exposes it through a tunnel.
- Mri's machine (or the agent's workspace): runs FastAPI + Streamlit + corpus + index. It calls the Kaggle LLM through the existing `openai_compatible` provider. No new adapter.
- Env on the app side: `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=<tunnel url>/v1`, `LLM_MODEL=<served model name>`, `LLM_API_KEY=<a random string chosen by Mri>`.
- The tunnel URL changes every Kaggle session. Never hardcode it. Read it from `.env` only.

## Model choice (decided by Mri: Llama 8B Instruct, assumed Meta-Llama-3.1-8B-Instruct; log the exact id used)
- This model is GATED. Mri must accept Meta's license on the model's Hugging Face page with his account, create a NEW read-only HF token (after revoking the old exposed one), and store it as Kaggle Secret `HF_TOKEN`. Alternative that avoids HF: attach the Llama model from Kaggle Models to the notebook after accepting its license there, and point `--model` at the attached path. Ask Mri which he did.
- Never print, log or commit the token. If a download returns 401/403, report "license not accepted or token wrong" and stop.
- Memory: 8B in fp16 is about 16 GB of weights, which does not fit one 16 GB T4. Pick one, in this order:
  1. T4 x2 with `--tensor-parallel-size 2 --dtype half --max-model-len 8192` (fp16, best quality).
  2. Single GPU with a 4-bit build (AWQ or bitsandbytes), `--max-model-len 8192`.
  If a notebook has only one GPU, use option 2. Log the choice and the GPU type in results.
- Llama 3.1 supports a long context, but cap it at 8192 here to fit memory.
- An 8B model is weaker at strict JSON than larger ones. Turn `LLM_JSON_SCHEMA_MODE` on by default for this model, keep temperature at 0 for extraction and grading steps, and keep the retry-twice-then-reject rule. Every schema failure goes in `llm_failures.jsonl` unedited; these are the "where AI got it wrong" evidence.
- If the model fails to load twice, stop and report. The fallback is a smaller ungated instruct model; do not silently substitute one.

## Task K1: `kaggle/serve_llm.ipynb` (45 min)
Write a notebook with these cells, in order. Do not run anything yourself; write it and test pieces that can run locally with the fake provider.
1. Settings: GPU on, Internet on (needs phone-verified account; Mri must enable it).
2. `pip install vllm` (pin a version that works on the Kaggle CUDA image; if the install breaks, report the exact error).
3. Read `API_KEY`, `HF_TOKEN` (unless the model is attached from Kaggle Models) and `NGROK_TOKEN` (if used) from Kaggle Secrets via `UserSecretsClient`. Pass the HF token to the process through an environment variable, never on the command line, and never print it.
4. Launch `python -m vllm.entrypoints.openai.api_server --model <id> --quantization awq --dtype half --max-model-len 8192 --api-key $API_KEY --served-model-name refund-llm --port 8000` in the background, with logs to a file.
5. Wait for `/v1/models` to respond (poll with timeout 10 min).
6. Open the tunnel (cloudflared quick tunnel needs no account; ngrok needs the token). Print ONLY the public URL.
7. Keep-alive loop that prints a heartbeat every 60 seconds and writes vLLM log tails, so a dead server is visible.
Structured output: vLLM supports JSON-schema constrained decoding through `response_format` / `guided_json`. In the app's `openai_compatible` provider, pass the pydantic JSON schema for fact extraction, relevance grading and drafting when `LLM_JSON_SCHEMA_MODE=true`. Keep the existing "retry twice then reject" rule on top of it. Log every schema failure verbatim.

## Task K2: app-side wiring and smoke (30 min)
- Add `LLM_JSON_SCHEMA_MODE`, `LLM_TIMEOUT_S` (default 120), `LLM_MAX_RETRIES_HTTP` (default 2) to settings and `.env.example` (placeholders only).
- The provider must handle: tunnel down (clear error, no silent fallback to the fake model in real mode), slow first call (cold start), 401 (bad key).
- `python -m ai_lawyer.tools.llm_smoke` as in R4, plus one latency and token log line per call to `evaluation/results/llm_calls.jsonl` (model, prompt tokens, completion tokens, seconds).
- Fail loudly if `CORPUS_MODE=real` and the LLM is the fake provider.

## Task K3: batch evaluation notebook `kaggle/run_eval.ipynb` (45 min)
- Option 1 (preferred, simplest): evaluation runs on the app side against the Kaggle LLM through the tunnel (R6, R7 unchanged).
- Option 2 (if the tunnel is flaky): clone the repo inside Kaggle, run behaviour and retrieval eval there next to the model on `localhost`, and write raw outputs to `/kaggle/working/results/` for Mri to download. Raw files stay code-written and unedited.
- Either way, record in every results folder: model id, quantization, vLLM version, GPU type, date, and corpus verified-count.

## Task K4: embeddings and reranker on the GPU (optional, 20 min)
- If the embedding model is too slow locally, build the FAISS index inside the Kaggle notebook, download the index files and the corpus hash, and have the app verify the hash on load. A hash mismatch must refuse to load.
- Reranker (E4) only if time remains. Run it in the Kaggle eval notebook and report it as a separate row; the default pipeline stays reranker-off.

## Prototype link: what is and is not honest (amends R8)
- A Kaggle session is temporary and ends. The tunnel URL dies with it. A reviewer clicking the link later may find nothing.
- Therefore the demo needs one of: (a) Mri keeps the Kaggle notebook and the app tunnel running until the reviewer is likely done, and says so in the submission; (b) the live demo uses a hosted LLM API key and Kaggle is used only for batch evaluation and logged results; (c) a recorded demo video as the fallback in all cases.
- Recommend (b) plus (c). Ask Mri which. Do not publish a public URL without his explicit OK.
- The UI banner must show the model in use, e.g. "LLM: refund-llm (7B, 4-bit) via Kaggle", and the corpus-verified count. Do not accept real personal data in the demo.

## Cut order for Kaggle work
1. Drop K4.
2. Drop Option 2 of K3.
3. Use a smaller model (3B–4B AWQ) if 7B is too slow or won't load. Log it; do not hide it.
Never cut: K1, K2, and the latency/token logging (it feeds the cost section of the doc).

## Report after each task
Task id, status label, command, real output, blockers. Flag anything that needs Mri: Internet toggle, phone verification, secrets, model choice, tunnel URL.
