# Product

## What this is

A GitHub Action that runs on a pull request, reads its diff, decides whether
the change alters something a user would see or do in the browser, and — if it
does — writes a Playwright test for exactly that change. The test is run
against a real local build of the PR **before** anyone sees it. Only a test
that passes is posted to the PR, as a suggested file with a pass badge.

## Who it's for

Small teams and solo developers shipping web UIs who review their own PRs and
don't have a QA engineer. They want a starting-point test for the change they
just made, not a test suite rewrite.

## The one promise

**Every test a human sees has already passed against a real build.**

Most AI QA tools generate tests from the diff alone, invent selectors that
don't exist, and post them unrun. This tool:

1. Grounds generation in the real rendered page (an ARIA snapshot of the
   running build), so selectors come from the DOM, not the model's imagination.
2. Runs the generated test. If a selector fails, it retries once with the
   live DOM fed back in.
3. If it still fails, it says so — the PR gets an "unverified, not posted"
   note with the failure, never a silently broken test.

## What it is not

- **Not a regression-suite generator.** It covers the change in this PR, not
  the whole app.
- **Not a code reviewer.** It doesn't judge whether the change is good.
- **Not a test runner for your existing suite.** It runs only the test it wrote.
- **Not autonomous.** It never commits to your branch. A human accepts or
  rejects the suggestion.
- **Not magic for every diff.** Server-only, refactor, docs and tooling PRs get
  a clear "no test needed, because …" instead of a forced test.

## First target

`liquid-financial` (Vite + React 19 personal-finance app). With no `.env` it
runs fully local with demo data, which makes it a clean real-build target for
verification without any secrets.
