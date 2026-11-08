# AGENT_GPU_ON_KAGGLE.md: all GPU and heavy-model work runs on Kaggle (decided by Mri)

## Precedence (read in this order; later files win on conflict)
1. AGENTS.md (hard rules)
2. AGENT_EXECUTION_SPEC.md (v3) and IMPLEMENTATION_PLAN.md
3. AGENT_REAL_MODE_RUNBOOK.md
4. AGENT_KAGGLE_ADDENDUM.md (Llama 8B on Kaggle)
5. AGENT_RISK_CONTROLS.md
6. AGENT_MACHINE_VERIFICATION.md (no human verifier; `machine_verified` status)
7. THIS FILE: overrides any instruction that installs or runs a GPU or large model locally (R5, K4, V7 and the reranker).

## Rule
Do not install torch, sentence-transformers, vLLM, transformers or any model weights on the local machine. Do not download models locally. Local code must import and start without any of them (lazy loading, already required). Local tests stay offline with fakes. Anything that needs a GPU or a model runs in a Kaggle notebook and is reached over HTTP or via downloaded artifacts.

## Split
Kaggle notebook (GPU, Internet on):
- LLM: Llama 8B Instruct via vLLM, OpenAI-compatible, port 8000 (see AGENT_KAGGLE_ADDENDUM.md).
- Embedding service: a small FastAPI app in the same notebook, port 8001, serving `BAAI/bge-large-en-v1.5` (fall back to `bge-small-en-v1.5` if memory is tight; log which). Put the LLM on GPU 0 and the embedder on GPU 1 if two GPUs are available; otherwise the embedder may run on CPU, because the corpus and query volume are small.
- Optional: BGE reranker service on port 8002 (E4 only; default pipeline keeps the reranker off).
- Index build job and batch evaluation (Option 2 of K3) when the tunnel is unreliable.
Local machine:
- FastAPI app, Streamlit UI, SQLite, corpus pipeline, guards, machine-verification checks that run on CPU, FAISS search over vectors, all unit tests.

## Tasks
G1 Embedding service and client (45 min)
- `kaggle/embed_server.py`: `POST /embed` with `{"texts":[...], "kind":"query|passage"}` returns vectors, model id, dimension, and a `model_hash`. Requires an API key header. L2-normalise vectors server-side. Applies the model's recommended query instruction only for `kind="query"`.
- App side: `EMBEDDER_PROVIDER=remote_http`, `EMBEDDER_BASE_URL`, `EMBEDDER_API_KEY`, `EMBEDDER_TIMEOUT_S`. Batch requests, retry twice on timeout, then raise a clear error. No fallback to the hashed embedder in real mode.
- Tests with a fake HTTP server: normalisation, batching, timeout error, 401 error, dimension mismatch error.

G2 Index build and integrity (30 min)
- Index build runs locally against the remote embedder (corpus is small), or inside the notebook if the tunnel fails. Either way it records `embedder_model_id`, `embedder_model_hash`, dimension, corpus hash, provision count and build time in `index_meta.json`.
- On load, the app checks `index_meta.json` against the current corpus hash and the embedder's live `model_hash`. Any mismatch refuses to load.
- Tests: corpus changed after build -> refuse; different embedder hash -> refuse.

G3 Query embedding cache for evaluation (20 min)
- Cache query embeddings keyed by `(model_hash, text)` in a local file so repeated evaluation runs do not call Kaggle again and results are reproducible. Cache entries from a different model hash are ignored.

G4 Notebook files (45 min)
- `kaggle/serve_all.ipynb`: installs vLLM and sentence-transformers, reads `HF_TOKEN`, `API_KEY`, tunnel token from Kaggle Secrets (never printed), starts the LLM, embedding service and optional reranker, opens one tunnel per port, prints ONLY the public URLs, and prints a heartbeat every 60 seconds with log tails.
- `kaggle/run_eval.ipynb`: Option 2 of K3 for batch evaluation inside Kaggle; writes raw code-generated outputs to `/kaggle/working/results/` with file hashes.
- Write and syntax-check the notebooks locally; mark them IMPLEMENTED_NOT_TESTED until Mri runs them on Kaggle. Never claim they work.

G5 Health and failure behaviour (20 min)
- `python -m ai_lawyer.tools.check_remote` pings LLM, embedder and reranker endpoints, prints model ids, latency and pass/fail, never prints keys or full URLs with tokens.
- The UI banner shows LLM id, embedder id, corpus trust level and verified count. In real mode, any unreachable remote service shows a clear "Service unavailable" state. Never silently degrade.

G6 Results provenance (15 min)
- Every results folder records: LLM id and quantization, embedder id/hash, GPU type, vLLM version, tunnel date, corpus hash, trust level, labeled row counts.

## Cut order
1. Drop the reranker service and E4.
2. Drop G3.
3. Run embedding on Kaggle CPU rather than the second GPU.
4. Smaller embedder (bge-small). Log it.
Never cut: G1, G2, G5.

## Needs Mri (report these; do not work around)
- Kaggle: Internet on, phone verification, GPU accelerator selected, Secrets set (`HF_TOKEN`, `API_KEY`, tunnel token).
- Run `serve_all.ipynb` and paste the printed public URLs into `.env` (never into code).
- Keep the notebook running during evaluation and demo; a Kaggle session is temporary and the URLs change each session.

## Report format
Per task: id, status label (IMPLEMENTED_AND_TESTED / IMPLEMENTED_NOT_TESTED / BLOCKED), command, real output, blockers. List everything that has not run on real Kaggle hardware.
