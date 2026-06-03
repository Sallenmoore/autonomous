#!/usr/bin/env python3
"""Image-provider evaluation harness.

Generate the same prompt corpus through N image providers and produce
a side-by-side HTML gallery for human creative-quality review. Used as
the validation gate before flipping IMAGE_PROVIDER_ROUTING=1 in
production (see specs/2026-06-02-image-gen-cost-design.md).

Usage:
    python scripts/image_provider_eval.py \\
      --prompts scripts/_eval_prompts.json \\
      --providers gemini,flux,local \\
      --aspect-ratios Portrait,2KPortrait \\
      --out eval-2026-06-02/

Each run independently generates one image per (prompt × provider ×
aspect_ratio) tuple — no built-in caching. Re-running the harness
re-bills for every entry. (Adding ``autonomous.ai.image_cache``
integration is a possible follow-up.)
"""

import argparse
import json
import sys
import time
from html import escape
from pathlib import Path

from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.imageagent import _COST_USD, _aspect_to_size_token


def _load_prompts(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"prompt corpus not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _estimate_cost(provider: str, aspect_ratio: str) -> float:
    size = _aspect_to_size_token(aspect_ratio)
    if (provider, size) in _COST_USD:
        return _COST_USD[(provider, size)]
    if (provider, "*") in _COST_USD:
        return _COST_USD[(provider, "*")]
    return 0.0


def _safe_filename(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)


def _generate(provider: str, prompt: str, aspect_ratio: str) -> tuple[bytes | None, float, str | None]:
    """Return (image_bytes_or_None, elapsed_seconds, error_or_None)."""
    cls = BaseAgent.MODEL_REGISTRY.get(provider)
    if cls is None:
        return None, 0.0, f"provider {provider!r} not in MODEL_REGISTRY"
    client = cls.__new__(cls)
    try:
        cls.__init__(client) if hasattr(cls, "__init__") else None
    except Exception as exc:
        return None, 0.0, f"could not init {provider}: {exc}"
    started = time.monotonic()
    try:
        img = client.generate_image(prompt, aspect_ratio=aspect_ratio)
    except Exception as exc:
        return None, time.monotonic() - started, f"{type(exc).__name__}: {exc}"
    return img, time.monotonic() - started, None


def _write_html(out_dir: Path, results: list[dict], providers: list[str]) -> None:
    rows = []
    by_prompt: dict[tuple[str, str], dict[str, dict]] = {}
    for r in results:
        by_prompt.setdefault((r["slug"], r["aspect_ratio"]), {})[r["provider"]] = r

    for (slug, ratio), per_prov in by_prompt.items():
        cells = []
        for prov in providers:
            entry = per_prov.get(prov, {})
            if entry.get("relpath"):
                cells.append(
                    f'<td><img src="{escape(entry["relpath"])}" alt="{escape(slug)}">'
                    f"<br><small>{prov} — {entry['elapsed']:.1f}s — ${entry['cost']:.3f}</small></td>"
                )
            else:
                err = entry.get("error", "(no result)")
                cells.append(
                    f'<td class="err">{prov} — failed<br><small>{escape(err)}</small></td>'
                )
        rows.append(
            f"<tr><th>{escape(slug)}<br><small>{escape(ratio)}</small></th>"
            + "".join(cells)
            + "</tr>"
        )

    head_cells = "<th></th>" + "".join(f"<th>{escape(p)}</th>" for p in providers)
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>image-provider eval</title>
<style>
  body {{ font-family: system-ui, sans-serif; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; }}
  img {{ max-width: 320px; height: auto; display: block; }}
  td.err {{ color: #a00; }}
</style></head><body>
<h1>image-provider eval</h1>
<table><thead><tr>{head_cells}</tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>
"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", required=True, type=Path,
                        help="path to prompt corpus JSON")
    parser.add_argument("--providers", required=True,
                        help="comma-separated providers, e.g. gemini,flux,local")
    parser.add_argument("--aspect-ratios", default="Portrait,2KPortrait",
                        help="comma-separated aspect ratios per prompt")
    parser.add_argument("--out", required=True, type=Path,
                        help="output directory for images + index.html")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    prompts = _load_prompts(args.prompts)
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    ratios = [r.strip() for r in args.aspect_ratios.split(",") if r.strip()]

    results: list[dict] = []
    totals: dict[str, dict] = {p: {"count": 0, "elapsed_s": 0.0, "cost_usd": 0.0} for p in providers}

    for entry in prompts:
        slug = entry["slug"]
        prompt = entry["prompt"]
        for ratio in ratios:
            for provider in providers:
                print(f"  {provider} × {slug} × {ratio} ...", flush=True)
                img, elapsed, err = _generate(provider, prompt, ratio)
                row = {
                    "slug": slug,
                    "category": entry.get("category", ""),
                    "aspect_ratio": ratio,
                    "provider": provider,
                    "elapsed": elapsed,
                    "cost": _estimate_cost(provider, ratio),
                    "error": err,
                }
                if img is not None:
                    fname = f"{provider}__{_safe_filename(slug)}__{_safe_filename(ratio)}.webp"
                    (args.out / fname).write_bytes(img)
                    row["relpath"] = fname
                results.append(row)
                totals[provider]["count"] += 1
                totals[provider]["elapsed_s"] += elapsed
                totals[provider]["cost_usd"] += row["cost"] if img is not None else 0.0

    (args.out / "summary.json").write_text(
        json.dumps({"results": results, "totals": totals}, indent=2),
        encoding="utf-8",
    )
    _write_html(args.out, results, providers)
    print(f"Wrote {args.out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
