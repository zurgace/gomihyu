import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
"""finetuning/kaggle_train.py with Unsloth, the GPU, pip and llama.cpp faked: its plumbing, not the training."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(REPO)
calls = []


# --- fake libraries
class FakeTok:
    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": text.split()}  # a word is a token

    def decode(self, ids):
        return " ".join(ids)


class FakeProcessor:
    tokenizer = FakeTok()

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        return "<bos>" + " ".join(f"<|turn>{m['role']} {m['content']} <turn|>" for m in messages)


class FakeModel:
    def save_pretrained_merged(self, path, tokenizer):
        Path(path).mkdir(parents=True)
        (Path(path) / "model.safetensors").write_text("weights")
        calls.append("merged")


class FastModel:
    @staticmethod
    def from_pretrained(**kw):
        calls.append(("load", kw))
        return FakeModel(), FakeProcessor()

    @staticmethod
    def get_peft_model(model, **kw):
        calls.append(("peft", kw))
        return model


MASK = {"on": True}


def train_on_responses_only(trainer):
    rows = []
    for row in trainer.train_dataset:
        tokens = row["text"].split()
        start = max(i for i, t in enumerate(tokens) if t == "<|turn>assistant") + 1 if MASK["on"] else len(tokens)
        rows.append({"labels": [-100] * start + tokens[start:]})
    trainer.train_dataset = rows
    return trainer


def SFTConfig(dataset_text_field=None, max_length=None, **kw):
    return {"dataset_text_field": dataset_text_field, "max_length": max_length, **kw}


class SFTTrainer:
    def __init__(self, model, tokenizer, train_dataset, args):
        self.train_dataset, self.args = train_dataset, args
        calls.append(("trainer", args))

    def train(self):
        calls.append(("train", len(self.train_dataset)))
        return types.SimpleNamespace(training_loss=1.23456)


def module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


work = Path(tempfile.mkdtemp())
hf_cache = work / "hf" / "hub"
module("unsloth", FastModel=FastModel)
module("unsloth.chat_templates", get_chat_template=lambda tok, chat_template: tok,
       train_on_responses_only=train_on_responses_only)
module("trl", SFTConfig=SFTConfig, SFTTrainer=SFTTrainer)
module("datasets", Dataset=types.SimpleNamespace(from_list=lambda rows: list(rows)))
module("torch", cuda=types.SimpleNamespace(empty_cache=lambda: calls.append("empty_cache")))
module("huggingface_hub", constants=types.SimpleNamespace(HF_HUB_CACHE=str(hf_cache)))

spec = importlib.util.spec_from_file_location("kaggle_train", REPO / "finetuning" / "kaggle_train.py")
kt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kt)

GPU = {"line": "Tesla T4, 7.5\n"}


def fake_run(command, capture_output=True, text=True):
    command = [str(c) for c in command]
    calls.append(("run", command[:3]))
    out = ""
    if command[0] == "nvidia-smi":
        out = GPU["line"]
    elif command[:2] == ["git", "clone"]:
        Path(command[-1]).mkdir(parents=True)
        (Path(command[-1]) / "convert_hf_to_gguf.py").write_text("")
    elif command[1].endswith("convert_hf_to_gguf.py"):
        assert Path(command[2]).is_dir()  # the merged model is still there
        Path(command[command.index("--outfile") + 1]).write_bytes(b"f16" * 100)
    elif command[0].endswith("llama-quantize"):
        assert Path(command[1]).exists()
        Path(command[2]).write_bytes(b"q4" * 50)
        assert command[3] == "Q4_K_M"
    return types.SimpleNamespace(returncode=0, stdout=out, stderr="")


kt.subprocess = types.SimpleNamespace(run=fake_run)


def rows(n, reply_words=5):
    return [{"messages": [{"role": "system", "content": "you are gomi"},
                          {"role": "user", "content": f"kaz0: line {i}"},
                          {"role": "assistant", "content": " ".join(f"secretreply{i}w{k}" for k in range(reply_words))}]}
            for i in range(n)]


def setup(run=3, data=None, max_len=60, quant="Q4_K_M"):
    base = Path(tempfile.mkdtemp(dir=work))
    kt.INPUT, kt.OUT, kt.SCRATCH = base / "input", base / "working", base / "temp" / "gomi"
    kt.OUT.mkdir(parents=True)
    dataset = kt.INPUT / "datasets" / "tester" / "gomi-meld-w3"
    dataset.mkdir(parents=True)
    (dataset / "run.json").write_text(json.dumps({"run": run, "base": "unsloth/gemma-4-E4B-it", "epochs": 1,
                                                  "rank": 16, "lr": 2e-4, "max_len": max_len, "quant": quant}))
    (dataset / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (data or rows(5))))
    hf_cache.mkdir(parents=True, exist_ok=True)
    kt.RUN = 3
    kt.result.clear()
    kt.result["run"] = 3
    calls.clear()
    return base


def main_output():
    out, cwd = io.StringIO(), os.getcwd()
    code = 0
    with contextlib.redirect_stdout(out):
        try:
            kt.main()
        except SystemExit as e:
            code = e.code
    os.chdir(cwd)
    return code, out.getvalue(), json.loads((kt.OUT / "result.json").read_text())


# --- a run that works: one example too long is left out, the rest trained, merged, converted, quantized
data = rows(4) + rows(1, reply_words=80)
setup(data=data)
code, log, result = main_output()
assert code == 0, log
assert result["run"] == 3 and result["examples"] == 4 and result["too_long"] == 1 and result["loss"] == 1.2346, result
assert result["gguf"] == "gomi-w3.Q4_K_M.gguf" and result["gpu"] == "Tesla T4" and result["gguf_bytes"] == 100, result
assert (kt.OUT / "gomi-w3.Q4_K_M.gguf").exists() and sorted(p.name for p in kt.OUT.iterdir()) == \
    ["gomi-w3.Q4_K_M.gguf", "result.json"]                                  # only these get downloaded
assert not (kt.SCRATCH / "merged").exists() and not (kt.SCRATCH / "model.F16.gguf").exists() and not hf_cache.exists()
assert "secretreply" not in log and "kaz0" not in log, log                   # no chat in the log
load = next(c[1] for c in calls if c[0] == "load")
assert load["load_in_4bit"] and load["max_seq_length"] == 60 and load["model_name"] == "unsloth/gemma-4-E4B-it"
peft = next(c[1] for c in calls if c[0] == "peft")
assert peft["r"] == 16 and not peft["finetune_vision_layers"]
trainer_args = next(c[1] for c in calls if c[0] == "trainer")
assert trainer_args["max_length"] == 60 and trainer_args["num_train_epochs"] == 1 and trainer_args["save_strategy"] == "no"
assert ("train", 4) in calls and "merged" in calls
pips = [c[1] for c in calls if c[0] == "run" and c[1][1:3] == ["-m", "pip"]]
assert len(pips) >= len(kt.PIP)

# --- last week's data still attached: stops before installing anything
setup(run=2)
code, log, result = main_output()
assert code == 0 and "run 2, not run 3" in result["error"] and not any(c[0] == "load" for c in calls if isinstance(c, tuple))

# --- a P100: Unsloth can't use it
setup()
GPU["line"] = "Tesla P100-PCIE-16GB, 6.0\n"
code, log, result = main_output()
assert code == 0 and "P100" in result["error"] and "T4" in result["error"], result
GPU["line"] = "Tesla T4, 7.5\n"

# --- prompts not masked: stops rather than train on the chat log
setup()
MASK["on"] = False
code, log, result = main_output()
assert code == 0 and "mask" in result["error"] and not any(c[0] == "train" for c in calls if isinstance(c, tuple))
MASK["on"] = True

# --- F16: no quantizing
setup(quant="F16")
code, log, result = main_output()
assert code == 0 and result["gguf"] == "gomi-w3.F16.gguf" and (kt.OUT / "gomi-w3.F16.gguf").exists()
assert not any(c[0] == "run" and "llama-quantize" in c[1][0] for c in calls if isinstance(c, tuple))

# --- nothing fits
setup(data=rows(2, reply_words=80))
code, log, result = main_output()
assert code == 0 and "no examples fit" in result["error"]

# --- a crash fail() didn't see coming: still a result.json, the traceback in the log
setup()
FastModel.from_pretrained = staticmethod(lambda **kw: (_ for _ in ()).throw(ImportError("torchcodec mismatch")))
code, log, result = main_output()
assert code == 0 and result["error"].startswith("ImportError: torchcodec mismatch") and result["run"] == 3, result
print("KAGGLE TRAIN TESTS PASSED")
