# Conversation review — 2026-11-13, corrections 2026-11-14

This review records reproducible context-handling bugs and fixes, plus unresolved model/training-quality questions. The
November 14 follow-up corrects async handoffs and provenance that the earlier 31-suite pass missed.
The tests exercise controlled async events and synthetic logs, with no live inference. Passing
them demonstrates scheduling/data invariants, not whether a model understands a conversation or
can converse as well as Doumi. The historical model samples below were not rerun in this session.

The earlier November 14 review reported all 33 suites passing. That result missed the three bugs
below: a canned correct batch answer did not inspect its prompt, and image identity/persistence races
were untested. This follow-up reproduced each failure against a source snapshot taken before these
additional fixes, preserving the existing uncommitted work. Fake localhost services require sandbox
escalation; all test input and services remain synthetic. Earlier regressions include
vision during a reaction await, reaction-only corrections, slow images during drafts, request batches,
speaker-specific memories, failed/empty/capped generation, failed/uncertain delivery and log writes,
harvest-to-render addressing/targets, bot-interposed complaints, expanded diary budgets and evidence,
generated media separation, optional few-shot provenance, and the comparison matrix via a fake service.

Session 1 validation: `tests/run_all.sh` passed **all 35 suites** on its temporary
repository copy (the previous 33 plus image-identity and observation-log suites). `git diff --check`
passed. The final full run was serial to avoid the suites' shared fake-server ports. An earlier
attempt without localhost permission failed at socket creation; an overlapping test run hit a port
collision. Neither used real services, and the final authorized isolated run completed successfully.

## Checker isolation follow-up — November 14

Inspection confirmed that importing `tools/chat_check.py` imported `finetuning.weekly`, which
imported `vision_check` and loaded repository `.env`. The earlier synthetic reproduction loaded an
unrelated sentinel and selected the synthetic `.env` endpoint. Explicit decoding settings stayed
unchanged; no credential disclosure was demonstrated. The correction defers `vision_check` until
`weekly.sees()` actually needs it. Weekly's CLI still loads its configuration in `main()`, and the
standalone vision-check CLI keeps its documented `.env` behavior.

The checker selects **`--url` → process `OLLAMA_URL` → `http://localhost:11434/api/chat`**, without
loading `.env`. It freezes that endpoint for inventory and every generation, and records its normalized
chat URL and selection source. URLs containing user credentials, query parameters or fragments are
rejected before requests or report creation, with an error that does not echo the supplied URL.
This prevents such credentials from entering endpoint metadata or URL-bearing request errors.

`tests/test_chat_check_isolation.py` constructs a source-only repository under `/tmp`, writes a
synthetic `.env`, then starts fresh interpreters with a fake HTTP transport. An audit hook checks
that neither checker nor weekly import opens `.env`; an unrelated sentinel and inherited decoding
settings independently check environment effects. Against the pre-fix checker/weekly snapshot the
regression failed with **`import read synthetic .env`**. Endpoint probes cover default, inherited and
explicit selection without opening sockets. Separate fresh processes verify all four vision CLI
colours and both weekly vision colours using synthetic configuration.

Revalidation against Session 1 found and corrected a checker prompt mismatch: direct questions now
appear in the selected-request block even when they are the newest message. Raw author words still
determine shaping; displayed quotes and descriptions remain context. Tests assert the exact newest
speaker/source and selected requests, including multiple speakers and a transcript ending in Gomi's
previous batch answer. The six comparison scenarios and persona/sampling settings were retained.

Reports retain exact prompts and hashes, fixtures, explicit seeds/date/options, requested and returned
model identities, available installed digests, raw answers and returned thinking, and sentence/emoji
previews. Requested thinking is separate from observed thinking text; separate reasoning-token counts
remain unavailable. `elapsed_seconds` measures the chat HTTP request and JSON decoding, including
model loading; Ollama's reported `load_seconds` and `total_seconds` are separate, nullable fields.
Missing timings are not zero, and skipped requests have no elapsed measurement. These measurements
are not complete end-to-end runtime latency.

Fake-service tests assert the full 54-request matrix and equality of prompts/options across models,
explicit overrides, endpoint pinning, identity mismatches, missing timings, absent/inline/separate
thinking, empty answers, HTTP errors, invalid JSON and unusable response schemas. Missing models or
unavailable inventory produce a nonzero result and retained errors without generation for unidentified
models. No pull is attempted; existing reports are refused before network access. Passing canned
responses demonstrate plumbing and prompt construction, not model understanding.

Session 2 validation: `tests/run_all.sh` passed **all 36 suites**, serially on its temporary repository
copy, including checker isolation, matrix/failures, weekly and vision-check callers. `git diff --check`
passed. Fake localhost services used the test runner's authorized sandbox escalation; the fresh-process
isolation probes used an in-process fake transport. No live service or model was contacted. All
pre-existing runtime source/test changes outside this checker work match the session-start snapshot.

Checker readiness means readiness for the separately authorized synthetic model experiment below.
It does not establish deployment readiness or resolve Session 1's runtime limits: historical
misordered logs remain unrepaired; crash/write failures can leave incomplete image context or audit
records; diary timestamp cursors retain equal-time split and wall-clock rollback edge cases; and
freshness cannot retract an in-flight Discord send. Model quality and actual runtime operation remain
untested here. The checker does not simulate room reading, Discord scheduling, delivery, retries or
complete runtime cleanup, including required-answer withholding and name/slur filtering.

## Additional confirmed failures — November 14

| Failing reproduction | Correction and discriminating evidence |
|---|---|
| Pause an initial generation, then queue four direct questions. The fourth question is marked answered while its prompt labels Gomi's previous three-part answer as Mira's newest message. | Every selected source is an explicit request, including one whose observation number equals the current revision. The newest observed participant and their display context stay separate from the transcript tail. The bounded-batch test asserts the exact newest line and selected sources for **all three generations**, not just the canned responses or delivery IDs. |
| Two Mira images have identical captions; the older description completes first, including after its original history entry has been evicted. The newer image acquires the older description. | Each displayed observation retains its source; enrichment replaces that exact observation by identity, updates its queued request, and never restores an evicted line. Both completion orders are tested with and without eviction, refetched message objects, Gomi posts and another bot interposed. Assertions bind each description to its source ID, pending request, saved record, and the **newest-message instruction**. |
| An older slow image arrives before Sol's newer unsolicited question. Runtime answers Sol, but saved history orders Sol before Mira's image and rendering teaches the answer as addressed to Mira. | Save raw observations synchronously before vision yields. Append display-only context updates by Discord message ID; reads fold updates into the original record without changing its arrival time or raw words. The runtime regression reinstantiates the log, reloads history, harvests positive synthetic feedback and renders the example, checking Mira → Sol → Gomi and Sol as the actual newest source with `answered_requests=[]`. |

`tests/test_image_identity.py` reproduces the swapped description (including eviction) and reversed
disk order against the pre-fix snapshot, then passes with the corrections. The strengthened
`bounded_batches` and pending-speaker tests also failed before correction. Pending questions from
multiple people retain distinct facts, learned observations and nicknames even after all their
history lines are evicted or a display-name alias overwrites the handle lookup.

`tests/test_observation_log.py` covers completion across midnight, unchanged original log bytes,
arrival-time cutoffs, identical captions, orphan context events, deletion, legacy plain records,
stable ordering for equal timestamps, and harvest/render identities. A diary run started while an
image is pending now waits for that existing vision future before reading the channel. Its frozen
arrival cutoff excludes posts that arrive while it waits; enrichment is persisted before the future
is released. The regression checks the exact diary transcript, cursor and unread IDs across two
passes. Without the wait it fails because the cursor can permanently pass the unfinished picture.

The final diff review also caught and corrected an intermediate rendering regression: human voice
examples whose previous speaker was Gomi must still target that true transcript tail. Skipping a
prior Gomi answer is restricted to explicit required batches, with a voice-harvest-to-render test.
The persona, substantive three-sentence allowance and necessary-clarification rule remain intact;
no new retry loop, background task, duplicated identity map or automatic delivery resend was added.

Remaining limits: old records already saved in the wrong completion order are not repaired, and
legacy examples lacking trustworthy provenance keep their existing compatibility/skip rules. A crash
before enrichment leaves the raw observation available without an invented description. A failed
context write can likewise leave display context incomplete. Diary cursors remain timestamps: the
pre-existing equal-time split-part failure and wall-clock rollback edge cases were not redesigned.
The deterministic tests cover the reported arrival/vision cursor race, not those clock anomalies.

## Follow-up failures reproduced and corrected

| Reproduction | Correction and demonstrated boundary |
|---|---|
| A picture question arrives while `chimes_in` awaits a Discord reaction. Generation starts before vision finishes. | Recheck pending descriptions and the observation revision after every room-read/reaction await, immediately before freezing the prompt. |
| An unsolicited chess draft survives a short correction or a newly arriving slow image. | Every observed message changes freshness, including posts that schedule only a reaction or are still awaiting vision. Required answers retain their source instead of being discarded. |
| Three pending questions followed by short pizza chatter lose the third answer. | Shape uses the raw requests being answered; multiple requests use the normal three-sentence policy. Batches contain at most three requests; later requests remain queued. Genuine quick exchanges keep their short shape. |
| Generation is empty/failed, delivery fails, or cleanup removes part of a required answer. | Requests stay pending through generation and delivery. A terminal `reply_failure` event records request IDs/reason separately from successful replies. No automatic resend after delivery failure, including ambiguous timeouts. |
| A quoted Gomi mention becomes raw addressing, or a delayed arithmetic reply is taught as answering newer pizza chatter. | Harvested `history_meta` keeps raw text/addressing beside display context; `answered_requests` identifies actual sources. Rendering uses these fields and skips missing/out-of-window targets. |
| Three other-bot posts hide a human complaint. | The three-message window counts nonempty, eligible human follow-ups; bot posts remain visible context. |
| Diary parts fit their raw-text budget but exceed it after quote expansion; another speaker's words validate a personal note. | Budget the exact displayed transcript and validate each note against its named human's raw words. Oversized single display lines are capped on copies and cannot supply note evidence. |
| The checker treats quoted context as author text when selecting a reply shape. | Runtime and checker share `this_time(..., pending_raw=...)`; displayed context stays in the prompt while raw words determine shape. |

Synthetic reproduction against the old diary functions produced a 30,598-character transcript under
a nominal 1,000-character budget; corrected batching stayed within the limit. The old pooled evidence
check accepted a note about Sol using only Mira's words; per-speaker checking rejects it.

New human log records keep normalized author words in `text`, with `text_provenance="author"` and
explicit `addressed`; quotes, embed titles and generated descriptions live only in `context`.
Generated context cannot endorse a reply, become a human voice target, or validate personal memory.
Legacy plain text remains usable when it has no quote/media markers; ambiguous legacy text is skipped
rather than stripped into invented author words. Legacy earned examples lacking answer provenance
are excluded from new datasets and runtime example loading; existing files and weights are not rewritten.
Optional few-shot examples label retained delayed sources and skip sources lost by their compact
three-line display, while the saved baseline still has zero few-shot examples.

Failure handling is deliberately bounded: the existing content/thinking retries remain, but failures
do not create a new retry loop. Truncated required drafts are withheld. Existing unknown-name/slur
filter behavior can still post a filtered response, with empty answered-request provenance and a
separate failure event. A human must ask again after terminal failure. A timeout can mean Discord
accepted the message; avoiding an automatic duplicate takes precedence over retrying that uncertainty.
If log persistence itself fails, the terminal outcome still prevents automatic resends; only the
operational warning may remain, so the saved audit trail can be incomplete after a disk failure.

## What was going wrong

| Weak point | Evidence and effect | Change |
|---|---|---|
| Missing conversations | Gomi discarded every other bot's post. Humans replying to Doumi could appear to be answering nothing. | Other bots are visible context, without triggering replies, commands, or training targets. |
| Missing Discord reply targets | The reply generator saw message text but not the quoted post. | Bounded quotes enter context; unavailable quotes are labeled. Raw author text stays separate for learning. |
| Incorrect target during bursts | An earlier mention was carried forward as a boolean, then applied to a different latest speaker. | Preserve actual pending requests and their speakers' notes. |
| Replies arriving after the topic moved | Old unsolicited drafts were posted, followed by another reply. Retries could silently change their target. | Recheck stale room reads, discard superseded unsolicited drafts, freeze retries, and link delayed required answers to their actual source posts. |
| Pictures not ready | Another turn could consume a picture question before its description arrived. | Wait for descriptions already in progress before answering that batch. |
| Clarification forbidden | A recent question could produce a blanket instruction not to ask another. | Needed clarifications are exempt; only optional conversation-extending questions remain discouraged. |
| Pressure to add filler | The prompt asked for a plain answer and then extra attitude or a take. | Stop when the answer is complete; don't invent terms, shared history, or a connection to the previous topic. |
| Bad feedback treated as success | Any reaction, reply, or later mention of Gomi could endorse her answer. | Require a positive human reaction or laugh, reject recognizable complaints, and exclude bot endorsements. |

The prior saved-data audit reported unreliable approval signals in training material. The local first run used 461 examples, including
60 harvested Gomi replies. Of the then-saved 80 examples, 62 were accepted merely because someone
subsequently named Gomi, and 11 through angry reactions. Complaints about verbosity and repetition
were among the accepted examples. These are engagement signals, not reliable approval.

These observations do not establish which learned behaviors came from those examples, or explain
every W1 failure. Existing earned-example files and model weights have not been modified. The new
rules affect future harvesting/rendering; they cannot untrain `gomi-w1`. Positive reactions and laughter
remain imperfect heuristics, so reviewing data before another training run still matters.

## What Doumi does differently

Doumi preserves [reply quotes and other bots' messages](https://github.com/zurgace/entertainerllm/blob/main/src/entertainerllm/discord_bot/bot.py#L2685),
can identify an unknown term through its [room reader](https://github.com/zurgace/entertainerllm/blob/main/src/entertainerllm/chat/room.py),
and explicitly permits [clarifying questions](https://github.com/zurgace/entertainerllm/blob/main/src/entertainerllm/chat/shape.py).
Gomi now preserves the missing context and permits clarification without adding another model call
or making her chime in more frequently. Her existing participation thresholds are unchanged.

Doumi's [configured model](https://github.com/zurgace/entertainerllm/blob/main/config/models.yaml) is
Gemma 4 **26B-A4B**, approximately 18 GB at its configured quantization. Gomi's **E4B** is a different
model. Similar active-parameter counts do not mean equivalent capacity or memory requirements;
Doumi's configured model is not a same-size replacement for the RTX 2070.

## Historical model checks on this RTX 2070 (not rerun November 14)

Six synthetic conversations covered topic changes, an ambiguous reference, an older Discord reply,
"you" addressed to someone else, a pending question during a burst, and a simple answer. The models
received the revised prompt; `gomi-w1` and `gomi-bolt` were tested with thinking requested both off and
on, and installed stock `gemma4:e4b` with it on. These are small, single-sample checks, not a benchmark
or proof of a universal ranking. The checker bypasses room-reading decisions and Discord delivery.
Those six saved samples raised concerns about W1 and justified testing stock Gemma and Bolt; they
established neither a ranking nor training contamination as the cause. Stock and Bolt also made
mistakes. Nothing in the isolation tests adds model-quality evidence.

| Model, thinking requested | Median reply words | Median elapsed minus reported model load | Observed issues |
|---|---:|---:|---|
| `gomi-w1`, on | 19 | 1.43 s | Invented knowledge of an unspecified movie; took someone else's praise personally; added irrelevant insults. |
| `gomi-bolt`, on | 6 | 9.64 s | Asked the right clarification and answered pending arithmetic, but some replies were unhelpfully terse and it praised an unseen drawing. |
| `gemma4:e4b`, on | 13 | 10.59 s | Asked the right clarification and gave a usable plain answer, but still added unnecessary jokes and praised the unseen drawing. |

Thinking off was not an automatic improvement: Bolt answered the pending arithmetic incorrectly in
that sample. In a separate fixed-seed diagnostic, replacing only the long system persona with a
127-word version did not repair `gomi-w1`. That diagnostic reported no thinking text from `gomi-w1`
despite `think=true`, while Bolt did return thinking. Requested thinking and actual reasoning behavior
must be distinguished.

Ollama reported **100% GPU at context 8192** for Bolt (3.6 GB resident) and stock Gemma (3.2 GB
resident). Installed file sizes were roughly 5.1 GB, 5.3 GB, and 9.6 GB for Bolt, W1, and stock
respectively: file size and resident memory are different measurements.

Bolt is a relevant candidate because [NVIDIA describes its training](https://research.nvidia.com/labs/nemotron/Nemotron-3.5-Bolt-E4B-4GB/)
as targeting conversational grounding and interactive personas, and the existing
[Unsloth quantization](https://huggingface.co/unsloth/NVIDIA-Nemotron-3.5-Bolt-E4B-GGUF/tree/main)
fits here. This test does not justify calling it an unconditional upgrade. A different-family candidate
is [Qwen3.5 4B](https://ollama.com/library/qwen3.5:4b); it was not downloaded or tested.

## Recommendation and limits

Review stock Gemma and Bolt as alternatives to the current fine-tune before investing in more
training. Both showed better clarification in these samples; neither demonstrated Doumi-level
conversation quality. Keep the first comparison on the corrected code, without changing personality,
model, history length and thinking mode all at once. The configured model was left unchanged.

Before retraining, curate the existing earned examples and add good examples of topic changes,
uncertainty, natural follow-up questions and plain answers. Reintroducing the old earned pool through
an older builder or bypassing the provenance checks would retain unreliable targets despite the
corrected future-harvesting rule.

For the later reproducible comparison, from `/home/main/gomihyu`, choose a new report path and run:

```sh
venv/bin/python tools/chat_check.py gomi-w1 gemma4:e4b gomi-bolt --url http://localhost:11434/api/chat --seeds 17 29 43 --think --num-ctx 8192 --num-predict -1 --temperature 0.8 --top-p 0.9 --top-k 40 --repeat-penalty 1.1 --at 2026-11-14T12:00:00-05:00 --output /tmp/gomi-comparison-thinking-isolation-fixed.md
```

This is six scenarios × three fixed seeds × three models (54 generations), all with the same persona,
fixed synthetic date, no few-shot examples or private memory, and explicit sampling settings. To
compare requested thinking off, repeat with `--no-think --num-predict 200` and a different output path.
The command deliberately selects localhost rather than inheriting an endpoint; change `--url` only
if the intended Ollama service is elsewhere. The checker also fixes `min_p=0`, `mirostat=0`,
`repeat_last_n=64`, `presence_penalty=0` and `frequency_penalty=0` identically in every request.
The three models must already be installed: the checker never pulls them. It reads installed digests
and records returned model identity, exact prompts/settings, raw answers/thinking, observed thinking
word/character counts, sentence/emoji previews, available load time and request elapsed time. Separate thinking token
counts are unavailable, rather than inferred from total generated tokens. Reports refuse overwrites.

The checker tests generation only; it does not test Discord scheduling, room-reading decisions,
delivery, retries, or full runtime cleanup. Its previews expose shaping losses; a preview is not proof
the runtime would deliver a clipped required answer. Judge grounding, uncertainty, useful questions,
substance and latency across samples; this small matrix cannot establish a general model ranking.

Diary character budgets cover the rendered transcript, not fixed prompt overhead or tokenization.
Evidence provenance verifies whose words a quote came from; it does not prove a note's semantic
entailment. Freshness checks end when Discord sending begins; they cannot retract an in-flight send.
The fake-service regression suite checks these code paths without testing model understanding.

The saved baseline at that review was `gomi-w1`, thinking enabled, history 30, zero few-shot examples,
`VISION_MODEL=gemma4:e4b`, empty `TASK_MODEL` (inherits W1), context 8192 on the RTX 2070 (8 GB).
Those earlier sessions made no live comparison, bot restart, deployment, retraining, commit, push,
model/configuration change, or edit to saved data. Their fixes were left uncommitted for the code
review recorded below. Actual model relevance, personality and latency still need live evaluation.

## Commit review — November 14

Reviewed the combined changes against the friend-first persona, required replies, bounded reply
shape, local memory, and gradual server-voice training described in `CLAUDE.md`. Additional fixes:

- Mark required replies altered by name/slur filtering separately, so positive reactions cannot promote an
  incomplete answer into training.
- Preserve Gomi's question as the newest transcript line when a human voice sample answers it with
  a Discord reply link; queued Gomi answer batches retain their separate source selection.
- Suppress pings for every requester in a batched reply, matching the existing single-request rule.
- Continue replies from in-memory context when saving an observation or image description fails;
  log the persistence failure without leaving a required request stranded.
- Cancel queued questions when muted, recording one terminal outcome even if unmuted before
  generation or vision completes. Unrelated later chatter cannot revive those requests.
- Identify historical training totals as incomparable with today's provenance-filtered pool, instead
  of reporting a misleading new-example count. Review data before the existing `build --force` path.
- Ignore the local `.githubkey` credential file and correct the optional Bolt recipe's misleading
  stock-model replacement instructions.

Validation: all **36 suites** passed in a final serial `tests/run_all.sh` run on the temporary
repository copy, with fake services only. Added regressions reproduced the linked-voice target,
batched ping, observation-write, mute-cancellation, and historical-count failures; focused checks
also cover excluding filtered required answers from harvest. `git diff --check` passed.

The code review does not choose a replacement model or curate saved chat/training data. Compare
stock Gemma and Bolt in both thinking modes before a switch; review old examples before retraining.
Historical log repair and diary cursor behavior across equal timestamps or a backward clock remain
separate work. No live bot restart, model switch, retraining, or push is part of this commit review.
