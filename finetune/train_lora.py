"""LoRA fine-tune of the edge-fast model on finetune/data/sft.jsonl, then merge to BF16.

Runs inside the NGC PyTorch container on the Nano (see run_finetune.sh), mirroring the HP
reference repo (jrgosalvez/Med_VLM_Fine-Tune_vLLM). Loss is on the assistant answer only
(TRL prompt/completion format). Output: finetune/outputs/merged (servable with zrt/vLLM),
optionally pushed to $HF_REPO_ID.
"""
import argparse
import inspect
import json
import math
import os
import time
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct"))
    ap.add_argument("--data", default=str(ROOT / "finetune/data/sft.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "finetune/outputs"))
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--max-length", type=int, default=3072)
    ap.add_argument("--max-steps", type=int, default=-1, help="cap steps for a smoke test")
    ap.add_argument("--push", action="store_true", help="push merged model to $HF_REPO_ID")
    args = ap.parse_args()
    print(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}", flush=True)
    out = Path(args.out)
    dataset = load_dataset("json", data_files=args.data, split="train").remove_columns(["id"])
    split = dataset.train_test_split(test_size=.05, seed=7)

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(args.base, dtype=torch.bfloat16, attn_implementation="sdpa")
    lora = LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=.05, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    steps_per_epoch = math.ceil(len(split["train"]) / (args.batch * args.grad_accum))
    total_steps = args.max_steps if args.max_steps > 0 else math.ceil(steps_per_epoch * args.epochs)
    options = dict(output_dir=str(out / "lora"), num_train_epochs=args.epochs, learning_rate=args.lr,
                   per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
                   lr_scheduler_type="cosine", warmup_steps=max(1, int(.05 * total_steps)), bf16=torch.cuda.is_available(),
                   use_cpu=not torch.cuda.is_available(), logging_steps=5,
                   eval_strategy="epoch", save_strategy="no", gradient_checkpointing=True, report_to="none",
                   max_steps=args.max_steps, max_length=args.max_length, max_seq_length=args.max_length)
    # TRL/transformers rename and drop arguments between releases; pass only what this version accepts.
    accepted = inspect.signature(SFTConfig).parameters
    config = SFTConfig(**{k: v for k, v in options.items() if k in accepted})
    trainer = SFTTrainer(model=model, args=config, train_dataset=split["train"], eval_dataset=split["test"],
                         processing_class=tokenizer, peft_config=lora)
    start = time.time()
    result = trainer.train()
    metrics = {"base_model": args.base, "examples": len(split["train"]), "train_seconds": round(time.time() - start, 1),
               "train_loss": result.training_loss, "eval": trainer.evaluate(),
               "peak_gpu_memory_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if torch.cuda.is_available() else None}
    trainer.model.save_pretrained(out / "lora")

    merged = trainer.model.merge_and_unload()
    merged.save_pretrained(out / "merged", safe_serialization=True)
    tokenizer.save_pretrained(out / "merged")
    meta = Path(args.data).with_name("sft_meta.json")
    if meta.exists():  # ship the prompt switches with the weights so evaluation can use the same .env
        metrics["sft_meta"] = json.loads(meta.read_text())
        (out / "merged" / "edgesupport_training_meta.json").write_text(meta.read_text())
    (out / "train_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    print(json.dumps(metrics, indent=2, default=str))

    repo = os.getenv("HF_REPO_ID")
    if args.push and repo:
        from huggingface_hub import create_repo
        create_repo(repo, private=True, exist_ok=True)
        merged.push_to_hub(repo, private=True)
        tokenizer.push_to_hub(repo, private=True)
        print(f"Pushed to https://huggingface.co/{repo}  ->  zrt pull {repo} && zrt serve {repo} --port 8000")

if __name__ == "__main__":
    main()
