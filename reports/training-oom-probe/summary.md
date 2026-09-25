# GPU training OOM smoke test

Both bounded tests passed training, evaluation, LoRA merge and weight saving without OOM. Code: `eead6e8`, NVIDIA GB10, Qwen2.5-7B-Instruct, PyTorch 2.11.0+cu130.

| Test | Train batch | Eval batch | Accumulation | Peak allocated GiB | Peak reserved GiB | Duration |
|---|---:|---:|---:|---:|---:|---:|
| conservative | 1 | 1 | 1 | 15.61 | 16.36 | 248 s |
| current-defaults | 4 | 8 | 4 | 17.97 | 20.48 | 308 s |

During the current-default test, sampled whole-system used memory peaked at **45.07 GiB**, with at least **76.55 GiB** available in those samples. This includes CPU/model-saving buffers, OS and unrelated processes; it is not GPU allocator memory.

Two optimizer steps each; evaluation uses 20 examples held out from the 387-row training set, not the benchmark test set. Actual training lengths: 408–1,233 tokens, below the configured 3,072-token cap. BF16 LoRA rank 16 and gradient checkpointing were enabled.

Training packages were installed into a separate virtual environment; the serving environment and source code were not changed. Docker requires elevated access and was not tested. The diagnostic wrapper reduced evaluation batch only for the conservative run and added memory logging/callbacks. The current-default run retained the original batch/evaluation/accumulation settings.

No Hugging Face upload, automatic deployment of smoke weights, full-epoch quality claim, full-context memory guarantee or concurrent serving/training validation. Raw measurements are stored beside this summary.

Original inference was restored on port 8000 and returned `OK` to a real chat-completion request.
