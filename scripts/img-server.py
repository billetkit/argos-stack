#!/usr/bin/env python3
"""img-server.py — Keep SDXL Turbo loaded in memory; serve image generations over HTTP.

Loads the model once at startup (~70s), then each /generate request is ~6s.
Listens on 127.0.0.1:8081 (loopback only — not exposed to LAN).

POST /generate
  body: {"prompt": "...", "steps": 4, "seed": null, "height": 512, "width": 512}
  response: {"ok": true, "path": "/tmp/img-{ts}.png", "render_ms": 6500}
           or {"ok": false, "error": "..."}
"""
import os, time, pathlib, threading, random
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_file, render_template_string

# Lock to serialize generations (model is single-instance)
GEN_LOCK = threading.Lock()
PIPES = {}  # model_id → pipe (lazy-loaded)
ACTIVE_MODEL = None

MODEL_CONFIGS = {
    "turbo": {
        "hf_id": "stabilityai/sdxl-turbo",
        "label": "SDXL Turbo · fast preview · 4 steps",
        "default_steps": 4,
        "default_guidance": 0.0,
        "max_steps": 8,
        "needs_auth": False,
    },
    "playground": {
        "hf_id": "playgroundai/playground-v2.5-1024px-aesthetic",
        "label": "Playground v2.5 · aesthetic · 30 steps",
        "default_steps": 30,
        "default_guidance": 3.0,
        "max_steps": 50,
        "needs_auth": False,
    },
    "sdxl": {
        "hf_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "label": "SDXL Base 1.0 · standard · 30 steps",
        "default_steps": 30,
        "default_guidance": 7.5,
        "max_steps": 50,
        "needs_auth": False,
    },
    "flux-schnell": {
        "hf_id": "black-forest-labs/FLUX.1-schnell",
        "label": "FLUX.1 schnell · best open-source · 4 steps · needs HF token",
        "default_steps": 4,
        "default_guidance": 0.0,
        "max_steps": 8,
        "needs_auth": True,
    },
}


def load_model(model_key):
    """Lazy-load a model and unload the previous one to save RAM."""
    global PIPES, ACTIVE_MODEL
    if model_key in PIPES:
        ACTIVE_MODEL = model_key
        return PIPES[model_key]

    import torch
    cfg = MODEL_CONFIGS[model_key]
    print(f"[img-server] loading {cfg['hf_id']}...", flush=True)
    t0 = time.time()

    # Pick the right pipeline class
    if model_key == "flux-schnell":
        from diffusers import FluxPipeline
        pipe = FluxPipeline.from_pretrained(cfg["hf_id"], torch_dtype=torch.bfloat16)
    else:
        from diffusers import AutoPipelineForText2Image
        pipe = AutoPipelineForText2Image.from_pretrained(
            cfg["hf_id"],
            torch_dtype=torch.float16,
            variant="fp16" if model_key != "playground" else None,
            use_safetensors=True,
        )

    pipe = pipe.to("mps")
    pipe.set_progress_bar_config(disable=True)

    # Unload previous to free RAM
    if PIPES and len(PIPES) > 1:
        for k in list(PIPES.keys()):
            if k != model_key:
                del PIPES[k]
        import gc; gc.collect()
        try:
            torch.mps.empty_cache()
        except Exception:
            pass

    PIPES[model_key] = pipe
    ACTIVE_MODEL = model_key
    print(f"[img-server] {model_key} ready in {time.time()-t0:.1f}s", flush=True)
    return pipe


def load_default_model():
    """Load whatever's already on disk to get warmed up."""
    # Prefer turbo for fast warmup; user can switch via UI/API
    load_model("turbo")


def main():
    load_default_model()

    app = Flask(__name__)

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "active_model": ACTIVE_MODEL, "loaded": list(PIPES.keys())})

    @app.route("/models")
    def models():
        # Report which models are on disk (downloaded) vs need download
        return jsonify({k: {"label": v["label"], "needs_auth": v["needs_auth"]} for k, v in MODEL_CONFIGS.items()})

    @app.route("/generate", methods=["POST"])
    def generate():
        import torch
        body = request.get_json(force=True)
        prompt = body.get("prompt", "").strip()
        if not prompt:
            return jsonify({"ok": False, "error": "missing prompt"}), 400

        model_key = body.get("model", ACTIVE_MODEL or "turbo")
        if model_key not in MODEL_CONFIGS:
            return jsonify({"ok": False, "error": f"unknown model: {model_key}"}), 400

        try:
            pipe = load_model(model_key)
        except Exception as e:
            return jsonify({"ok": False, "error": f"model load failed: {type(e).__name__}: {e}"}), 500

        cfg = MODEL_CONFIGS[model_key]
        steps = int(body.get("steps", cfg["default_steps"]))
        guidance = float(body.get("guidance", cfg["default_guidance"]))
        seed = body.get("seed")
        height = int(body.get("height", 1024 if model_key != "turbo" else 512))
        width = int(body.get("width", 1024 if model_key != "turbo" else 512))
        negative = body.get("negative_prompt", "")

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        out_path = f"/tmp/img-{ts}.png"

        # Always materialize a seed so we can return it. If user didn't supply one, generate a random.
        if seed is None or seed == "":
            seed = random.randint(0, 2**32 - 1)
        seed = int(seed)

        with GEN_LOCK:
            t0 = time.time()
            gen = torch.Generator(device="mps").manual_seed(seed)
            try:
                kwargs = {
                    "prompt": prompt,
                    "num_inference_steps": steps,
                    "guidance_scale": guidance,
                    "height": height,
                    "width": width,
                    "generator": gen,
                }
                if negative and model_key != "flux-schnell":  # FLUX schnell doesn't accept negative
                    kwargs["negative_prompt"] = negative
                image = pipe(**kwargs).images[0]
                pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(out_path)
                render_ms = int((time.time() - t0) * 1000)
                return jsonify({
                    "ok": True,
                    "path": out_path,
                    "render_ms": render_ms,
                    "bytes": pathlib.Path(out_path).stat().st_size,
                    "model": model_key,
                    "seed": seed,
                })
            except Exception as e:
                return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500

    @app.route("/")
    def ui():
        return render_template_string(UI_HTML)

    @app.route("/image/<filename>")
    def serve_image(filename):
        # Only serve image files we generated
        if not filename.startswith("img-") or not filename.endswith(".png"):
            return ("not found", 404)
        path = pathlib.Path("/tmp") / filename
        if not path.exists():
            return ("not found", 404)
        return send_file(str(path), mimetype="image/png")

    port = int(os.environ.get("ARGOS_IMG_PORT", "8081"))
    # Bind LAN so operator can hit from laptop browser (the bot still uses 127.0.0.1:8081 too — same listener)
    # threaded=True so health/UI/status stay responsive while a generation runs (gen still serialized via GEN_LOCK)
    print(f"[img-server] listening on 0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True)


UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>argos · img studio</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #06080d; --bg-alt: #0c1018; --bg-card: #0f1422;
    --border: #1a2138; --border-glow: #2d3a5c;
    --text: #d8dee9; --text-dim: #5b6577; --text-dimmer: #3a4258;
    --green: #00ff9f; --cyan: #00d4ff; --amber: #ffaa00;
    --red: #ff3366; --pink: #ff79c6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: var(--bg); color: var(--text); font-family: 'JetBrains Mono', monospace; min-height: 100vh; }
  body {
    background-image: linear-gradient(rgba(0,212,255,0.025) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(0,212,255,0.025) 1px, transparent 1px);
    background-size: 40px 40px;
  }
  header { padding: 18px 28px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
  .brand { font-size: 18px; font-weight: 700; letter-spacing: 0.2em; color: var(--green); text-shadow: 0 0 12px rgba(0,255,159,0.5); }
  .sub { color: var(--text-dim); font-size: 11px; letter-spacing: 0.15em; }
  .privacy-tag { color: var(--amber); font-size: 10px; letter-spacing: 0.2em; padding: 4px 10px; border: 1px solid var(--amber); border-radius: 2px; }
  main { display: grid; grid-template-columns: 380px 1fr; gap: 24px; padding: 24px 28px; max-width: 1600px; margin: 0 auto; }
  .controls { display: flex; flex-direction: column; gap: 18px; }
  .control-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px; padding: 16px 18px; }
  .label { font-size: 10px; letter-spacing: 0.25em; color: var(--text-dim); margin-bottom: 8px; display: block; }
  textarea, input[type="number"], input[type="text"], select {
    width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 2px; color: var(--text);
    font-family: 'JetBrains Mono', monospace; font-size: 13px; padding: 10px 12px; resize: vertical;
  }
  textarea:focus, input:focus { outline: none; border-color: var(--cyan); box-shadow: 0 0 8px rgba(0,212,255,0.2); }
  textarea { min-height: 100px; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .btn-primary {
    width: 100%; background: transparent; border: 1px solid var(--green); color: var(--green);
    font-family: 'JetBrains Mono', monospace; font-size: 12px; letter-spacing: 0.2em; padding: 14px;
    border-radius: 2px; cursor: pointer; transition: all 0.15s;
  }
  .btn-primary:hover { background: rgba(0,255,159,0.08); box-shadow: 0 0 16px rgba(0,255,159,0.3); }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-secondary { background: transparent; border: 1px solid var(--border); color: var(--text-dim); font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.15em; padding: 8px 14px; border-radius: 2px; cursor: pointer; transition: all 0.15s; }
  .btn-secondary:hover { border-color: var(--cyan); color: var(--cyan); }
  .preview { background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px; min-height: 600px; display: flex; flex-direction: column; padding: 18px 20px; }
  .preview-title { font-size: 10px; letter-spacing: 0.25em; color: var(--text-dim); margin-bottom: 14px; }
  .preview-img-wrap { flex: 1; display: flex; align-items: center; justify-content: center; min-height: 500px; }
  .preview-img-wrap img { max-width: 100%; max-height: 700px; border-radius: 2px; border: 1px solid var(--border-glow); }
  .preview-empty { color: var(--text-dimmer); font-size: 11px; letter-spacing: 0.1em; }
  .preview-meta { margin-top: 12px; font-size: 11px; color: var(--text-dim); font-family: 'JetBrains Mono', monospace; min-height: 18px; }
  .preview-actions { display: flex; gap: 8px; margin-top: 12px; }
  .history { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-top: 18px; }
  .history img { width: 100%; aspect-ratio: 1; object-fit: cover; border: 1px solid var(--border); border-radius: 2px; cursor: pointer; transition: border-color 0.15s; }
  .history img:hover { border-color: var(--cyan); }
  .spinner { display: none; color: var(--cyan); font-size: 11px; letter-spacing: 0.15em; }
  .spinner.active { display: inline; animation: blink 1s steps(2) infinite; }
  @keyframes blink { 50% { opacity: 0.3; } }
</style>
</head>
<body>
<header>
  <div>
    <span class="brand">ARGOS</span>
    <span class="sub" style="margin-left: 12px;">img studio · stabilityai/sdxl-turbo · mps</span>
  </div>
  <div class="privacy-tag">LAN-ONLY · NOT VISIBLE TO BOT OR DASHBOARD</div>
</header>

<main>
  <div class="controls">
    <div class="control-card">
      <label class="label">MODEL</label>
      <select id="model" onchange="onModelChange()">
        <option value="turbo">SDXL Turbo · 4 steps · ~6s · fast preview</option>
        <option value="playground" selected>Playground v2.5 · 30 steps · ~40s · best aesthetic</option>
        <option value="sdxl">SDXL Base 1.0 · 30 steps · ~30s · vanilla</option>
        <option value="flux-schnell">FLUX schnell · 4 steps · ~30s · needs HF token</option>
      </select>
    </div>

    <div class="control-card">
      <label class="label">PROMPT</label>
      <textarea id="prompt" placeholder="describe what you want to see"></textarea>
    </div>

    <div class="control-card">
      <label class="label">NEGATIVE PROMPT (optional)</label>
      <textarea id="negative" placeholder="what to avoid (e.g. blurry, extra limbs, lowres)" style="min-height: 60px;"></textarea>
    </div>

    <div class="control-card">
      <div class="row">
        <div>
          <label class="label">STEPS</label>
          <input type="number" id="steps" value="30" min="1" max="50">
        </div>
        <div>
          <label class="label">GUIDANCE</label>
          <input type="number" id="guidance" value="3" min="0" max="15" step="0.5">
        </div>
      </div>
      <div class="row" style="margin-top: 12px;">
        <div>
          <label class="label">WIDTH</label>
          <select id="width">
            <option value="512">512</option>
            <option value="768">768</option>
            <option value="1024" selected>1024</option>
            <option value="1152">1152</option>
            <option value="1344">1344</option>
          </select>
        </div>
        <div>
          <label class="label">HEIGHT</label>
          <select id="height">
            <option value="512">512</option>
            <option value="768">768</option>
            <option value="1024" selected>1024</option>
            <option value="1152">1152</option>
            <option value="1344">1344</option>
          </select>
        </div>
      </div>
      <div style="margin-top: 12px;">
        <label class="label">SEED (blank = random)</label>
        <input type="text" id="seed" placeholder="optional">
      </div>
    </div>

    <button class="btn-primary" id="generate-btn" onclick="generate()">▸ GENERATE <span class="spinner" id="spinner">· rendering…</span></button>
  </div>

  <div class="preview">
    <div class="preview-title">PREVIEW</div>
    <div class="preview-img-wrap" id="preview-img-wrap">
      <div class="preview-empty">no image yet · write a prompt and hit generate</div>
    </div>
    <div class="preview-meta" id="preview-meta"></div>
    <div class="preview-actions" id="preview-actions"></div>
    <div class="history" id="history"></div>
  </div>
</main>

<script>
const $ = id => document.getElementById(id);
const history = []; // {path, prompt, render_ms, seed}

async function generate() {
  const btn = $('generate-btn');
  const spinner = $('spinner');
  btn.disabled = true; spinner.classList.add('active');

  const body = {
    model: $('model').value,
    prompt: $('prompt').value.trim(),
    negative_prompt: $('negative').value.trim(),
    steps: parseInt($('steps').value),
    guidance: parseFloat($('guidance').value),
    height: parseInt($('height').value),
    width: parseInt($('width').value),
  };
  const seed = $('seed').value.trim();
  if (seed) body.seed = parseInt(seed);

  if (!body.prompt) {
    btn.disabled = false; spinner.classList.remove('active');
    return;
  }

  try {
    const t0 = performance.now();
    const r = await fetch('/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await r.json();
    if (!data.ok) {
      $('preview-meta').textContent = 'error: ' + (data.error || 'unknown');
      btn.disabled = false; spinner.classList.remove('active');
      return;
    }
    const filename = data.path.split('/').pop();
    const url = '/image/' + filename + '?t=' + Date.now();

    $('preview-img-wrap').innerHTML = '<img src="' + url + '" alt="">';
    $('preview-meta').innerHTML = `${(data.render_ms/1000).toFixed(1)}s · ${(data.bytes/1024).toFixed(0)}kb · seed <code style="color:var(--cyan); cursor:pointer;" onclick="lockSeed(${data.seed})">${data.seed}</code> · ${filename}`;
    $('preview-actions').innerHTML = `
      <button class="btn-secondary" onclick="window.open('${url}')">▸ OPEN FULL SIZE</button>
      <button class="btn-secondary" onclick="lockSeed(${data.seed})">🔒 LOCK SEED</button>
      <button class="btn-secondary" onclick="reroll()">↻ REROLL (new seed)</button>
      <button class="btn-secondary" onclick="tweak()">✎ TWEAK PROMPT</button>
    `;
    history.unshift({path: filename, prompt: body.prompt, render_ms: data.render_ms, seed: data.seed});
    if (history.length > 12) history.length = 12;
    renderHistory();
  } catch (e) {
    $('preview-meta').textContent = 'error: ' + e.message;
  } finally {
    btn.disabled = false; spinner.classList.remove('active');
  }
}

function renderHistory() {
  $('history').innerHTML = history.map(h =>
    `<img src="/image/${h.path}" title="${h.prompt.replace(/"/g,'&quot;')}" onclick="loadFromHistory('${h.path}', ${JSON.stringify(h.prompt).replace(/'/g, "\\'")})">`
  ).join('');
}

function loadFromHistory(path, prompt) {
  $('preview-img-wrap').innerHTML = '<img src="/image/' + path + '" alt="">';
  $('preview-meta').textContent = path;
  $('prompt').value = prompt;
}

function reroll() {
  $('seed').value = '';
  generate();
}

function lockSeed(s) {
  $('seed').value = s;
  $('seed').focus();
}

function tweak() {
  $('prompt').focus();
  $('prompt').setSelectionRange($('prompt').value.length, $('prompt').value.length);
}

function onModelChange() {
  const model = $('model').value;
  // Adjust defaults per model
  if (model === 'turbo' || model === 'flux-schnell') {
    $('steps').value = 4;
    $('guidance').value = 0;
  } else if (model === 'playground') {
    $('steps').value = 30;
    $('guidance').value = 3;
  } else if (model === 'sdxl') {
    $('steps').value = 30;
    $('guidance').value = 7.5;
  }
}

$('prompt').addEventListener('keydown', e => {
  if (e.metaKey && e.key === 'Enter') generate();
});
// Trigger initial sync since playground is the default
onModelChange();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
