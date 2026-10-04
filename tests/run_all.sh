#!/bin/bash
# Runs the test suites against a throwaway copy of the repo: your .env, chat logs, people.json and
# training data are never read or touched. Ollama, Discord and Kaggle are all faked, so nothing but
# the bot's requirements is needed. Each suite gets its own temp folder for the bot's files.
#
#   tests/run_all.sh                       every suite
#   tests/run_all.sh test_reactions.py     just these
#   PYTHON=python3 tests/run_all.sh        another interpreter (default: venv/bin/python)
#   GOMI_AVATAR_PNG=~/gomi.png tests/run_all.sh test_avatar.py   also check her real avatar
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/venv/bin/python}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/repo"
(cd "$ROOT" && git ls-files -co --exclude-standard -z | xargs -0 cp --parents -t "$WORK/repo")
export GOMI_REPO="$WORK/repo"
cd "$WORK"
fail=0
for t in ${@:-$(cd "$GOMI_REPO/tests" && ls test_*.py)}; do
  T="$WORK/tmp"; rm -rf "$T"; mkdir -p "$T"
  if GOMI_TMP="$T" CHAT_LOG_DIR="$T/chatlogs" DIARY_FILE="$T/diary.json" EARNED_FILE="$T/earned.jsonl" \
      timeout 300 "$PY" "$GOMI_REPO/tests/$t" >"$WORK/$t.log" 2>&1; then
    echo "PASS $t"
  else
    echo "FAIL $t"; tail -8 "$WORK/$t.log"; fail=1
  fi
done
exit $fail
