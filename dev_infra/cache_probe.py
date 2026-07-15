"""Cache probe — proves whether an inference engine actually reuses the shared
prompt prefix (the "canonical executor prompt" of docs/PARALLEL_DEVELOPMENT.md).

It sends three requests and compares how many prompt tokens the engine REALLY
processed (not how many you sent):

  1. COLD    shared prefix + task A          -> baseline (everything processed)
  2. WARM    identical prefix + task B       -> should process ~task tokens only
  3. BROKEN  prefix with 1 byte changed + B  -> back to baseline (negative control)

PASS = warm processed-tokens << cold, and broken ~= cold.

The shared prefix is your real workload: AI_CONTEXT.md + plans/active_plan.yaml.

Usage:
  python dev_infra/cache_probe.py --backend ollama    --url http://localhost:11434 --model llama3.1
  python dev_infra/cache_probe.py --backend llamacpp  --url http://localhost:8080
  python dev_infra/cache_probe.py --backend openai    --url http://localhost:8000 --model my-model   # vLLM etc.
  python dev_infra/cache_probe.py --backend anthropic --model claude-haiku-4-5     # needs ANTHROPIC_API_KEY

No dependencies beyond the standard library.
"""
import argparse
import json
import os
import time
import urllib.request

TASK_A = "Implement feature CreateThingPlugin from the plan above. Reply with only the file path you would create."
TASK_B = "Implement feature DeleteThingPlugin from the plan above. Reply with only the file path you would create."


def read_shared_prefix() -> str:
    parts = []
    for path in ("AI_CONTEXT.md", "plans/active_plan.yaml"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                parts.append(f"===== {path} =====\n{f.read()}")
        except FileNotFoundError:
            parts.append(f"===== {path} ===== (missing)")
    parts.append("===== RULES =====\nOne file = one feature. Follow the plan exactly.")
    return "\n\n".join(parts)


def post_json(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Backends ────────────────────────────────────────────────────────────────
# Each returns {"processed": int, "cached": int|None, "wall_s": float}
# "processed" = prompt tokens the engine actually evaluated this request.

def probe_ollama(url, model, prefix, task):
    t0 = time.monotonic()
    r = post_json(f"{url}/api/chat", {
        "model": model, "stream": False,
        "messages": [{"role": "user", "content": prefix + "\n\n" + task}],
        "options": {"num_predict": 32},
    }, {})
    return {"processed": r.get("prompt_eval_count", -1), "cached": None,
            "wall_s": time.monotonic() - t0}


def probe_llamacpp(url, model, prefix, task):
    t0 = time.monotonic()
    r = post_json(f"{url}/completion", {
        "prompt": prefix + "\n\n" + task,
        "n_predict": 32, "cache_prompt": True,
    }, {})
    timings = r.get("timings", {})
    return {"processed": timings.get("prompt_n", -1), "cached": None,
            "wall_s": time.monotonic() - t0}


def probe_openai(url, model, prefix, task):
    """OpenAI-compatible servers (vLLM with prefix caching, OpenAI itself)."""
    t0 = time.monotonic()
    headers = {}
    if os.getenv("OPENAI_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['OPENAI_API_KEY']}"
    r = post_json(f"{url}/v1/chat/completions", {
        "model": model, "max_tokens": 32,
        "messages": [{"role": "user", "content": prefix + "\n\n" + task}],
    }, headers)
    usage = r.get("usage", {})
    total = usage.get("prompt_tokens", -1)
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    return {"processed": total - cached, "cached": cached,
            "wall_s": time.monotonic() - t0}


def _anthropic_headers():
    h = {"anthropic-version": "2023-06-01"}
    if os.getenv("ANTHROPIC_API_KEY"):
        h["x-api-key"] = os.environ["ANTHROPIC_API_KEY"]
    elif os.getenv("ANTHROPIC_AUTH_TOKEN"):  # OAuth token (e.g. from ant auth / Claude Code)
        h["Authorization"] = f"Bearer {os.environ['ANTHROPIC_AUTH_TOKEN']}"
        h["anthropic-beta"] = "oauth-2025-04-20"
    else:
        raise SystemExit("Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN")
    return h


def probe_anthropic(url, model, prefix, task):
    t0 = time.monotonic()
    r = post_json(f"{url}/v1/messages", {
        "model": model, "max_tokens": 32,
        "system": [{"type": "text", "text": prefix,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": task}],
    }, _anthropic_headers())
    u = r.get("usage", {})
    processed = u.get("input_tokens", -1) + u.get("cache_creation_input_tokens", 0)
    return {"processed": processed, "cached": u.get("cache_read_input_tokens", 0),
            "wall_s": time.monotonic() - t0}


BACKENDS = {
    "ollama": (probe_ollama, "http://localhost:11434"),
    "llamacpp": (probe_llamacpp, "http://localhost:8080"),
    "openai": (probe_openai, "http://localhost:8000"),
    "anthropic": (probe_anthropic, "https://api.anthropic.com"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=BACKENDS, required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--url", default="")
    args = ap.parse_args()

    probe, default_url = BACKENDS[args.backend]
    url = (args.url or default_url).rstrip("/")
    prefix = read_shared_prefix()
    # Negative control: one byte changed at position 0 breaks the whole prefix.
    broken_prefix = "!" + prefix[1:]

    runs = [
        ("COLD   (prefix + task A)", prefix, TASK_A),
        ("WARM   (same prefix + task B)", prefix, TASK_B),
        ("BROKEN (1 byte changed + task B)", broken_prefix, TASK_B),
    ]
    results = []
    print(f"backend={args.backend}  model={args.model or '(default)'}  url={url}")
    print(f"shared prefix: {len(prefix)} chars (~{len(prefix) // 4} tokens)\n")
    for name, pfx, task in runs:
        res = probe(url, args.model, pfx, task)
        results.append(res)
        cached = f"  cached={res['cached']}" if res["cached"] is not None else ""
        print(f"{name:38} processed={res['processed']:>7}{cached}  wall={res['wall_s']:.2f}s")

    cold, warm, broken = (r["processed"] for r in results)
    print()
    if 0 <= warm < cold * 0.5 and broken > cold * 0.5:
        print(f"PASS — WARM processed only {warm}/{cold} tokens (cache hit), "
              f"and BROKEN reprocessed {broken} (prefix rule confirmed).")
    elif 0 <= warm < cold * 0.5:
        print(f"PARTIAL — WARM hit the cache ({warm}/{cold}), but BROKEN also "
              f"avoided reprocessing ({broken}) — check the negative control.")
    else:
        print(f"FAIL — WARM reprocessed {warm}/{cold} tokens. No prefix reuse: "
              f"check that prefix caching is enabled on the server, the prefix "
              f"is byte-identical, and (hosted) the prefix meets the minimum "
              f"cacheable size for the model.")


if __name__ == "__main__":
    main()
