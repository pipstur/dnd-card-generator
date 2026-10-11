"""
Batch-generate item images from a CSV using:
  - Ollama (qwen2.5:14b-instruct) to turn each item's description into a visual prompt
  - ComfyUI's API (running your Anima + DND-items-LoRA workflow) to render the image

Settings are resolved in this order (later wins):
    1. built-in defaults (the Config dataclass below)
    2. a JSON config file passed with --config
    3. command-line flags

Every Config field is available as a flag: snake_case -> --kebab-case.

Examples:
    python generate_item_images.py
    python generate_item_images.py --variants 4 --ollama-model qwen2.5:7b-instruct
    python generate_item_images.py --config config.json --output-dir out/test
    python generate_item_images.py --config config.json --print-config

Requires:
    pip install requests
  - Ollama running locally with the chosen model pulled
  - ComfyUI running locally (default http://127.0.0.1:8188)
  - An exported API-format workflow JSON
"""

import argparse
import copy
import csv
import json
import random
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import requests


@dataclass
class Config:
    # Files
    csv_path: Path = Path("output/dnd5e_wondrous_items.csv")
    output_dir: Path = Path("output/item_images")
    log_path: Path = Path("output/generation_log.jsonl")
    workflow_path: Path = Path("config/comfy_workflow.json")  # exported API-format JSON

    # Ollama
    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "qwen2.5:14b-instruct"
    ollama_temperature: float = 0.7
    ollama_timeout: int = 300

    # ComfyUI
    comfy_url: str = "http://127.0.0.1:8188"
    comfy_timeout: int = 180

    # Node IDs from the exported Anima + LoRA workflow
    positive_prompt_node_id: str = "90:77"  # CLIPTextEncode (Positive Prompt)
    negative_prompt_node_id: str = "90:75"  # CLIPTextEncode (Negative Prompt)
    ksampler_node_id: str = "90:76"  # KSampler (for randomizing the seed)
    save_image_node_id: str = "46"  # SaveImage (to find the output filename)

    # Suffix appended identically to every item — keeps the set visually
    # consistent instead of drifting per-item.
    style_suffix: str = (
        ", pure white background, soft gray smoke wisping behind the object, "
        "high fantasy painterly digital painting, rich brushwork, soft realistic "
        "shading, dramatic lighting, detailed textures, centered composition"
    )

    # Overrides whatever negative prompt is baked into the workflow JSON, adding
    # strong anti-text terms since Anima likes to hallucinate labels/watermarks.
    negative_prompt: str = (
        "worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
        "sepia, text, watermark, writing, letters, words, logo, signature, caption, "
        "speech bubble, label, title"
    )

    # Generation
    variants: int = 1


# Field names that are Paths, so values from JSON/TOML get converted.
_PATH_FIELDS = {f.name for f in fields(Config) if f.type is Path}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-generate D&D item images.")
    parser.add_argument(
        "--config", type=Path, help="Path to a JSON config file (CLI flags override it)"
    )
    parser.add_argument(
        "--print-config", action="store_true", help="Print the resolved config and exit"
    )

    defaults = Config()
    for f in fields(Config):
        parser.add_argument(
            "--" + f.name.replace("_", "-"),
            dest=f.name,
            type=f.type,
            default=None,  # None = "not given", so we know what to override
            help=f"default: {getattr(defaults, f.name)}",
        )
    return parser


def load_config_file(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"Config file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in {path}: {e}")

    valid = {f.name for f in fields(Config)}
    unknown = set(data) - valid
    if unknown:
        sys.exit(f"Unknown config key(s) in {path}: {', '.join(sorted(unknown))}")
    return data


def resolve_config(argv=None) -> tuple[Config, argparse.Namespace]:
    args = build_parser().parse_args(argv)

    values = asdict(Config())
    if args.config:
        values.update(load_config_file(args.config))
    for f in fields(Config):
        cli_val = getattr(args, f.name)
        if cli_val is not None:
            values[f.name] = cli_val

    for name in _PATH_FIELDS:
        values[name] = Path(values[name])
    for name in (
        "positive_prompt_node_id",
        "negative_prompt_node_id",
        "ksampler_node_id",
        "save_image_node_id",
    ):
        values[name] = str(values[name])  # allow bare ints in config files

    cfg = Config(**values)
    if cfg.variants < 1:
        sys.exit("--variants must be >= 1")
    return cfg, args


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

CLIENT_ID = uuid.uuid4().hex


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build_visual_description(cfg: Config, item: dict) -> str:
    """Condense the (often long, mechanics-heavy) CSV description into a short
    visual-only line, since raw rules text adds noise the model doesn't need."""
    system = (
        "You write short, vivid visual descriptions for an image generation model. "
        "Given a fantasy item's name, type, rarity, and description, output ONE line: "
        "a concrete visual description of what the object physically looks like "
        "(materials, shape, color, ornamentation, glow/magic effects). "
        "Ignore game rules, mechanical effects, and lore that has no visual component. "
        "Do not restate the item's name. Do not add commentary, quotes, or labels. "
        "Respond only in English — do not include any other language, script, or "
        "translation anywhere in your output. "
        "Output only the single description line, nothing else."
    )
    user = (
        f"Name: {item.get('Item Name', '')}\n"
        f"Type: {item.get('Type', '')}\n"
        f"Rarity: {item.get('Rarity', '')}\n"
        f"Description: {item.get('Description', '')}"
    )
    resp = requests.post(
        cfg.ollama_url,
        json={
            "model": cfg.ollama_model,
            "prompt": f"{system}\n\n{user}",
            "stream": False,
            "options": {"temperature": cfg.ollama_temperature},
        },
        timeout=cfg.ollama_timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip().strip('"').strip()


def build_full_prompt(cfg: Config, item: dict) -> str:
    """Matches the template already proven to work with this LoRA:
    'dnd item - <visual description> they are named <item name>', plus a fixed
    style/background suffix identical on every item for visual consistency."""
    visual = build_visual_description(cfg, item)
    name = item.get("Item Name", "").strip()
    return f"dnd item - {visual} they are named {name}{cfg.style_suffix}"


def queue_prompt(cfg: Config, workflow_template: dict, prompt_text: str) -> str:
    workflow = copy.deepcopy(workflow_template)
    workflow[cfg.positive_prompt_node_id]["inputs"]["text"] = prompt_text
    workflow[cfg.negative_prompt_node_id]["inputs"]["text"] = cfg.negative_prompt
    workflow[cfg.ksampler_node_id]["inputs"]["seed"] = random.randint(0, 2**32 - 1)

    resp = requests.post(
        f"{cfg.comfy_url}/prompt",
        json={"prompt": workflow, "client_id": CLIENT_ID},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["prompt_id"]


def wait_for_image(cfg: Config, prompt_id: str) -> bytes:
    start = time.time()
    while time.time() - start < cfg.comfy_timeout:
        resp = requests.get(f"{cfg.comfy_url}/history/{prompt_id}", timeout=30)
        resp.raise_for_status()
        history = resp.json()
        if prompt_id in history:
            outputs = history[prompt_id]["outputs"]
            image_info = outputs[cfg.save_image_node_id]["images"][0]
            params = {
                "filename": image_info["filename"],
                "subfolder": image_info.get("subfolder", ""),
                "type": image_info.get("type", "output"),
            }
            img_resp = requests.get(f"{cfg.comfy_url}/view", params=params, timeout=30)
            img_resp.raise_for_status()
            return img_resp.content
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")


def run(cfg: Config) -> None:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    workflow_template = json.loads(cfg.workflow_path.read_text(encoding="utf-8"))

    with open(cfg.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} items from {cfg.csv_path} — {cfg.variants} variant(s) each")

    with open(cfg.log_path, "a", encoding="utf-8") as log:
        for i, item in enumerate(rows, 1):
            name = item.get("Item Name", f"item-{i}")
            slug = slugify(name)

            variant_paths = [
                cfg.output_dir / (f"{slug}.png" if cfg.variants == 1 else f"{slug}_{v}.png")
                for v in range(1, cfg.variants + 1)
            ]
            # Skip the (cheap) Ollama call entirely if every variant already exists
            if all(p.exists() for p in variant_paths):
                continue

            for v, out_path in enumerate(variant_paths, 1):
                if out_path.exists():
                    continue  # resumable, per variant

                try:
                    prompt = build_full_prompt(cfg, item)
                    prompt_id = queue_prompt(cfg, workflow_template, prompt)
                    img_bytes = wait_for_image(cfg, prompt_id)
                    out_path.write_bytes(img_bytes)

                    log.write(
                        json.dumps(
                            {"item": name, "variant": v, "prompt": prompt, "file": str(out_path)}
                        )
                        + "\n"
                    )
                    log.flush()
                    print(
                        f"[{i}/{len(rows)}] {name} (variant {v}/{cfg.variants}) -> {out_path.name}"
                    )

                except Exception as e:
                    print(f"[{i}/{len(rows)}] FAILED: {name} (variant {v}): {e}")
                    log.write(json.dumps({"item": name, "variant": v, "error": str(e)}) + "\n")
                    log.flush()
                    time.sleep(2)


def main(argv=None) -> None:
    cfg, args = resolve_config(argv)
    if args.print_config:
        print(json.dumps(asdict(cfg), indent=2, default=str))
        return
    run(cfg)


if __name__ == "__main__":
    main()
