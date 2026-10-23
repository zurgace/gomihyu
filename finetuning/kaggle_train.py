"""
Gomi's weekly fine-tune, run on Kaggle's free T4 GPU by finetuning/weekly.py (see its header): you don't
run this yourself. Every run starts from the stock Gemma 4 E4B, never from last week's model, so any
week can be redone or undone and how far she's melded comes only from the data's mix
(meld.persona_share).

It reads the private dataset weekly.py uploaded (train.jsonl, run.json), trains a QLoRA adapter on her
replies only (Unsloth), merges it into the model, converts that to GGUF with llama.cpp and quantizes it
like the stock model (Q4_K_M), and writes what weekly.py downloads to /kaggle/working:
  gomi-wN.Q4_K_M.gguf  her model, text only (pictures stay on the stock model: VISION_MODEL)
  result.json          what happened: examples used, loss, minutes, or the error
The log (downloaded too) has counts and losses only, never a line of chat, and weekly.py deletes the
dataset from Kaggle once the model is downloaded.

The installs follow Unsloth's Gemma 4 notebook (github.com/unslothai/notebooks, nb/Gemma4_(E4B)-Text.ipynb);
if they stop working, compare PIP with that notebook's first cell.
"""

RUN = 0  # weekly.py writes the run number here when it pushes this script

import gc
import glob
import inspect
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # Kaggle's "T4 x2": Unsloth trains on one
INPUT = Path("/kaggle/input")  # where Kaggle mounts the attached dataset
OUT = Path("/kaggle/working")
SCRATCH = Path("/kaggle/temp/gomi")  # the big in-between files, never downloaded
PIP = [
    ["unsloth"],
    ["--no-deps", "transformers==5.5.0", "tokenizers>=0.22.0,<=0.23.0"],
    ["huggingface_hub>=1.5.0,<2.0"],
    ["--no-deps", "--upgrade", "timm"],  # Gemma 4 loads its vision/audio parts even for text training
]
LLAMA_CPP = "https://github.com/ggml-org/llama.cpp"
START = time.time()
result = {"run": RUN}


def say(text: str) -> None:
    print(f"[{(time.time() - START) / 60:5.1f} min] {text}", flush=True)


def write_result(**extra) -> None:
    result.update(extra, minutes=round((time.time() - START) / 60, 1))
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")


def fail(text: str) -> None:
    say(f"FAILED: {text}")
    write_result(error=text)
    sys.exit(0)  # not 1: Kaggle may not keep a failed run's output, and result.json is how weekly.py hears why


def run(*command: str, what: str) -> None:
    say(what)
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode:
        print(done.stdout[-3000:], done.stderr[-3000:], sep="\n", flush=True)
        fail(f"{what} failed (exit {done.returncode}); the log above has the end of its output")


def load_data() -> tuple[dict, list[dict]]:
    found = sorted(glob.glob(f"{INPUT}/**/run.json", recursive=True))
    if not found:
        fail(f"no run.json under {INPUT}: the dataset isn't attached to this notebook")
    config = json.loads(Path(found[0]).read_text())
    if config.get("run") != RUN:
        fail(f"the attached data is for run {config.get('run')}, not run {RUN}: Kaggle was still serving the "
             "dataset's older version. Wait a few minutes and run weekly.py upload again.")
    lines = (Path(found[0]).parent / "train.jsonl").read_text(encoding="utf-8").splitlines()
    return config, [json.loads(line) for line in lines if line.strip()]


def check_gpu() -> str:
    try:
        name, capability = subprocess.run(["nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv,noheader"],
                                          capture_output=True, text=True).stdout.splitlines()[0].split(", ")
    except (OSError, IndexError, ValueError):
        fail("no GPU: weekly.py pushes this with a T4 (--accelerator); check the notebook's settings on Kaggle")
    if float(capability) < 7.0:  # the P100, Kaggle's other free GPU
        fail(f"got a {name}, which Unsloth doesn't support; it needs the T4 (weekly.py upload --accelerator)")
    return name


def masks_prompts(trainer, tokenizer, reply: str) -> bool:
    """Whether training only sees her reply: the first example's unmasked tokens are just that."""
    labels = trainer.train_dataset[0]["labels"]
    kept = [token for token in labels if token != -100]
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    return 0 < len(kept) < len(labels) and " ".join(reply.split())[:30] in " ".join(text_tokenizer.decode(kept).split())


def train(config: dict, rows: list[dict]) -> Path:
    """The merged model, in 16-bit safetensors, in SCRATCH."""
    import torch
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastModel
    from unsloth.chat_templates import get_chat_template, train_on_responses_only

    max_len = config["max_len"]
    say(f"Loading {config['base']} in 4 bits")
    model, tokenizer = FastModel.from_pretrained(model_name=config["base"], dtype=None, max_seq_length=max_len,
                                                 load_in_4bit=True, full_finetuning=False)
    model = FastModel.get_peft_model(model, finetune_vision_layers=False, finetune_language_layers=True,
                                     finetune_attention_modules=True, finetune_mlp_modules=True,
                                     r=config["rank"], lora_alpha=config["rank"], lora_dropout=0, bias="none",
                                     random_state=3407)
    tokenizer = get_chat_template(tokenizer, chat_template="gemma-4")
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    texts, replies, too_long = [], [], 0
    for row in rows:
        text = tokenizer.apply_chat_template(row["messages"], tokenize=False,
                                             add_generation_prompt=False).removeprefix("<bos>")
        if len(text_tokenizer(text, add_special_tokens=False)["input_ids"]) + 1 > max_len:
            too_long += 1  # cut to fit, it would lose her reply at the end: left out instead
            continue
        texts.append(text)
        replies.append(row["messages"][-1]["content"])
    say(f"{len(texts)} examples, {too_long} longer than {max_len} tokens left out")
    if not texts:
        fail("no examples fit")
    result.update(examples=len(texts), too_long=too_long)

    length = "max_length" if "max_length" in inspect.signature(SFTConfig).parameters else "max_seq_length"
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=Dataset.from_list([{"text": t} for t in texts]),
        args=SFTConfig(dataset_text_field="text", per_device_train_batch_size=1, gradient_accumulation_steps=4,
                       warmup_steps=5, num_train_epochs=config["epochs"], learning_rate=config["lr"],
                       logging_steps=5, optim="adamw_8bit", weight_decay=0.001, lr_scheduler_type="linear",
                       seed=3407, report_to="none", save_strategy="no", output_dir=str(SCRATCH / "checkpoints"),
                       **{length: max_len}))
    trainer = train_on_responses_only(trainer)
    if not masks_prompts(trainer, tokenizer, replies[0]):  # the template's markers weren't found: say so
        fail("couldn't mask the prompts, so it would train on the chat log too; Unsloth's Gemma 4 chat "
             "template may have changed (see the notebook named at the top)")
    say(f"Training: {config['epochs']} epoch(s), LoRA rank {config['rank']}, learning rate {config['lr']}")
    stats = trainer.train()
    result.update(loss=round(stats.training_loss, 4))
    say(f"Trained, final average loss {stats.training_loss:.4f}")

    merged = SCRATCH / "merged"
    say("Merging the adapter into the 16-bit model")
    model.save_pretrained_merged(str(merged), tokenizer)
    del model, trainer
    gc.collect()
    torch.cuda.empty_cache()
    return merged


def to_gguf(merged: Path, quant: str) -> Path:
    from huggingface_hub import constants
    shutil.rmtree(constants.HF_HUB_CACHE, ignore_errors=True)  # the downloaded base: disk for what's next
    llama = SCRATCH / "llama.cpp"
    run("git", "clone", "--depth", "1", LLAMA_CPP, str(llama), what="Getting llama.cpp")
    f16 = SCRATCH / "model.F16.gguf"
    run(sys.executable, str(llama / "convert_hf_to_gguf.py"), str(merged), "--outtype", "f16", "--outfile", str(f16),
        what="Converting to GGUF")
    shutil.rmtree(merged)
    out = OUT / f"gomi-w{RUN}.{quant}.gguf"
    if quant.upper() == "F16":
        shutil.move(f16, out)
        return out
    if not shutil.which("cmake"):
        run(sys.executable, "-m", "pip", "install", "-q", "cmake", what="Installing cmake")
    run("cmake", "-S", str(llama), "-B", str(llama / "build"), "-DGGML_CUDA=OFF", "-DLLAMA_CURL=OFF",
        "-DLLAMA_BUILD_TESTS=OFF", what="Configuring llama.cpp")
    run("cmake", "--build", str(llama / "build"), "--target", "llama-quantize", "-j", str(os.cpu_count() or 2),
        what="Building llama-quantize")
    run(str(llama / "build" / "bin" / "llama-quantize"), str(f16), str(out), quant, what=f"Quantizing to {quant}")
    f16.unlink()
    return out


def main() -> None:
    try:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        os.chdir(SCRATCH)  # Unsloth's compile cache lands in the working folder: not in what gets downloaded
        config, rows = load_data()
        result.update(base=config["base"], epochs=config["epochs"], rank=config["rank"], gpu=check_gpu())
        say(f"Run {RUN}: {len(rows)} examples on a {result['gpu']}")
        for args in PIP:
            run(sys.executable, "-m", "pip", "install", "-q", *args, what=f"pip install {' '.join(args)}")
        merged = train(config, rows)
        gguf = to_gguf(merged, config["quant"])
        write_result(gguf=gguf.name, gguf_bytes=gguf.stat().st_size)
        say(f"Done: {gguf.name}, {gguf.stat().st_size / 1e9:.1f} GB")
    except Exception as e:  # a crash in Unsloth, torch or the like: the traceback goes to the log
        traceback.print_exc()
        fail(f"{type(e).__name__}: {str(e)[:300]}; the log has the traceback")


if __name__ == "__main__":
    main()
