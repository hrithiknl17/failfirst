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
**Chose:** `gemini-3.1-flash-lite` for classification, `gemini-3.8-flash` for generation. Both overridable via `FAILFIRST_CLASSIFY_MODEL` / `FAILFIRST_GENERATE_MODEL`.
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

## [2026-09-30] Decision: A verified test must FAIL on the base build and PASS on the PR build
**Context:** "Passes against a real build" alone is weak: a test that checks something already true (e.g. "the page has a button") passes on the PR and proves nothing about the change.
**Options considered:** Run only against the PR build vs also run against the base (merge-base) build and require a failure there.
**Chose:** Both. VERIFIED = passes on PR build AND fails on base build. Passing on both is treated as a failed attempt ("doesn't cover the change").
**Why:** It's the cheapest objective proof that the test actually covers this PR. Costs one extra build + one extra run per PR. Stricter than the brief, same direction as its spirit.
**Ours vs generated:** joint (I proposed, you approved)

## [2026-09-30] Decision: One retry total, shared across failure types
**Context:** Brief says retry once on selector failure with the DOM fed back. There are now three ways an attempt can fail: rejected by the safety check, fails on the PR build, passes on the base build.
**Options considered:** One retry per failure type (up to 4 generations) vs one retry total (max 2 generations).
**Chose:** Max 2 generations. Any failure feeds its specific evidence (pytest output, ARIA snapshot at the moment of failure, or "this also passes on base") into the single retry. Still failing → UNVERIFIED, not posted.
**Why:** Keeps cost and latency bounded and matches the brief's "retry once". If pass rates are low, the lever is the model or the context, not more retries.
**Ours vs generated:** my call

## [2026-09-30] Decision: Serve the production bundle with `vite preview`; reach app state through the UI only
**Context:** Verification needs a real running build of the PR (and of base). The app also has an Express server, but it only backs the AI/cloud features.
**Options considered:** `vite dev` vs `vite build` + `vite preview` vs the full `npm run serve` (Express). For state: inject demo data into localStorage vs click through the UI.
**Chose:** `npm run build`, then `npm run preview -- --port {port} --strictPort --host 127.0.0.1` (both overridable per target). Tests start from an empty browser and click "Try it with sample data" like a user would.
**Why:** The production bundle is what users get; dev mode can hide build-only bugs. Express adds nothing testable without secrets. Injecting localStorage couples tests to storage internals and can make a test pass without the UI working.
**Ours vs generated:** joint (I proposed, you approved)

## [2026-09-30] Decision: Build each ref in a git worktree nested inside the target checkout
**Context:** Need base and PR builds side by side without disturbing the checkout, and `npm ci` per build costs ~30s.
**Options considered:** Check out refs in place (mutates the working tree) vs worktrees in a temp dir (needs its own `npm ci`) vs worktrees under `<repo>/.failfirst/worktrees/<sha>`.
**Chose:** Nested worktrees, excluded via the repo's local `.git/info/exclude`. `npm ci` runs inside a worktree only when its `package.json`/lockfile differs from the checkout's.
**Why:** Node resolves packages by walking up directories, so a nested worktree reuses the parent's `node_modules` — measured: build in ~6s, no install. Worktrees are keyed by commit SHA so reruns reuse finished builds. The checkout's `git status` stays clean.
**Ours vs generated:** my call

## [2026-09-30] Decision: Generated test code is AST-checked and run with a scrubbed environment
**Context:** The test is written by an LLM whose input includes untrusted PR content, and it is then *executed* on the runner. A prompt-injected PR could steer it into reading secrets (e.g. `GITHUB_TOKEN`) or faking a pass by editing the DOM.
**Options considered:** Trust the model vs static allowlist check + minimal environment.
**Chose:** Before running, parse the code: only `re`, `pytest`, `playwright.sync_api` imports; no `eval`/`exec`/`open`/dunder access; no `page.evaluate`, `add_init_script`, `route`, `set_content`, `request`, or sleeps. Violations count as a failed attempt. The pytest subprocess gets an env with only PATH/temp/home-type variables — no tokens, no API keys.
**Why:** Defense in depth for code execution driven by untrusted input. The Playwright restrictions double as honesty rules: a test may only do what a user can do, so it can't pass by manipulating the page.
**Ours vs generated:** my call

## [2026-09-30] Decision: Context for generation = PR-build ARIA snapshot + new source + call sites of changed symbols
**Context:** Classification on `demo/percent-zero` showed the model can't tell *where* a shared helper (`percent()`) is rendered from the diff alone.
**Options considered:** Diff only vs diff + full new source of changed files + `git grep` call sites of the exported symbols whose bodies changed + ARIA snapshot of the landing page.
**Chose:** The latter, all read from the PR commit via git (no working-tree reads), with size caps.
**Why:** Snapshot gives real selectors for the entry screen; call sites tell the model which screen to navigate to; the failure-time snapshot on retry covers screens deeper in the app.
**Ours vs generated:** my call

## [2026-09-30] Decision: Fall back to other Gemini models when one is overloaded
**Context:** First end-to-end run died on `gemini-3.8-flash` returning HTTP 503 "model is currently experiencing high demand" three times in a row. The error surfaced correctly, but one busy model shouldn't fail a PR.
**Options considered:** Longer retries on one model vs a fallback chain vs fail the run.
**Chose:** 4 attempts per model with exponential backoff, then the next model in a chain: generation `3.8-flash → 3.5-flash → 2.5-flash`, classification `3.1-flash-lite → 3.5-flash-lite → 2.5-flash-lite` (env-overridable). Only "unavailable" moves down the chain — a bad request or bad answer still fails immediately.
**Why:** Overload is transient and model-specific. Verification is the quality gate, so a fallback model can't lower what gets posted — at worst it lowers the verified rate.
**Ours vs generated:** my call

## [2026-09-30] Decision: UNVERIFIED reasons diagnose "not reachable" separately from "test failed"
**Context:** On `demo/ui-demo-button` the tool correctly refused to post, but said "failed against the PR build", which reads like flakiness. The real cause: the changed button lives on the sign-in screen, which never renders in a build without Supabase keys.
**Options considered:** Generic reason vs detect unreachable UI.
**Chose:** Extract the user-visible text the PR added (JSX text, prose string literals). If none of it appears on the start page or on any page where an attempt failed, say "change not reachable in this build … Not a flaky test: the UI was never there to find." Otherwise name the first pytest error. No text extractable (e.g. a formula change) → no reachability claim.
**Why:** The difference between someone trusting the tool's judgment and someone thinking it's flaky. The check is conservative: it only claims "not reachable" when *every* new string is absent from *every* page seen.
**Ours vs generated:** your call (you asked for it); detection method my call

## [2026-09-30] Decision: Stability gate — a VERIFIED test must survive reruns and a clock sweep
**Context:** Asked to rerun both verified tests 5–10×. Reading the code first showed the Hub banner depends on time of day. Results: `percent-zero` held 10/10 on each build and was correct at all 6 clock times; `hub-log-button` held 10/10 at 14:50 — but **failed on the PR build at 06:00, 21:00 and 23:30**. Plain reruns would have certified a time bomb (and CI runners are on UTC, so it would flip at 02:00 IST).
**Options considered:** Reruns only vs reruns + faking the browser clock (Playwright `page.clock`) vs pinning the clock for every test.
**Chose:** After a first pass, 2 more reruns on the PR build plus the clock at 03:00 / 13:00 / 22:00 on both builds (PR must pass, base must still fail) — 8 extra runs. Any deviation = failed attempt; the retry is told which checks flipped and to pin the clock with `page.clock.set_fixed_time` before `page.goto`. The generation prompt also asks for that up front for date/time-dependent UI.
**Why:** A "verified" test that flips is worse than an honest UNVERIFIED — it breaks the pitch. Pinning every test's clock would hide real time-dependence instead of handling it deliberately. Cost is ~8 runs (~1 min locally), paid only by tests that already passed once.
**Ours vs generated:** joint (you asked for the flakiness check; the clock sweep and gate were my call from what it found)

## [2026-09-30] Decision: Trigger on `pull_request`, never `pull_request_target`
**Context:** The Action builds and runs the PR's own code (`npm ci`, `npm run build`, the generated test). The trigger decides what that code can reach.
**Options considered:** `pull_request` vs `pull_request_target`.
**Chose:** `pull_request` only.
**Why:** Fork PRs get no secrets under `pull_request`, so they get skipped instead of a test — that's the correct trade against `pull_request_target` running untrusted fork code with a Gemini key and a write token in scope, which is a known attack pattern ("pwn request"). Correction found while building: under `pull_request` a fork PR's `GITHUB_TOKEN` is also read-only, so the "skipped" notice can't be a PR comment — it goes to the run's job summary instead, and the fork check runs *before* any PR code (including `npm ci` install scripts) executes.
**Ours vs generated:** your call

## [2026-09-30] Decision: Ship as a composite action (`action.yml`) plus an example consumer workflow
**Context:** The brief puts "the actual Action YAML" in `/.github/workflows/`. But a workflow file in *this* repo runs on *this* repo's PRs (a Python tool, not a web app), and target repos consume an Action via `uses: owner/repo@ref`, which requires `action.yml` at the repo root.
**Options considered:** Workflow-only in this repo vs composite `action.yml` + consumer workflow vs Docker action.
**Chose:** `action.yml` (composite: gate → install → run → post → artifact), `examples/liquid-financial/failfirst.yml` (what a target repo adds), and `.github/workflows/ci.yml` (this tool's own unit tests).
**Why:** Composite reuses the runner's Node/Python (no image to build or pull); the target owns Node setup; this repo's own workflow does something meaningful for this repo. Docker actions are slower and can't reuse `setup-node` caches.
**Ours vs generated:** my call (deviation from the brief's folder note, flagged)

## [2026-09-30] Decision: Workflow hardening for the same-repo path
**Context:** Same-repo PRs do get the Gemini key and a write token, while running PR code.
**Options considered:** Rely on "collaborators are trusted" vs also harden what we control.
**Chose:** `permissions: contents: read, pull-requests: write` only; `persist-credentials: false` on checkout (no token left in `.git/config` for a build script to read); PR title/body read from the event file, never interpolated into shell (`${{ github.event.pull_request.title }}` in a `run:` is script injection); secrets passed only to the step that needs them; build/serve/test subprocesses get an environment with token/secret/key-named variables removed.
**Why:** Same-repo authors already have write access, so they're inside the trust boundary — the real boundary is "forks never run". The rest is defense in depth against accidents (a build that logs its env, a crafted PR title). Env scrubbing is not a sandbox: a same-user process can still read its parent's environment on Linux. Stated plainly so nobody mistakes it for one.
**Ours vs generated:** my call

## [2026-09-30] Decision: Incident — edited the act test's workflow copy mid-run; stopped it and restarted clean
**Context:** While the first local `act` run (same-repo mode) was starting, I ran an actionlint negative check *inside* its working folder. That check used `sed` to rename `post-comment` to `post-commnt` in `.tools/act-target/.github/workflows/failfirst-local.yml` and then renamed it back. That file is a generated, git-ignored copy made by `scripts/act_local_test.sh` from `examples/liquid-financial/failfirst.yml`. Neither the example, nor `action.yml`, nor the sandbox, nor any GitHub repo was touched. The risk: if act had read the typo'd copy, `post-comment` would have fallen back to its default `"true"` and the real Post step would have run.
**Options considered:** Reason from timing that act had already parsed the good version, and keep the run; vs stop it and restart from scratch.
**Chose:** Stopped the run (killed act.exe and removed its container) about 37 s in, while it was still in the Gate step, before any comment step. The rerun deletes and re-clones `act-target` and regenerates the workflow. Verified after restart: the host copy matches a fresh regeneration from the unmodified example; the copy inside the running container has `post-comment: "false"` and the same SHA-256 as the host once Windows CRLFs are stripped (`ff325fe8…`); the example and `action.yml` were last modified at 15:32, before the incident. Added guards to the script: it unsets `GITHUB_TOKEN`/`GH_TOKEN` and refuses to launch act unless the workflow says `post-comment: "false"`. Rule for myself: never touch a folder a running job is using; lint a copy.
**Why:** The no-remote-writes boundary is worth more than a few minutes of rerun time, and "probably fine because of timing" is not evidence. No token was ever used to post: act was never given `GITHUB_TOKEN` (confirmed unset in my shell and in the running container, along with `GH_TOKEN` and `ACTIONS_RUNTIME_TOKEN`); the post client refuses to start without one, before any HTTP request; and `--post` has never been run this session. Every `post` call so far was a dry run, and the real client has only run in unit tests, against a mock transport with a fake token.
**Ours vs generated:** my call (my mistake, and my fix)

## [2026-09-30] Decision: Name the tool failfirst (redgreen was taken on PyPI)
**Context:** Five names proposed; you picked redgreen, conditional on it being free where it matters.
**Options considered:** redgreen vs failfirst (your named fallback).
**Chose:** failfirst. Renamed everywhere: CLI, Action name, env vars (`FAILFIRST_*`), comment marker, worktree folder (`.failfirst/`), example workflow file, README, this log.
**Why:** redgreen is free as `hrithiknl17/redgreen` and on the Actions Marketplace, but taken on PyPI ("redgreen 0.0.9 — (Yet another) nosetests daemon"), and at least nine GitHub repos named redgreen are test-output colour tools, so it would be both unpublishable as a Python package and easy to confuse. failfirst is free as `hrithiknl17/failfirst`, on PyPI (`failfirst` and `fail-first`), and on the Marketplace. Noted: a GitHub account/org called `failfirst` exists (doesn't block our repo name), and `BenMalaga/failfirst` (0 stars) describes a similar idea.
**Ours vs generated:** your call (the rule was yours; I applied it)

## [2026-09-30] Decision: Stability gate also fakes a Sunday evening
**Context:** The README listed a gap: the clock sweep only set times on one date, so UI that changes by day of the week (liquid-financial's Sunday weekly review) was never exercised.
**Options considered:** Keep it as a limitation vs add a day-of-week clock.
**Chose:** Clocks are now (day, time) pairs: 03:00, 13:00, 22:00 on a weekday (today if Mon–Fri, else the Friday before) and 21:00 on the Sunday before it — 10 stability checks instead of 8. The generation prompt now names weekly UI as a reason to pin the clock.
**Why:** Small change (two extra runs per verified test). Rechecked with the exact production gate: both verified tests (`hub-log-button`, `percent-zero`) hold 10/10. The original unpinned hub test, as a control, is still rejected (fails Wed 03:00 and Wed 22:00) — and it *passes* at Sun 21:00, because the Sunday weekly review uses the daytime layout. So Sunday evening really does render differently from a weekday evening in this app. Remaining gap: specific dates, month boundaries and timezones.
**Ours vs generated:** your call (close the gap if small); implementation my call

## [2026-09-30] Decision: Rewrite local history before the first public push
**Context:** The repo is about to go public. All commits were authored with a personal email, and every commit's copy of `CLAUDE.md` and `decisions.md` named the reviewer.
**Options considered:** Fix only the current files (name and email stay readable in history) vs rewrite every commit before anything is pushed.
**Chose:** Rewrite all commits: author and committer set to `215130962+hrithiknl17@users.noreply.github.com` (ID+username form, so commits still link to the account), and the reviewer's name replaced with "a reviewer" in every commit's files. The "Ours vs generated" notes are unchanged.
**Why:** Nothing has been pushed, so rewriting is free and safe now and impossible to undo later — once a public commit exists, forks and caches keep it.
**Ours vs generated:** your call (email and name removal); rewriting history rather than only the latest files was my call
