"""Convert an exact-frame YOLO review into C.A.N.I.S. WebSocket messages."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def envelope(kind, source, seq, **fields):
    return {"schema": "canis.v1", "kind": kind, "source": {"kind": source, "id": f"warehouse-{source}"},
            "seq": seq, "quality": "ok", **fields}


def frame_events(review):
    metadata = json.loads((review / "frame.json").read_text())
    if metadata["status"] != "ok":
        raise ValueError("A successful detector response is required")
    response = json.loads((review / "response.json").read_text())
    source, = review.glob("input.*")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata["input_sha256"]:
        raise ValueError("Input image does not match the reviewed frame")
    if response["best_sha256"] != metadata["model_sha256"]:
        raise ValueError("Response checkpoint does not match the review")
    if response["image"] != {key: metadata[key] for key in ("width", "height")}:
        raise ValueError("Response dimensions do not match the review")

    frame_id = metadata["frame_id"]
    encoding = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}[source.suffix.lower()]
    uri = f"data:image/{encoding};base64," + base64.b64encode(raw).decode("ascii")
    yield envelope("camera_frame", "isaac", 0, camera_id="rgb", frame_id=frame_id,
                   width=metadata["width"], height=metadata["height"], uri=uri, encoding=encoding)
    for index, detection in enumerate(response["detections"]):
        x0, y0, x1, y1 = detection["bbox_xyxy"]
        yield envelope("detection", "detector", index, camera_id="rgb", frame_id=frame_id,
                       detection_id=f"{frame_id}:{index}", class_id=detection["class_id"],
                       bbox_px=[x0, y0, x1 - x0, y1 - y0], confidence=detection["confidence"],
                       model_id=f"{response['run_id']}:{response['best_sha256']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    print(json.dumps(list(frame_events(args.review))))
