"""Replay Spot sensor snapshots through the inspection planner and safety gate."""

import argparse
import json
import math
from pathlib import Path


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_limits(limits):
    if not isinstance(limits, dict) or not limits:
        raise ValueError("Configure at least one required sensor limit")
    for sensor, rule in limits.items():
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("unit"), str)
            or not rule["unit"].strip()
            or not finite_number(rule.get("stop_at"))
            or not finite_number(rule.get("max_age_s"))
            or rule["max_age_s"] <= 0
        ):
            raise ValueError(f"Invalid safety limit for {sensor}")


def safety_stop(readings, limits):
    for sensor, rule in limits.items():
        reading = readings.get(sensor)
        if not isinstance(reading, dict):
            return f"{sensor}: missing reading"
        value = reading.get("value")
        age = reading.get("age_s")
        if (
            reading.get("unit") != rule["unit"]
            or not finite_number(value)
            or not finite_number(age)
            or not 0 <= age <= rule["max_age_s"]
        ):
            return f"{sensor}: invalid unit, value, or sample age"
        if value >= rule["stop_at"]:
            return f"{sensor}: {value} {rule['unit']} reached stop limit {rule['stop_at']}"
    return None


def decide(snapshot, limits, planner):
    """Return a goal proposal or a hold. The caller owns motion and revalidation."""
    reason = safety_stop(snapshot["readings"], limits)
    if reason:
        return {"action": "hold", "source": "safety", "reason": reason}

    # The navigation layer owns route and clearance checks before offering goals.
    goals = [goal for goal in snapshot["goals"] if goal.get("route_clear") is True]
    if not goals:
        return {"action": "hold", "source": "navigation", "reason": "No clear route"}

    try:
        proposal = planner({**snapshot, "goals": goals})
        goal_id = proposal["goal_id"]
        reason = proposal["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Missing reason")
        if goal_id is None:
            return {"action": "hold", "source": "planner", "reason": reason}
        if not isinstance(goal_id, str) or not any(goal["id"] == goal_id for goal in goals):
            raise ValueError("Goal is outside the offered set")
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as error:
        return {"action": "hold", "source": "planner_error", "reason": str(error)}
    return {"action": "navigate", "source": "planner", "goal_id": goal_id, "reason": reason}


class CosmosPlanner:
    def __init__(self, model_path, adapter_path):
        import torch
        from transformers import Qwen3VLForConditionalGeneration, Qwen3VLProcessor

        if not model_path.is_dir() or (adapter_path and not adapter_path.is_dir()):
            raise ValueError("Model and adapter paths must be local checkpoint directories")
        model_path = str(model_path.resolve())
        self.torch = torch
        self.processor = Qwen3VLProcessor.from_pretrained(model_path, local_files_only=True)
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_path, dtype=torch.float16, device_map={"": "cuda"},
            attn_implementation="sdpa", local_files_only=True,
        )
        if adapter_path:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, str(adapter_path.resolve()), local_files_only=True)
        self.model.eval()

    def __call__(self, snapshot):
        from PIL import Image

        with Image.open(snapshot["rgb_path"]) as frame:
            rgb = frame.convert("RGB")
        rgb.thumbnail((640, 480))
        context = {key: snapshot[key] for key in ("readings", "goals")}
        context["findings"] = snapshot.get("findings", [])
        messages = [
            {"role": "system", "content": (
                "You plan a waste-drum inspection. Use the image, sensor readings and findings "
                "to choose one offered goal. Prioritize a useful view of suspected damage, "
                "otherwise continue inspection. Return only JSON with goal_id (an offered ID "
                "or null to hold) and reason (one short sentence grounded in the observations)."
            )},
            {"role": "user", "content": [
                {"type": "image", "image": rgb},
                {"type": "text", "text": json.dumps(context)},
            ]},
        ]
        inputs = self.processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt",
        ).to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=128, do_sample=False)
        tokens = output[0, inputs.input_ids.shape[1]:]
        return json.loads(self.processor.decode(tokens, skip_special_tokens=True))


def baseline(snapshot):
    finding_ids = {finding["id"] for finding in snapshot.get("findings", [])}
    for goal in snapshot["goals"]:
        if goal.get("finding_id") in finding_ids:
            return {"goal_id": goal["id"], "reason": f"Check reported finding {goal['finding_id']}"}
    return {"goal_id": snapshot["goals"][0]["id"], "reason": "Continue inspection"}


def demo_snapshots():
    # Synthetic units and values for exercising the software only.
    limits = {
        "radiation": {"unit": "sim_rad", "stop_at": 10, "max_age_s": 1},
        "thermal": {"unit": "sim_heat", "stop_at": 8, "max_age_s": 1},
    }
    readings = {
        "radiation": {"value": 2, "unit": "sim_rad", "age_s": 0},
        "thermal": {"value": 3, "unit": "sim_heat", "age_s": 0},
    }
    patrol = {"id": "patrol_aisle", "route_clear": True}
    inspect = {"id": "inspect_drum", "route_clear": True, "finding_id": "spill_1"}
    return limits, [
        {"readings": readings, "goals": [patrol]},
        {
            "readings": readings, "goals": [patrol, inspect],
            "findings": [{"id": "spill_1", "label": "possible spill"}],
        },
        {
            "readings": {**readings, "radiation": {**readings["radiation"], "value": 12}},
            "goals": [inspect],
        },
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Replay three synthetic snapshots")
    parser.add_argument("--limits", type=Path, help="JSON safety limit configuration")
    parser.add_argument("--observations", type=Path, help="JSONL sensor snapshots")
    parser.add_argument("--model", type=Path, help="Local Cosmos Reason 2 checkpoint directory")
    parser.add_argument("--adapter", type=Path, help="Optional local PEFT adapter directory")
    args = parser.parse_args()
    if args.adapter and not args.model:
        parser.error("--adapter requires --model")
    if args.demo:
        if args.limits or args.observations or args.model:
            parser.error("--demo uses its own synthetic inputs and baseline")
        limits, snapshots = demo_snapshots()
    else:
        if not args.limits or not args.observations:
            parser.error("provide --limits and --observations, or use --demo")
        limits = json.loads(args.limits.read_text())
        snapshots = [
            json.loads(line) for line in args.observations.read_text().splitlines() if line.strip()
        ]
    validate_limits(limits)
    planner = CosmosPlanner(args.model, args.adapter) if args.model else baseline
    for snapshot in snapshots:
        print(json.dumps(decide(snapshot, limits, planner)), flush=True)


if __name__ == "__main__":
    main()
