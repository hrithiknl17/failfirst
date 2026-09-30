# Decisions

Running log of every real decision in this project, newest at the bottom.
Written for a reviewer: read this to understand what was built and why without
reading the code.

---

## [2026-09-30] Decision: Use Gemini as the LLM for classification and generation
**Context:** Two pipeline steps (classification, generation) are LLM calls made by the Action itself on a GitHub runner, so the Action needs its own model credential — this Claude Code session doesn't travel with it.
**Options considered:** Anthropic Claude API vs local Ollama (`qwen2.5-coder:14b`, already installed) vs Gemini API.
**Chose:** Gemini API, key from `GEMINI_API_KEY`.
**Why:** Key already exists and works; runs identically on a laptop and on a GitHub-hosted runner (Ollama can't be reached from hosted runners without a self-hosted runner on the laptop). Claude would need a new paid key.
**Ours vs generated:** your call (after I laid out Claude / Ollama / Gemini trade-offs)

## [2026-09-30] Decision: Model split — flash-lite classifies, flash generates
**Context:** Classification is a yes/no with a reason; generation writes code that must pass a real run. Different difficulty, different price.
**Options considered:** One model for both vs cheap model for classification + stronger for generation.
**Chose:** `gemini-3.1-flash-lite` for classification, `gemini-3.8-flash` for generation. Both overridable via `PRGEN_CLASSIFY_MODEL` / `PRGEN_GENERATE_MODEL`.
**Why:** Classification runs on every PR, so it should be cheap. Generation quality directly drives the verified-pass rate; if too many tests land as unverified, first lever is swapping to `gemini-3.1-pro-preview`.
**Ours vs generated:** my call

## [2026-09-30] Decision: Generated tests are Python (pytest-playwright), not TypeScript
**Context:** liquid-financial is a TypeScript repo, and the generated test gets posted into its PRs. The Action itself is Python either way — this is only about the output file.
**Options considered:** TypeScript `@playwright/test` (matches the repo, most common Playwright flavour) vs Python `pytest-playwright`.
**Chose:** Python `pytest-playwright`.
**Why:** The human reviewer of every generated test is the repo owner, who reads Python fluently and TypeScript poorly — a test the reviewer can't read turns "human review" into a rubber stamp, which defeats the product. Playwright's Python API is near-identical (same locators, same auto-wait), and Python Playwright is already installed. Language lives only in the generation prompt + verification runner, so adding TS later is a two-module change.
**Ours vs generated:** joint (I recommended TS; your Python fluency flipped it)

## [2026-09-30] Decision: Demo against a separate sandbox clone, push disabled
**Context:** Plan was to clone liquid-financial to `Downloads/liquid-financial`, but that folder already exists as the owner's working copy — with a real `.env` (Supabase keys → sign-in wall, real cloud DB) and `origin` pointing at the production repo.
**Options considered:** Reuse the working copy vs fresh clone elsewhere.
**Chose:** Fresh clone at `Downloads/liquid-financial-sandbox`, no `.env`, and `git remote set-url --push origin DISABLED-no-push-from-sandbox`.
**Why:** With no `.env` the app runs in local-only mode (by design, see its `src/lib/cloud.ts`), so tests verify against a real build with zero secrets. Disabling the push URL makes an accidental push to production impossible, not just unlikely. The working copy is never touched.
**Ours vs generated:** my call (safer variant of the approved plan)

## [2026-09-30] Decision: Ground selectors with an ARIA snapshot of the real page, not `playwright codegen`
**Context:** The brief says to use codegen as a reference so selectors are real. `codegen` is an interactive recorder — a human clicks around a headed browser. It cannot run headless on a CI runner.
**Options considered:** codegen (manual, not automatable) vs Playwright's `aria_snapshot()` of the rendered page plus a list of role/name/test-id locators pulled from the live DOM.
**Chose:** ARIA snapshot + extracted locator list, captured from the local build.
**Why:** Same goal — the model only sees selectors that exist on the real page — but fully automatable. It's also what verification feeds back to the model on the one allowed retry.
**Ours vs generated:** my call (flagged as a deviation from the brief)

## [2026-09-30] Decision: Read the diff from local git, not the GitHub API
**Context:** diff_extraction needs the PR diff both on a laptop (sandbox branches) and inside the Action.
**Options considered:** GitHub REST `pulls/{n}/files` vs `git diff base...head` on a checkout.
**Chose:** `git diff base...head` (three-dot = only what the PR branch added since it forked).
**Why:** One code path for local demo and CI (`actions/checkout` with `fetch-depth: 0`), no token needed to read, no API pagination or 3,000-file cap. The GitHub API is only needed for posting the comment.
**Ours vs generated:** my call

## [2026-09-30] Decision: Call Gemini over plain REST (httpx), not an SDK
**Context:** Need one JSON-returning call per step.
**Options considered:** `google-generativeai` (installed, but deprecated) vs `google-genai` (new SDK, extra dependency, tracks new Python versions) vs raw REST with `httpx` (already installed).
**Chose:** REST via `httpx`, behind a small `LLMClient` interface.
**Why:** ~60 lines, no SDK churn, trivially mockable in tests with `httpx.MockTransport`, works on the local Python 3.9. The interface keeps swapping to Claude/Ollama a one-file change.
**Ours vs generated:** my call

## [2026-09-30] Decision: Deterministic prefilter runs before the LLM classifier
**Context:** Many PRs touch only docs, tests, CI or lockfiles. Sending those to an LLM costs money and adds a failure mode for an obvious answer.
**Options considered:** LLM on every PR vs rules-only vs rules for the obvious cases then LLM for the rest.
**Chose:** A conservative skip list (root-level markdown, `docs/`, tests, `.github/`, repo dotfiles) short-circuits to "no test needed" with the reason stated. Anything else — including server code and SQL — goes to the LLM.
**Why:** The prefilter must never wrongly say "no test"; so it only skips categories that cannot change what a browser shows. Ambiguous files cost one cheap LLM call, which is fine.
**Ours vs generated:** my call

## [2026-09-30] Decision: When unsure, the classifier leans towards "test needed"
**Context:** Classification can be wrong in two directions.
**Options considered:** Bias to "no test" (fewer runs) vs bias to "test needed".
**Chose:** Bias to "test needed", reported with `confidence: low`.
**Why:** A false positive costs one generation + one verification run, and verification stops a bad test reaching a human. A false negative silently skips coverage of a real UI change, which is the exact failure this tool exists to prevent. Classifier/LLM errors never default to "no test" — they surface as errors.
**Ours vs generated:** my call

## [2026-09-30] Decision: Code layout — `action/src/<step>/` packages on the import path
**Context:** Brief fixes the folder names; Python needs an import scheme and a place for the shared LLM client.
**Options considered:** Import as `action.src.x` vs put `action/src` on `sys.path` / pytest `pythonpath` and import step packages by name.
**Chose:** `action/src` on the path; step packages imported by name (`diff_extraction`, `classification`, …); shared Gemini client in an extra `action/src/llm/` package; CLI entry at `action/cli.py`.
**Why:** Keeps the mandated folder names while giving clean imports. `llm/` is the one addition to the brief's layout — both LLM steps need it and it belongs to neither.
**Ours vs generated:** my call
