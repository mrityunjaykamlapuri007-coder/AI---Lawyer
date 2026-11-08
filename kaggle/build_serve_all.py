"""Generate kaggle/serve_all.ipynb (LLM + embedder + tunnels) from source.

The embedding server source is inlined from kaggle/embed_server.py so the
notebook can never drift from the tested file.

    python kaggle/build_serve_all.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EMBED_SOURCE = (HERE / "embed_server.py").read_text(encoding="utf-8")

INTRO = """# Serve the LLM and the embedder for the refund assistant (Kaggle GPU)

Runs two services and exposes each through its own cloudflared quick tunnel:

| service | port | what |
|---|---|---|
| vLLM (OpenAI-compatible) | 8000 | Llama 3.1 8B Instruct, JSON-schema output |
| embedder (`embed_server.py`) | 8001 | BGE sentence embeddings, L2-normalised |

**Before running**

1. Settings: **Accelerator = GPU T4 x2** (preferred) or T4 x1; **Internet = On**
   (needs a phone-verified Kaggle account).
2. Accept Meta's Llama 3.1 license (Hugging Face route: new read-only token as
   Kaggle Secret `HF_TOKEN`; or attach the model from Kaggle Models and set
   `MODEL_SOURCE = "kaggle_model"`).
3. Kaggle Secrets: `API_KEY` (random string; the app uses the same value for the
   LLM and the embedder) and `HF_TOKEN` (Hugging Face route only).
4. Never paste a token into a cell.  Secrets are read, never printed.

Run all cells top to bottom.  Copy the printed `.env` lines to the app machine.
Leave the last cell running during evaluation and the demo; the URLs die with
the session.  Status until run on Kaggle: IMPLEMENTED_NOT_TESTED.
"""

CELLS = [
    """# Cell 1 - settings
MODEL_SOURCE = "huggingface"          # "huggingface" or "kaggle_model"
HF_MODEL_ID = "meta-llama/Meta-Llama-3.1-8B-Instruct"
AWQ_MODEL_ID = "casperhansen/llama-3.1-8b-instruct-awq"
KAGGLE_MODEL_PATH = ""                # set when MODEL_SOURCE == "kaggle_model"
SERVED_NAME = "refund-llm"
MAX_MODEL_LEN = 8192
LLM_PORT = 8000

EMBED_MODEL_ID = "BAAI/bge-large-en-v1.5"
EMBED_FALLBACK_ID = "BAAI/bge-small-en-v1.5"   # use if the large model will not load; log it
EMBED_DEVICE = "cpu"                  # the LLM takes the GPUs; the corpus is small
EMBED_PORT = 8001
print("LLM:", MODEL_SOURCE, "| embedder:", EMBED_MODEL_ID, "on", EMBED_DEVICE)
""",
    """# Cell 2 - install.  If an install fails, report the exact error.
import subprocess, sys

def run(cmd, check=True):
    print("$", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout[-3000:])
    if proc.stderr:
        print(proc.stderr[-3000:])
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed with {proc.returncode}: {' '.join(cmd)}")
    return proc

run([sys.executable, "-m", "pip", "install", "-q", "vllm", "sentence-transformers", "fastapi", "uvicorn"])
import vllm, sentence_transformers
VLLM_VERSION = vllm.__version__
print("vllm", VLLM_VERSION, "| sentence-transformers", sentence_transformers.__version__)
""",
    """# Cell 3 - secrets.  Nothing secret is printed.
from kaggle_secrets import UserSecretsClient

_secrets = UserSecretsClient()

def optional_secret(name):
    try:
        return _secrets.get_secret(name)
    except Exception:
        return None

API_KEY = optional_secret("API_KEY")
if not API_KEY:
    raise SystemExit("Missing Kaggle Secret API_KEY. Add it in Add-ons > Secrets.")
HF_TOKEN = optional_secret("HF_TOKEN") if MODEL_SOURCE == "huggingface" else None
print("API_KEY loaded:", bool(API_KEY), "| HF_TOKEN loaded:", bool(HF_TOKEN))
""",
    """# Cell 4 - GPUs and LLM plan
smi = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True)
print(smi.stdout.strip() or smi.stderr.strip())
GPU_COUNT = max(1, smi.stdout.count("GPU "))
GPU_TYPE = (smi.stdout.splitlines() or ["unknown"])[0]

if MODEL_SOURCE == "kaggle_model":
    if not KAGGLE_MODEL_PATH:
        raise SystemExit("Set KAGGLE_MODEL_PATH to the attached Kaggle Models path.")
    MODEL = KAGGLE_MODEL_PATH
elif GPU_COUNT >= 2:
    MODEL = HF_MODEL_ID
else:
    MODEL = AWQ_MODEL_ID

if GPU_COUNT >= 2:
    TENSOR_PARALLEL, QUANTIZATION = 2, None
elif MODEL == AWQ_MODEL_ID:
    TENSOR_PARALLEL, QUANTIZATION = 1, "awq"
else:
    raise SystemExit("One 16 GB GPU cannot hold fp16 8B weights. Use T4 x2 or a 4-bit AWQ build.")
print("model:", MODEL, "| tensor_parallel:", TENSOR_PARALLEL, "| quantization:", QUANTIZATION)
""",
    """# Cell 5 - start vLLM in the background
import os, time

LLM_LOG = "/kaggle/working/vllm.log"
cmd = [
    "python", "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL, "--served-model-name", SERVED_NAME, "--dtype", "half",
    "--max-model-len", str(MAX_MODEL_LEN), "--port", str(LLM_PORT),
    "--api-key", API_KEY, "--trust-remote-code",
]
if QUANTIZATION:
    cmd += ["--quantization", QUANTIZATION]
if TENSOR_PARALLEL > 1:
    cmd += ["--tensor-parallel-size", str(TENSOR_PARALLEL)]
llm_env = dict(os.environ)
if HF_TOKEN:
    llm_env["HF_TOKEN"] = HF_TOKEN          # environment only, never on the command line
    llm_env["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN
llm_server = subprocess.Popen(cmd, stdout=open(LLM_LOG, "w"), stderr=subprocess.STDOUT, env=llm_env)
print("vLLM pid:", llm_server.pid, "log:", LLM_LOG)
""",
    "# Cell 6 - write the embedding server (inlined from kaggle/embed_server.py) and start it\n"
    "EMBED_SERVER_SOURCE = " + repr(EMBED_SOURCE) + "\n"
    + """
open("/kaggle/working/embed_server.py", "w").write(EMBED_SERVER_SOURCE)
EMBED_LOG = "/kaggle/working/embed.log"

def start_embedder(model_id):
    env = dict(os.environ, EMBED_API_KEY=API_KEY, EMBED_MODEL_ID=model_id, EMBED_DEVICE=EMBED_DEVICE)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "embed_server:app", "--host", "127.0.0.1", "--port", str(EMBED_PORT)],
        cwd="/kaggle/working", stdout=open(EMBED_LOG, "w"), stderr=subprocess.STDOUT, env=env,
    )

EMBED_IN_USE = EMBED_MODEL_ID
embed_server = start_embedder(EMBED_IN_USE)
print("embedder pid:", embed_server.pid, "model:", EMBED_IN_USE, "log:", EMBED_LOG)
""",
    """# Cell 7 - wait for both services (cold start can take several minutes)
import requests

AUTH = {"Authorization": f"Bearer {API_KEY}"}

def wait_for(name, url, proc, log, minutes=10):
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        if proc.poll() is not None:
            print(open(log).read()[-6000:])
            return False
        try:
            if requests.get(url, headers=AUTH, timeout=5).status_code == 200:
                print(name, "ready")
                return True
        except Exception:
            pass
        time.sleep(10)
    print(open(log).read()[-6000:])
    return False

if not wait_for("vLLM", f"http://127.0.0.1:{LLM_PORT}/v1/models", llm_server, LLM_LOG):
    raise SystemExit("vLLM did not start. 401/403 in the log: license not accepted or HF_TOKEN wrong.")
if not wait_for("embedder", f"http://127.0.0.1:{EMBED_PORT}/info", embed_server, EMBED_LOG, minutes=6):
    print("Large embedder failed; trying the fallback", EMBED_FALLBACK_ID, "(this is logged).")
    EMBED_IN_USE = EMBED_FALLBACK_ID
    embed_server = start_embedder(EMBED_IN_USE)
    if not wait_for("embedder", f"http://127.0.0.1:{EMBED_PORT}/info", embed_server, EMBED_LOG, minutes=6):
        raise SystemExit("embedder did not start with either model; see the log above")
""",
    """# Cell 8 - smoke tests: JSON-schema decoding and a normalised embedding
import json, math

schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
r = requests.post(
    f"http://127.0.0.1:{LLM_PORT}/v1/chat/completions", headers=AUTH, timeout=120,
    json={"model": SERVED_NAME, "temperature": 0, "max_tokens": 50,
          "messages": [{"role": "user", "content": "Return JSON with ok=true."}],
          "response_format": {"type": "json_schema", "json_schema": {"name": "Ok", "schema": schema}}},
)
print("LLM JSON schema:", "PASS" if r.status_code == 200 and "ok" in json.loads(r.json()["choices"][0]["message"]["content"]) else f"FAIL {r.status_code} {r.text[:500]}")

info = requests.get(f"http://127.0.0.1:{EMBED_PORT}/info", headers=AUTH, timeout=30).json()
e = requests.post(f"http://127.0.0.1:{EMBED_PORT}/embed", headers=AUTH, timeout=120,
                  json={"texts": ["refund not received"], "kind": "query"}).json()
norm = math.sqrt(sum(x * x for x in e["vectors"][0]))
print("embedder:", info["model_id"], "dim", info["dimension"], "hash", info["model_hash"],
      "| norm", round(norm, 4), "PASS" if abs(norm - 1) < 1e-3 else "FAIL")
""",
    """# Cell 9 - one cloudflared quick tunnel per service.  Prints only the public URLs.
import re

subprocess.run(
    "wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
    "-O /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared",
    shell=True, check=True,
)

def open_tunnel(port, log):
    proc = subprocess.Popen(
        ["/usr/local/bin/cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        found = re.search(r"https://[a-zA-Z0-9-]+\\.trycloudflare\\.com", open(log).read())
        if found:
            return proc, found.group(0)
        time.sleep(3)
    raise SystemExit(f"no tunnel URL for port {port}; see {log}")

llm_tunnel, LLM_URL = open_tunnel(LLM_PORT, "/kaggle/working/tunnel_llm.log")
embed_tunnel, EMBED_URL = open_tunnel(EMBED_PORT, "/kaggle/working/tunnel_embed.log")
print("LLM URL     :", LLM_URL)
print("EMBEDDER URL:", EMBED_URL)
print()
print("# .env on the app machine (never commit):")
print("CORPUS_MODE=real")
print("LLM_PROVIDER=openai_compatible")
print(f"LLM_BASE_URL={LLM_URL}/v1")
print(f"LLM_MODEL={SERVED_NAME}")
print("LLM_API_KEY=<your Kaggle API_KEY secret>")
print("LLM_JSON_SCHEMA_MODE=true")
print("EMBEDDING_BACKEND=remote_http")
print(f"EMBEDDER_BASE_URL={EMBED_URL}")
print("EMBEDDER_API_KEY=<your Kaggle API_KEY secret>")
""",
    """# Cell 10 - provenance for the results folders (no secrets)
PROVENANCE = {
    "llm_model": MODEL, "served_name": SERVED_NAME, "quantization": QUANTIZATION or "fp16",
    "tensor_parallel": TENSOR_PARALLEL, "vllm_version": VLLM_VERSION, "gpu_type": GPU_TYPE,
    "gpu_count": GPU_COUNT, "embedder_model": info["model_id"], "embedder_hash": info["model_hash"],
    "embedder_dimension": info["dimension"], "embedder_device": EMBED_DEVICE,
    "embedder_fallback_used": EMBED_IN_USE != EMBED_MODEL_ID,
    "session_started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
json.dump(PROVENANCE, open("/kaggle/working/provenance.json", "w"), indent=2)
print(json.dumps(PROVENANCE, indent=2))
print("Pass these to the eval runner: --vllm-version", VLLM_VERSION,
      "--quantization", PROVENANCE["quantization"], '--gpu-type "' + GPU_TYPE + '"')
""",
    """# Cell 11 - heartbeat.  Leave running during evaluation and the demo.
beat = 0
try:
    while True:
        beat += 1
        procs = {"vllm": llm_server, "embedder": embed_server, "llm_tunnel": llm_tunnel, "embed_tunnel": embed_tunnel}
        dead = [name for name, p in procs.items() if p.poll() is not None]
        print(f"[{beat}] alive={not dead} dead={dead}")
        for name, log in (("vllm", LLM_LOG), ("embed", EMBED_LOG)):
            for line in open(log).read()[-600:].strip().splitlines()[-2:]:
                print(f"  {name}: {line}")
        if dead:
            print("A process died: restart from the matching cell. The app will show 'service unavailable'.")
            break
        time.sleep(60)
except KeyboardInterrupt:
    print("heartbeat stopped")
""",
]


def build() -> dict:
    def cell(kind: str, source: str) -> dict:
        base = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
        if kind == "code":
            base.update(execution_count=None, outputs=[])
        return base

    return {
        "cells": [cell("markdown", INTRO)] + [cell("code", c) for c in CELLS],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


if __name__ == "__main__":
    out = HERE / "serve_all.ipynb"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(CELLS)} code cells)")
