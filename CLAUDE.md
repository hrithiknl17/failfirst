# Project: PR-Scoped Playwright Test Generator

## What this is

A GitHub Action that reads a pull request's diff, decides whether it changes
user-facing behavior, and generates a **verified** Playwright test for that
change — posted back to the PR for human review.

This is **PR-scoped test generation**, not a full regression suite
generator. The entire pitch is: most "AI QA tools" hallucinate selectors and
post unverified tests. This one doesn't. Every generated test runs against a
real local build before a human ever sees it. If it can't be verified, it
gets flagged as unverified instead of silently posted. Never compromise on
this — it's the whole point of the project.

## Before doing anything

1. Read `Product.md`, `README.md`, and `skills.md` if they already exist in
   this repo. Don't overwrite them blind.
2. Search the installed skills (starting with ECC) for anything relevant to
   Playwright test generation, GitHub Action scaffolding, or PR/diff
   handling. Use what's already there instead of rebuilding it. Report which
   skills you used and why.
3. Confirm the Playwright CLI is installed and check its version before
   assuming a command or flag exists.

## Target / demo repo

`github.com/hrithiknl17/liquid-financial` (deployed at
liquid-financial.onrender.com). Clone it **locally**. Never modify the real
production repo directly — work against a local clone or fork. Open local
branches/PRs there to demonstrate the tool end-to-end.

## Hard rules — do not break these

1. **Never create, push to, or modify a remote GitHub repository** —
   including liquid-financial itself — without asking first and getting an
   explicit "yes." Local git init, local commits, local branches are fine
   without asking. Anything that leaves the machine (new repo, `git push`,
   GitHub API writes, opening a real PR) — stop and ask.
2. **Before any major structural decision** (framework/library choice,
   architecture pattern, folder layout, which skill to use for what): state
   the decision, the reasoning, and the trade-off being passed on. For forks
   in the road, wait for explicit go-ahead. For minor calls, proceed and log
   it. Use judgment on which is which.
3. **Log every real decision to `/decisions.md`** as it's made, in the
   format below. This file is for a reviewer to read
   afterward and understand what was built and why, without reading code.

## Stack

Python for the Action itself. Playwright for both generation-grounding
(codegen as a reference so selectors are real, not hallucinated) and
verification (running the generated test against a real local build).

## Folder structure

```
/action/
  src/diff_extraction/     # pulls and filters the PR diff
  src/classification/      # LLM call: does this diff change user-facing
                            # behavior? Must be able to say "no test
                            # needed" and explain why.
  src/context/              # gathers existing tests for touched files +
                            # a DOM snapshot from a running local build
  src/generation/           # LLM call: writes the Playwright test,
                            # grounded in real selectors
  src/verification/         # runs the generated test against a real
                            # local build BEFORE a human sees it. On
                            # selector failure, retry once with the DOM
                            # snapshot fed back in. Still failing → flag
                            # as unverified, do not post.
  src/pr_comment/           # posts the verified test as a suggested
                            # diff on the PR, with a pass/fail badge
/tests/                     # tests for this tool, not liquid-financial's
/.github/workflows/         # the actual Action YAML
/decisions.md
/Product.md                 # what this is, who it's for, what it isn't
/README.md                  # written last, once it works
```

## decisions.md entry format

```
## [date] Decision: <one line>
**Context:** why this came up
**Options considered:** A vs B (vs C)
**Chose:** X
**Why:** 2-3 sentences, no fluff
**Ours vs generated:** my call / your call / joint
```

## Build order

1. Read existing docs + search skills. Report findings before scaffolding.
2. Propose folder structure, confirm plan to clone liquid-financial
   locally. Wait for sign-off on anything touching the real repo.
3. Scaffold locally (git init + first commit — no permission needed).
4. Build `diff_extraction` + `classification` first. Get "should we test
   this" correct before touching generation.
5. Build `generation` + `verification` together — never ship one without
   the other.
6. Open a few small local branches/PRs against the liquid-financial clone
   with real UI changes. Run the tool against them end-to-end.
7. Once it correctly catches a real UI change, stop and show the result.
8. Only after confirmation it works: ask permission to create the GitHub
   repo for the tool itself, then ask again before the actual push.
9. Write README.md last.

## Non-negotiable standard

Every generated test is verified against a real run before a human ever
sees it. No exceptions, no shortcuts to save time. Work fast on everything
else — never on this.
