"""Train a Cosmos Reason 2 decision adapter from raw Spot decision captures."""

import argparse
from io import BytesIO
import json
from pathlib import Path
from time import perf_counter
import uuid

import modal

MODEL = "nvidia/Cosmos-Reason2-2B"
ROOT = Path(__file__).resolve().parents[1]
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.9.0", "torchvision==0.24.0", "transformers==4.57.3",
        "trl[peft]==0.26.1", "bitsandbytes==0.49.0", "pillow==12.0.0",
    )
    .add_local_file(ROOT / "sim" / "spot_agent.py", "/root/spot_agent.py")
)
app = modal.App("spot-cosmos-lora")
artifacts = modal.Volume.from_name("spot-cosmos-training", create_if_missing=True)


def load_examples(root):
    examples = []
    for manifest in sorted(root.rglob("decision.json")):
        snapshot = json.loads(manifest.read_text())
        snapshot["goals"] = [goal for goal in snapshot["goals"] if goal["route_clear"]]
        target = snapshot.pop("target")
        goal_id = target["goal_id"]
        if goal_id is not None and goal_id not in {goal["id"] for goal in snapshot["goals"]}:
            raise ValueError(f"Target goal is unavailable in {manifest}")
        if not isinstance(target["reason"], str) or not target["reason"].strip():
            raise ValueError(f"Missing target reason in {manifest}")
        rgb_path = manifest.parent / snapshot.pop("rgb_path")
        examples.append((snapshot, target, rgb_path.read_bytes()))
    if not examples:
        raise ValueError(f"No decision.json files under {root}")
    return examples


@app.function(
    image=image,
    gpu="H100",
    timeout=1800,
    volumes={"/artifacts": artifacts},
    secrets=[modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"])],
)
def train(examples: list, steps: int) -> str:
    from datasets import Dataset
    from peft import LoraConfig
    from PIL import Image
    from spot_agent import planner_messages
    import torch
    from transformers import BitsAndBytesConfig, Qwen3VLForConditionalGeneration, Qwen3VLProcessor
    from trl import SFTConfig, SFTTrainer

    started = perf_counter()
    rows = []
    for snapshot, target, rgb in examples:
        with Image.open(BytesIO(rgb)) as frame:
            frame = frame.convert("RGB")
            frame.thumbnail((640, 480))
        rows.append({
            "images": [frame],
            "prompt": planner_messages(snapshot),
            "completion": [{"role": "assistant", "content": [
                {"type": "text", "text": json.dumps(target)},
            ]}],
        })
    dataset = Dataset.from_list(rows)
    data_ready = perf_counter()
    cache_dir = "/artifacts/hf-cache"
    processor = Qwen3VLProcessor.from_pretrained(MODEL, cache_dir=cache_dir)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        MODEL, cache_dir=cache_dir, device_map={"": 0}, dtype=torch.bfloat16,
        attn_implementation="sdpa", quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        ),
    )
    model_ready = perf_counter()
    output = Path("/artifacts") / f"adapter-{uuid.uuid4().hex[:8]}"
    trainer = SFTTrainer(
        model=model, processing_class=processor, train_dataset=dataset,
        peft_config=LoraConfig(
            r=16, lora_alpha=32, task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        ),
        args=SFTConfig(
            output_dir=str(output), max_steps=steps, per_device_train_batch_size=1,
            gradient_checkpointing=True, bf16=True, optim="adamw_8bit",
            max_length=None, completion_only_loss=True, learning_rate=2e-4,
            report_to="none", save_strategy="no", logging_steps=1,
        ),
    )
    train_started = perf_counter()
    result = trainer.train()
    train_finished = perf_counter()
    trainer.save_model(str(output))
    (output / "timing.json").write_text(json.dumps({
        "examples": len(dataset), "steps": steps, "data_s": data_ready - started,
        "model_load_s": model_ready - data_ready, "trainer_setup_s": train_started - model_ready,
        "train_s": train_finished - train_started, "save_s": perf_counter() - train_finished,
        "train_loss": result.training_loss,
    }, indent=2))
    artifacts.commit()
    return output.name


@app.local_entrypoint()
def main(data: str, steps: int = 1):
    if steps < 1:
        raise ValueError("steps must be positive")
    examples = load_examples(Path(data))
    if len({target["goal_id"] for _, target, _ in examples}) < 2:
        raise ValueError("Training requires captures with at least two distinct target decisions")
    print(f"Loaded {len(examples)} decision captures")
    output = train.remote(examples, steps)
    print(f"Adapter saved to spot-cosmos-training /{output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate training input locally without model access")
    parser.add_argument("data", type=Path)
    args = parser.parse_args()
    print(f"Validated {len(load_examples(args.data))} decision captures")
