#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SHOT_SCALES = ["extreme-close-up", "close-up", "medium", "wide", "extreme-wide", "detail", "unknown"]
SEMANTIC_TAGS = [
    "people", "portrait", "group", "crowd", "street", "architecture", "interior",
    "landscape", "nature", "water", "sky", "vegetation", "transport", "car", "bicycle",
    "train", "performance", "event", "sculpture", "reflection", "silhouette", "motion",
    "abstract", "night", "food", "animal", "monochrome",
]
COMPOSITION_TAGS = [
    "centered", "symmetrical", "diagonal", "layered", "negative-space", "minimal",
    "dense", "geometric", "shallow-depth-of-field", "motion-blur",
]

def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_metrics(image: Image.Image) -> dict[str, Any]:
    rgb = image.convert("RGB")
    sample = rgb.copy()
    sample.thumbnail((256, 256))
    pixels = np.asarray(sample, dtype=np.float32) / 255.0
    pixels_u8 = np.asarray(sample, dtype=np.uint8)
    luminance = pixels[..., 0] * 0.2126 + pixels[..., 1] * 0.7152 + pixels[..., 2] * 0.0722
    maximum = pixels.max(axis=2)
    minimum = pixels.min(axis=2)
    saturation = np.zeros_like(maximum)
    np.divide(maximum - minimum, maximum, out=saturation, where=maximum > 0)
    brightness = float(luminance.mean())
    contrast = float(luminance.std())
    colorfulness = float(saturation.mean())
    warmth = float(np.clip(0.5 + (pixels[..., 0].mean() - pixels[..., 2].mean()) / 2, 0, 1))

    delta = maximum - minimum
    hue = np.zeros_like(maximum)
    chromatic_pixels = delta > 1e-6
    red_max = chromatic_pixels & (maximum == pixels[..., 0])
    green_max = chromatic_pixels & (maximum == pixels[..., 1])
    blue_max = chromatic_pixels & (maximum == pixels[..., 2])
    hue[red_max] = np.mod((pixels[..., 1][red_max] - pixels[..., 2][red_max]) / delta[red_max], 6)
    hue[green_max] = (pixels[..., 2][green_max] - pixels[..., 0][green_max]) / delta[green_max] + 2
    hue[blue_max] = (pixels[..., 0][blue_max] - pixels[..., 1][blue_max]) / delta[blue_max] + 4
    hue *= 60

    black = maximum < 0.12
    achromatic = (saturation < 0.15) & ~black
    white = achromatic & (maximum > 0.85)
    gray = achromatic & ~white
    chromatic = ~(black | white | gray)
    brown = chromatic & (hue >= 15) & (hue < 55) & (maximum < 0.58)
    color_masks = {
        "black": black,
        "white": white,
        "gray": gray,
        "red": chromatic & ~brown & ((hue < 15) | (hue >= 345)),
        "orange": chromatic & ~brown & (hue >= 15) & (hue < 45),
        "yellow": chromatic & ~brown & (hue >= 45) & (hue < 70),
        "green": chromatic & (hue >= 70) & (hue < 165),
        "teal": chromatic & (hue >= 165) & (hue < 195),
        "blue": chromatic & (hue >= 195) & (hue < 255),
        "purple": chromatic & (hue >= 255) & (hue < 290),
        "pink": chromatic & (hue >= 290) & (hue < 345),
        "brown": brown,
    }
    merged = {name: float(mask.mean()) for name, mask in color_masks.items()}
    color_profile = {name: round(weight, 4) for name, weight in merged.items()}
    dominant = [
        {"name": name, "weight": round(weight, 4)}
        for name, weight in sorted(merged.items(), key=lambda item: item[1], reverse=True)[:4]
        if weight > 0
    ]

    cv2.setRNGSeed(0)
    cluster_sample = sample.copy()
    cluster_sample.thumbnail((96, 96))
    cluster_pixels = np.asarray(cluster_sample, dtype=np.uint8).reshape(-1, 3).astype(np.float32)
    cluster_count = min(5, len(cluster_pixels))
    _, labels, centers = cv2.kmeans(
        cluster_pixels,
        cluster_count,
        None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5),
        1,
        cv2.KMEANS_PP_CENTERS,
    )
    label_counts = np.bincount(labels.ravel(), minlength=cluster_count)
    dominant_index = int(label_counts.argmax())
    dominant_rgb = np.clip(np.rint(centers[dominant_index]), 0, 255).astype(np.uint8)
    dominant_hsv = cv2.cvtColor(dominant_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2HSV)[0, 0]
    dominant_average_color = {
        "rgb": {"r": int(dominant_rgb[0]), "g": int(dominant_rgb[1]), "b": int(dominant_rgb[2])},
        "hsv": {
            "h": round(float(dominant_hsv[0]) * 2.0, 2),
            "s": round(float(dominant_hsv[1]) / 255.0, 4),
            "v": round(float(dominant_hsv[2]) / 255.0, 4),
        },
        "pixelShare": round(float(label_counts[dominant_index]) / len(cluster_pixels), 4),
        "clusters": cluster_count,
    }

    width, height = rgb.size
    orientation = "square" if abs(width - height) / max(width, height) < 0.05 else ("landscape" if width > height else "portrait")
    return {
        "width": width,
        "height": height,
        "orientation": orientation,
        "brightness": round(brightness, 4),
        "contrast": round(contrast, 4),
        "colorfulness": round(colorfulness, 4),
        "warmth": round(warmth, 4),
        "dominantColors": dominant,
        "colorProfile": color_profile,
        "dominantAverageColor": dominant_average_color,
    }


def tag_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "description": {"type": "string", "maxLength": 180},
            "shot_scale": {"type": "string", "enum": SHOT_SCALES},
            "people_count": {"type": "integer", "minimum": 0, "maximum": 100},
            "people_count_is_estimate": {"type": "boolean"},
            "semantic_tags": {"type": "array", "items": {"type": "string", "enum": SEMANTIC_TAGS}, "maxItems": 6},
            "composition_tags": {"type": "array", "items": {"type": "string", "enum": COMPOSITION_TAGS}, "maxItems": 4},
        },
        "required": ["description", "shot_scale", "people_count", "people_count_is_estimate", "semantic_tags", "composition_tags"],
        "additionalProperties": False,
    }


def analyze_with_ollama(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    ollama = config["ollama"]
    prompt = (
        "Index this photograph for a filterable photography library. First scan the foreground, middle ground, "
        "background, and every image edge. Describe only clearly visible content. "
        "Choose tags only from the supplied schema. shot_scale means framing of the primary subject: detail or "
        "extreme-close-up, close-up, medium, wide, extreme-wide; use unknown if there is no clear subject. "
        "Count visible people conservatively and mark the count as an estimate when anyone is distant, cropped, "
        "occluded, or the scene is crowded. Do not infer identity, gender, ethnicity, exact age, health, politics, "
        "religion, profession, relationships, or exact location. Return one short factual English description."
    )
    payload = {
        "model": ollama["model"],
        "stream": False,
        "think": False,
        "format": tag_schema(),
        "options": {"temperature": 0, "num_predict": 240},
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [base64.b64encode(path.read_bytes()).decode("ascii")],
        }],
    }
    request = urllib.request.Request(
        f"{ollama['baseUrl'].rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(int(ollama.get("retries", 3))):
        try:
            with urllib.request.urlopen(request, timeout=int(ollama.get("timeoutSeconds", 120))) as response:
                body = json.loads(response.read().decode("utf-8"))
            result = json.loads(body["message"]["content"])
            result["semantic_tags"] = [item for item in dict.fromkeys(result["semantic_tags"]) if item in SEMANTIC_TAGS]
            result["composition_tags"] = [item for item in dict.fromkeys(result["composition_tags"]) if item in COMPOSITION_TAGS]
            result["people_count"] = max(0, min(100, int(result["people_count"])))
            result["people_count_is_estimate"] = bool(result["people_count_is_estimate"] or result["people_count"] > 1)
            return result
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"Ollama failed after retries: {last_error}")


class ImageEmbedder:
    def __init__(self, model_name: str, requested_device: str) -> None:
        if requested_device == "mps" and torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")
        self.processor = AutoProcessor.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device).eval()

    def encode(self, image: Image.Image) -> list[float]:
        inputs = self.processor(images=image.convert("RGB"), return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items() if isinstance(value, torch.Tensor)}
        with torch.inference_mode():
            features = self.model.get_image_features(**inputs)
        if hasattr(features, "pooler_output"):
            features = features.pooler_output
        elif hasattr(features, "image_embeds"):
            features = features.image_embeds
        vector = features[0].float()
        vector = vector / torch.linalg.vector_norm(vector)
        return [round(float(value), 7) for value in vector.cpu().tolist()]


def computed_tags(metrics: dict[str, Any], semantic: dict[str, Any]) -> list[str]:
    tags = list(semantic["semantic_tags"]) + list(semantic["composition_tags"])
    if semantic["shot_scale"] != "unknown":
        tags.append(semantic["shot_scale"])
    people = semantic["people_count"]
    tags.append("no-people" if people == 0 else ("one-person" if people == 1 else ("small-group" if people <= 5 else "crowd")))
    tags.append("dark" if metrics["brightness"] < 0.33 else ("bright" if metrics["brightness"] > 0.66 else "mid-brightness"))
    tags.append("muted" if metrics["colorfulness"] < 0.2 else ("vivid" if metrics["colorfulness"] > 0.5 else "balanced-color"))
    tags.extend(item["name"] for item in metrics["dominantColors"][:2])
    return list(dict.fromkeys(tags))


def load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            records[record["key"]] = record
        except (json.JSONDecodeError, KeyError):
            continue
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local tags, visual metrics, and SigLIP embeddings")
    parser.add_argument("--config", default="config/analysis.config.json")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = read_json(resolve_path(args.config))
    gallery = read_json(resolve_path(config["galleryData"]))
    photos = gallery["photos"][:args.limit] if args.limit else gallery["photos"]
    image_root = resolve_path(config["imageRoot"])
    output = resolve_path(config["outputFile"])
    public_index = resolve_path(config["publicIndexFile"])
    checkpoint = resolve_path(config["checkpointFile"])
    output.parent.mkdir(parents=True, exist_ok=True)
    public_index.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    existing = {} if args.force else load_checkpoint(checkpoint)

    embedding_config = config["embeddings"]
    expected_models = {
        "tags": config["ollama"]["model"],
        "embedding": embedding_config["model"],
        "promptVersion": config["ollama"]["promptVersion"],
        "metricsVersion": config["analysisVersion"],
    }
    embedder: ImageEmbedder | None = None

    ordered_keys: list[str] = []
    records = dict(existing)
    for index, photo in enumerate(photos, start=1):
        key = f"{photo['albumId']}/{photo['id']}"
        ordered_keys.append(key)
        path = image_root / photo["src"].lstrip("/")
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = sha256(path)
        cached = records.get(key)
        cached_models = cached.get("models", {}) if cached else {}
        core_is_current = bool(
            cached
            and "error" not in cached.get("semantic", {})
            and cached.get("sha256") == digest
            and cached_models.get("tags") == expected_models["tags"]
            and cached_models.get("embedding") == expected_models["embedding"]
            and cached_models.get("promptVersion") == expected_models["promptVersion"]
        )
        if core_is_current:
            if cached_models.get("metricsVersion") != expected_models["metricsVersion"]:
                with Image.open(path) as image:
                    cached["visual"] = image_metrics(image)
                cached["models"] = expected_models
                cached["tags"] = computed_tags(cached["visual"], cached["semantic"])
                records[key] = cached
                with checkpoint.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(cached, ensure_ascii=False, separators=(",", ":")) + "\n")
                print(f"[{index}/{len(photos)}] refreshed metrics {key}", flush=True)
            else:
                print(f"[{index}/{len(photos)}] cached {key}", flush=True)
            continue

        started = time.monotonic()
        with Image.open(path) as image:
            metrics = image_metrics(image)
            if embedder is None:
                print(f"Loading {embedding_config['model']}…", flush=True)
                embedder = ImageEmbedder(embedding_config["model"], embedding_config.get("device", "mps"))
                print(f"Embedding device: {embedder.device}", flush=True)
            embedding = embedder.encode(image)
        try:
            semantic = analyze_with_ollama(path, config)
        except RuntimeError as error:
            semantic = {
                "description": "",
                "shot_scale": "unknown",
                "people_count": 0,
                "people_count_is_estimate": True,
                "semantic_tags": [],
                "composition_tags": [],
                "error": str(error),
            }
        record = {
            "key": key,
            "id": photo["id"],
            "albumId": photo["albumId"],
            "src": photo["src"],
            "date": photo["date"],
            "sha256": digest,
            "models": expected_models,
            "visual": metrics,
            "semantic": semantic,
            "tags": computed_tags(metrics, semantic),
            "embedding": embedding,
        }
        records[key] = record
        with checkpoint.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"[{index}/{len(photos)}] {key} ({time.monotonic() - started:.1f}s)", flush=True)

    final_records = [records[key] for key in ordered_keys if key in records]
    document = {
        "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "models": {
            "tags": config["ollama"]["model"],
            "embedding": embedding_config["model"],
            "promptVersion": config["ollama"]["promptVersion"],
            "metricsVersion": config["analysisVersion"],
            "embeddingDimensions": len(final_records[0]["embedding"]) if final_records else 0,
        },
        "photos": final_records,
    }
    output.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(final_records)} records to {output}", flush=True)

    public_document = {
        "version": document["version"],
        "generatedAt": document["generatedAt"],
        "photos": [
            {
                "key": record["key"],
                "id": record["id"],
                "albumId": record["albumId"],
                "date": record["date"],
                "visual": record["visual"],
                "semantic": {
                    "shot_scale": record["semantic"]["shot_scale"],
                    "people_count": record["semantic"]["people_count"],
                    "semantic_tags": record["semantic"]["semantic_tags"],
                    "composition_tags": record["semantic"]["composition_tags"],
                },
                "tags": record["tags"],
            }
            for record in final_records
        ],
    }
    public_index.write_text(
        json.dumps(public_document, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote compact public index to {public_index}", flush=True)


if __name__ == "__main__":
    main()
