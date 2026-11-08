"""Send one accepted onboard image to YOLO and retain auditable review outputs."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil

from PIL import Image, ImageDraw

from api_client import predict


def render_boxes(image, detections):
    overlay = image.convert("RGB")
    draw = ImageDraw.Draw(overlay)
    colors = {"drum": "#7cc4ff", "corrosion": "#ff9f5e", "bulge": "#c89aff"}
    for detection in detections:
        label = detection["class_name"]
        x0, y0, x1, y1 = detection["bbox_xyxy"]
        if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
            raise ValueError(f"Detection box outside input image: {detection['bbox_xyxy']}")
        draw.rectangle((x0, y0, x1, y1), outline=colors[label], width=3)
        draw.text((x0 + 3, max(0, y0 - 14)), f"{label} {detection['confidence']:.2f}",
                  fill=colors[label], stroke_width=2, stroke_fill="black")
    return overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--expected-model-sha256", help="Reject a response from a different checkpoint")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    keys = ("DETECTOR_API_URL", "DETECTOR_API_KEY", "DETECTOR_API_SECRET")
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        parser.error(f"Missing detector configuration: {', '.join(missing)}")
    args.out.mkdir(parents=True, exist_ok=False)
    source = args.out / f"input{args.image.suffix}"
    shutil.copyfile(args.image, source)
    metadata = {
        "frame_id": args.frame_id,
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "profile": "fixed",
        "confidence": 0.25,
    }
    try:
        response = predict(os.environ[keys[0]], source, os.environ[keys[1]], os.environ[keys[2]],
                           band="fixed", confidence=0.25)
    except Exception as error:
        metadata.update(status="request_failed", error_type=type(error).__name__,
                        http_status=getattr(error, "code", None))
        (args.out / "frame.json").write_text(json.dumps(metadata, indent=2) + "\n")
        raise SystemExit(f"Detector request failed: {type(error).__name__}") from None
    (args.out / "response.json").write_text(json.dumps(response, indent=2) + "\n")
    with Image.open(source) as image:
        dimensions = response["image"]
        if (dimensions["width"], dimensions["height"]) != image.size:
            raise SystemExit("Detector response dimensions differ from the input image")
        model_sha256 = response["best_sha256"]
        if args.expected_model_sha256 and model_sha256 != args.expected_model_sha256:
            raise SystemExit("Detector response came from a different checkpoint")
        detections = response["detections"]
        render_boxes(image, detections).save(args.out / "overlay.png")
        metadata.update(status="ok", width=image.width, height=image.height,
                        model_sha256=model_sha256, model_run_id=response["run_id"],
                        detections=dict(Counter(d["class_name"] for d in detections)))
    (args.out / "frame.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
