#!/usr/bin/env bash
# Wire the Codex CLI for this prototype. Idempotent — safe to re-run.
#
# Usage:  bash scripts/setup-codex.sh
#
# Requires: a shell with internet access and a ChatGPT/Codex subscription.

set -euo pipefail

say() { printf "\033[1;36m[codex-setup]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[codex-setup]\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m[codex-setup]\033[0m %s\n" "$*" >&2; exit 1; }

# 1. Install if missing.
if command -v codex >/dev/null 2>&1; then
  say "codex already installed: $(command -v codex)"
else
  say "codex not on PATH — installing"
  case "$(uname -s)" in
    Darwin*)
      if command -v brew >/dev/null 2>&1; then
        brew install --cask codex || die "brew install failed; try: npm install -g @openai/codex"
      elif command -v npm >/dev/null 2>&1; then
        npm install -g @openai/codex
      else
        die "neither brew nor npm available; install one and re-run"
      fi
      ;;
    Linux*)
      if command -v npm >/dev/null 2>&1; then
        npm install -g @openai/codex
      else
        die "npm required on Linux; install Node.js and re-run"
      fi
      ;;
    *)
      die "unsupported OS: $(uname -s); install codex manually from https://github.com/openai/codex"
      ;;
  esac
fi

# 2. Verify version.
say "codex version: $(codex --version 2>&1 | head -1)"

# 3. Auth — only prompts if not already logged in.
if codex auth status >/dev/null 2>&1; then
  say "codex already authenticated"
else
  warn "you are not logged in — running 'codex login' (browser will open)"
  codex login
fi

# 4. Smoke test (cheap; one short response).
say "running 1-token smoke test"
if echo 'Reply with the word OK and nothing else.' | codex exec --model gpt-5-codex 2>&1 | head -10; then
  say "smoke test produced output (review above)"
else
  warn "smoke test failed; check 'codex --help' and adjust src/app/core/codex.py flags"
fi

# 5. Dump help so we know the actual flag surface.
say "codex --help:"
codex --help 2>&1 | head -40 || true
echo
say "codex exec --help:"
codex exec --help 2>&1 | head -40 || true

say "done — if any flags above differ from src/app/core/codex.py, edit that file."
