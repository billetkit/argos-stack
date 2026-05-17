#!/usr/bin/env python3
"""img-gen.py — Generate an image via SDXL Turbo on the Mac mini.

Usage:
    python3 img-gen.py --prompt "your prompt" --output /tmp/out.png [--steps 2] [--seed 42]

First run downloads ~6.5GB to ~/.cache/huggingface/.
Subsequent runs reuse the cached model (~5-8 sec/image on M-series via MPS).
"""
import argparse, sys, time
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--output", default="/tmp/out.png")
    ap.add_argument("--steps", type=int, default=2)
    ap.add_argument("--guidance", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--height", type=int, default=512)
    ap.add_argument("--width", type=int, default=512)
    args = ap.parse_args()

    print(f"[img-gen] loading SDXL Turbo (first run downloads ~6.5GB)…", flush=True)
    t0 = time.time()
    import torch
    from diffusers import AutoPipelineForText2Image

    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sdxl-turbo",
        torch_dtype=torch.float16,
        variant="fp16",
        use_safetensors=True,
    )
    pipe = pipe.to("mps")
    pipe.set_progress_bar_config(disable=True)
    print(f"[img-gen] model ready in {time.time()-t0:.1f}s", flush=True)

    gen = None
    if args.seed is not None:
        gen = torch.Generator(device="mps").manual_seed(args.seed)

    print(f"[img-gen] generating: {args.prompt[:120]}", flush=True)
    t1 = time.time()
    image = pipe(
        prompt=args.prompt,
        num_inference_steps=args.steps,
        guidance_scale=args.guidance,
        height=args.height,
        width=args.width,
        generator=gen,
    ).images[0]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)
    print(f"[img-gen] saved {args.output} ({Path(args.output).stat().st_size} bytes, {time.time()-t1:.1f}s render)", flush=True)


if __name__ == "__main__":
    main()
