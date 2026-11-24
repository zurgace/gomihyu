import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]
import copy, hashlib, io, json, os, re, sys, threading
from contextlib import redirect_stderr
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, REPO + "/tools")
# Deliberately conflicting environment settings must not silently vary a comparison.
os.environ.update(OLLAMA_MODEL="fake-current", OLLAMA_THINK="false", OLLAMA_NUM_CTX="4096",
                  MAX_REPLY_TOKENS="123")
import chat_check
from gomi.shape import this_time

requests, gets = [], []
mode = {"content": "First full sentence. Second full sentence. Third full sentence. Fourth full sentence.",
        "thinking": "Check the current speaker first.", "fail": False, "tags": "ok", "chat": "ok"}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        gets.append(self.path)
        assert self.path == "/api/tags"
        if mode.get("change_url"):
            os.environ["OLLAMA_URL"] = "http://127.0.0.1:1/api/chat"
        if mode["tags"] == "http":
            self.send_response(503); self.end_headers(); return
        body = json.dumps({"models": [{"name": model + ":latest" if ":" not in model else model,
                                      "digest": "digest-" + model} for model in
                                     ["fake-a", "fake-b", *chat_check.MODELS]]}).encode()
        if mode["tags"] == "json": body = b"not JSON"
        if mode["tags"] == "schema": body = b'{"models": null}'
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        assert self.path == "/api/chat"
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append(payload)
        if mode["fail"] or payload["model"] == mode.get("fail_model"):
            self.send_response(503); self.end_headers(); return
        response = {"model": mode.get("returned_model", payload["model"]),
                    "message": {"content": mode["content"], "thinking": mode["thinking"]},
                    "done_reason": "stop", "prompt_eval_count": 70, "eval_count": 45}
        if not mode.get("no_durations"):
            response.update(total_duration=400000000, load_duration=100000000)
        if mode["chat"] == "schema": response["message"] = []
        body = b"not JSON" if mode["chat"] == "json" else json.dumps(response).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *args): pass


def records(path):
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", path.read_text(), re.DOTALL)]


# Regression: quotes previously turned four raw words into a long-post shape.
now = datetime.fromisoformat(chat_check.FIXTURE_TIME)
praise = chat_check.CASES[3]
_, praise_shape = chat_check.prompt(praise, now)
assert praise_shape == this_time("you nailed the lighting", [], 6)
assert praise_shape["one_line"]
assert not this_time(praise["history"][-1]["context"], [], 6)["one_line"]
assert "reply to Sol" in chat_check.prompt(praise, now)[0][1]["content"]
# A pending question, rather than unrelated pizza chatter, controls the policy.
_, pending_shape = chat_check.prompt(chat_check.CASES[4], now)
assert not pending_shape["one_line"]
burst = copy.deepcopy(chat_check.CASES[4])
burst["history"].insert(1, {"author": "Sol", "text": "gomi hi"})
burst["pending"] = [0, 1]
assert not chat_check.prompt(burst, now)[1]["one_line"]

# Inspect actual targets and labels; canned answers cannot reveal a wrong speaker.
for case in chat_check.CASES:
    content = chat_check.prompt(case, now)[0][1]["content"]
    newest = case["history"][-1]
    selected = case.get("pending", [-1] if case["mentioned"] else [])
    if selected:
        assert f'The newest message, from {newest["author"]}:\n{chat_check.displayed(newest)}\n' in content
        sources = "\n".join(chat_check.displayed(case["history"][i]) for i in selected)
        assert f"These messages still need your reply:\n{sources}\n" in content
        assert "You are replying to the newest message" not in content
        assert "respond to that directly" not in content
        if case["mentioned"]: assert "Answer the selected requests above" in content
    else:
        assert f'You are replying to the newest message, from {newest["author"]}:\n' in content
        assert "These messages still need your reply" not in content

later_batch = {"history": [{"author": "Mira", "text": "gomi what is two plus two?"},
                            {"author": "Sol", "text": "gomi what is five plus five?"},
                            {"author": chat_check.BOT_NAME, "text": "Two plus two is four."}],
               "mentioned": True, "pending": [1], "newest": 1}
later_instruction = chat_check.prompt(later_batch, now)[0][1]["content"].split("Above is the recent chat log", 1)[1]
assert "The newest message, from Sol:\nSol: gomi what is five plus five?\n" in later_instruction
assert "These messages still need your reply:\nSol: gomi what is five plus five?\n" in later_instruction
assert "\nGomihyu:" not in later_instruction
description = {"history": [{"author": "Mira", "text": "gomi hi", "context": "gomi hi [image: " + "colourful " * 30 + "]"}],
               "mentioned": True}
description_messages, description_shape = chat_check.prompt(description, now)
assert description_shape == this_time("gomi hi", [], 6, pending_raw=["gomi hi"])
assert description_shape["one_line"] and "[image:" in description_messages[1]["content"]

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
endpoint = f"http://127.0.0.1:{server.server_port}/api/chat"
os.environ["OLLAMA_URL"] = endpoint
try:
    report = Path(TMP) / "comparison.md"
    assert chat_check.main(["fake-a", "fake-b", "--no-think", "--output", str(report)]) == 0
    assert len(requests) == 2 * 3 * len(chat_check.CASES) and gets == ["/api/tags"]
    for index, (first, second) in enumerate(zip(requests[::2], requests[1::2])):
        assert first["messages"] == second["messages"]
        assert (first["model"], second["model"]) == ("fake-a", "fake-b")
        assert first["options"] == second["options"] == {
            "num_ctx": 8192, "num_predict": 200, "temperature": 0.8, "top_p": 0.9, "top_k": 40,
            "min_p": 0.0, "mirostat": 0, "repeat_penalty": 1.1, "repeat_last_n": 64,
            "presence_penalty": 0.0, "frequency_penalty": 0.0, "seed": chat_check.SEEDS[index % 3]}
        assert first["think"] is False
    result = records(report)
    responses = [row for row in result if "raw_content" in row]
    assert len(responses) == len(requests)
    assert all(row["raw_content"] == mode["content"] for row in responses)  # never hide shaping losses
    assert responses[0]["shaped_preview"] == "First full sentence. Second full sentence."
    pending_response = responses[4 * 2 * len(chat_check.SEEDS)]
    assert pending_response["shaped_preview"] == "First full sentence. Second full sentence. Third full sentence."
    assert all(row["thinking_present"] and row["thinking_words"] == 5 and row["thinking_chars"] == 32
               and row["thinking_token_count"] is None for row in responses)
    assert responses[0]["requested_model"] == responses[0]["returned_model"] == "fake-a"
    assert responses[0]["installed_digest"] == "digest-fake-a"
    assert responses[0]["load_seconds"] == 0.1 and responses[0]["total_seconds"] == 0.4
    assert responses[0]["prompt_eval_count"] == 70 and responses[0]["eval_count"] == 45
    assert all(row["elapsed_seconds"] >= 0 for row in responses)
    text = report.read_text()
    assert "does not test Discord scheduling or room-reading decisions" in text
    assert result[0]["fixture_time"] == chat_check.FIXTURE_TIME
    assert result[0]["endpoint"] == endpoint and result[0]["endpoint_source"] == "OLLAMA_URL"
    assert result[0]["few_shot_examples"] == 0 and result[0]["max_history"] == 30
    older = next(row for row in result if row.get("fixture", {}).get("name") == chat_check.CASES[2]["name"])
    assert "reply to Mira" in older["messages"][1]["content"]
    pending = next(row for row in result if row.get("fixture", {}).get("pending"))
    assert "Mira: gomi what's 6 times 7?" in pending["messages"][1]["content"]
    assert "Sol: my pizza just arrived" in pending["messages"][1]["content"]
    assert not pending["shape"]["one_line"]
    fixtures = [row for row in result if "fixture" in row]
    for index, fixture in enumerate(fixtures):
        expected_hash = hashlib.sha256(json.dumps(fixture["messages"], ensure_ascii=False,
                                                  sort_keys=True).encode()).hexdigest()
        assert fixture["prompt_sha256"] == expected_hash
        assert all(request["messages"] == fixture["messages"] for request in requests[index * 6:(index + 1) * 6])

    # The default run is exactly six scenarios x three fixed seeds x three candidates.
    requests.clear()
    thinking_report = Path(TMP) / "thinking.md"
    assert chat_check.main(["--output", str(thinking_report)]) == 0
    assert len(requests) == 54
    assert {r["model"] for r in requests} == set(chat_check.MODELS)
    assert {r["options"]["seed"] for r in requests} == set(chat_check.SEEDS)
    assert all(r["think"] is True and r["options"]["num_predict"] == -1 for r in requests)
    for case_index, case in enumerate(chat_check.CASES):
        matrix = requests[case_index * 9:(case_index + 1) * 9]
        assert [(r["options"]["seed"], r["model"]) for r in matrix] == [
            (seed, model) for seed in chat_check.SEEDS for model in chat_check.MODELS]
        assert all(r["messages"] == chat_check.prompt(case, now)[0] for r in matrix)
        assert all(r["options"] == matrix[0]["options"] for r in matrix[:3])
    assert "gomi.bot" not in sys.modules  # no Discord client, data stores or bot startup

    # Missing and inline-only thinking are measured from actual returned text.
    assert not chat_check.response_details({"message": {"content": "An answer."}})["thinking_present"]
    inline = chat_check.response_details({"message": {"content": "<think>Check this first.</think>Answer here."}})
    assert inline["raw_content"].startswith("<think>") and inline["reply"] == "Answer here."
    assert inline["thinking_present"] and inline["thinking_words"] == 3
    combined = chat_check.response_details({"message": {"content": "<think>Inline words.</think>Answer.",
                                                       "thinking": "Separate words."}})
    assert combined["raw_thinking"] == "Separate words." and combined["thinking_words"] == 4
    assert combined["thinking_token_count"] is None

    # Explicit settings override defaults identically, including the seed, rather than model Modelfiles.
    requests.clear()
    override = Path(TMP) / "override.md"
    assert chat_check.main(["fake-a", "--seeds", "8", "--num-ctx", "2048", "--num-predict", "99",
                            "--temperature", "0.2", "--at", "2025-01-02T03:04:05-05:00",
                            "--output", str(override)]) == 0
    assert len(requests) == 6
    assert all(r["options"]["seed"] == 8 and r["options"]["num_ctx"] == 2048 and
               r["options"]["num_predict"] == 99 and r["options"]["temperature"] == 0.2 for r in requests)
    assert records(override)[0]["fixture_time"] == "2025-01-02T03:04:05-05:00"

    # A CLI endpoint beats the inherited URL and stays fixed even if the environment changes mid-run.
    requests.clear(); gets.clear()
    os.environ["OLLAMA_URL"] = "http://127.0.0.1:1/api/chat"
    mode["change_url"] = True
    explicit = Path(TMP) / "explicit-endpoint.md"
    assert chat_check.main(["fake-a", "--seeds", "17", "--url", endpoint.removesuffix("/api/chat"),
                            "--output", str(explicit)]) == 0
    assert len(requests) == 6 and gets == ["/api/tags"]
    assert records(explicit)[0]["endpoint"] == endpoint
    assert records(explicit)[0]["endpoint_source"] == "--url"
    mode["change_url"] = False
    os.environ["OLLAMA_URL"] = endpoint

    # Refuse overwrites and credential-bearing endpoints before making any request or report.
    saved = explicit.read_bytes()
    requests.clear(); gets.clear()
    with redirect_stderr(io.StringIO()):
        try:
            chat_check.main(["--output", str(explicit)])
        except SystemExit as error:
            assert error.code == 2
        else:
            raise AssertionError("existing report was accepted")
    assert explicit.read_bytes() == saved and not requests and not gets
    for suffix in ("test-user:test-pass@localhost:1/api/chat", "localhost:1/api/chat?token=test-pass",
                   "localhost:1/api/chat#test-pass"):
        unsafe = Path(TMP) / "unsafe-endpoint.md"
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            try:
                chat_check.main(["--url", "http://" + suffix, "--output", str(unsafe)])
            except SystemExit as error:
                assert error.code == 2
            else:
                raise AssertionError("unsafe endpoint was accepted")
        assert "test-user" not in stderr.getvalue() and "test-pass" not in stderr.getvalue()
        assert not unsafe.exists() and not requests and not gets

    # Identity fields are observations, and unavailable timing stays unavailable rather than zero.
    mode.update(no_durations=True, returned_model="fake-returned:tag", thinking="")
    observed = Path(TMP) / "observed.md"
    assert chat_check.main(["fake-a", "--seeds", "17", "--output", str(observed)]) == 0
    observations = [row for row in records(observed) if "raw_content" in row]
    assert all(row["requested_model"] == "fake-a" and row["returned_model"] == "fake-returned:tag"
               and row["installed_digest"] == "digest-fake-a" for row in observations)
    assert all(row["load_seconds"] is None and row["total_seconds"] is None for row in observations)
    assert all(row["think_requested"] is True and not row["thinking_present"] for row in observations)
    mode.pop("no_durations"); mode.pop("returned_model"); mode["thinking"] = "Check the current speaker first."

    requests.clear(); gets.clear()
    missing = Path(TMP) / "missing.md"
    assert chat_check.main(["fake-missing", "fake-a", "--seeds", "17", "--output", str(missing)]) == 1
    assert len(requests) == 6 and all(r["model"] == "fake-a" for r in requests)
    assert len([row for row in records(missing) if row.get("requested_model") == "fake-missing" and "error" in row]) == 6
    assert gets == ["/api/tags"]  # no pull or other recovery calls

    # Discovery failures must not silently proceed to generation without model inventory.
    for failure in ("http", "json", "schema"):
        requests.clear(); gets.clear(); mode["tags"] = failure
        path = Path(TMP) / f"tags-{failure}.md"
        assert chat_check.main(["fake-a", "--seeds", "17", "--output", str(path)]) == 1
        assert records(path)[0]["identity_error"] and not requests and gets == ["/api/tags"]
    mode["tags"] = "ok"

    # A failed sample is retained and the rest of the synthetic matrix is still attempted.
    for failure in ("json", "schema"):
        requests.clear(); mode["chat"] = failure
        path = Path(TMP) / f"chat-{failure}.md"
        assert chat_check.main(["fake-a", "--seeds", "17", "--output", str(path)]) == 1
        errors = [row for row in records(path) if "error" in row]
        assert len(errors) == len(requests) == 6 and all(row["requested_model"] == "fake-a" for row in errors)
    mode["chat"] = "ok"

    requests.clear(); mode["fail_model"] = "fake-a"
    partial = Path(TMP) / "partial-failure.md"
    assert chat_check.main(["fake-a", "fake-b", "--seeds", "17", "--output", str(partial)]) == 1
    partial_records = records(partial)
    errors = [row for row in partial_records if "error" in row]
    successes = [row for row in partial_records if "raw_content" in row]
    assert len(requests) == 12 and len(errors) == len(successes) == 6
    assert all(row["requested_model"] == "fake-a" for row in errors)
    assert all(row["requested_model"] == "fake-b" for row in successes)
    mode.pop("fail_model")

    mode["content"] = ""
    empty = Path(TMP) / "empty.md"
    assert chat_check.main(["fake-a", "--seeds", "17", "--output", str(empty)]) == 1
    assert all(row["reply"] == "" for row in records(empty) if "raw_content" in row)
    mode["fail"] = True
    failed = Path(TMP) / "failed.md"
    assert chat_check.main(["fake-a", "--seeds", "17", "--output", str(failed)]) == 1
    assert len([row for row in records(failed) if "error" in row]) == 6
finally:
    server.shutdown(); server.server_close(); thread.join()
print("CHAT CHECK TESTS PASSED")
