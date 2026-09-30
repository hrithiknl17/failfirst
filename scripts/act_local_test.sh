#!/usr/bin/env bash
# Run the example workflow end to end in Docker with nektos/act — fully local.
#
#   scripts/act_local_test.sh [same-repo|fork] [branch]
#
# - Target: a throwaway clone of the sandbox under .tools/act-target (push disabled).
# - The Action is used as a local action (./.failfirst-action); nothing is published.
# - post-comment is "false" and no GITHUB_TOKEN is given to act, so the only
#   comment step that can run is the dry run. No GitHub API call is possible.
# - Needs GEMINI_API_KEY in the environment (passed to act as a secret).
set -euo pipefail

MODE="${1:-same-repo}"
BRANCH="${2:-demo/hub-log-button}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="$ROOT/../liquid-financial-sandbox"
TOOLS="$ROOT/.tools"
TARGET="$TOOLS/act-target"
REPO="hrithiknl17/liquid-financial"

rm -rf "$TARGET"
git clone -q "$SANDBOX" "$TARGET"
cd "$TARGET"
git remote set-url origin "https://github.com/$REPO.git"      # act derives github.repository from this
git remote set-url --push origin DISABLED-no-push-from-act-test
git checkout -q -B "$BRANCH" "origin/$BRANCH"
# Not git-ignored on purpose: act skips ignored files when copying the workspace in.

mkdir -p .failfirst-action .github/workflows
cp -r "$ROOT/action.yml" "$ROOT/requirements.txt" "$ROOT/action" .failfirst-action/
find .failfirst-action -name __pycache__ -type d -prune -exec rm -rf {} +

# The example workflow, pointed at the local action, dry-run comment, and no
# checkout ref override (act only uses the local tree when ref is not set; the
# tree is already at the PR head).
python - "$ROOT/examples/liquid-financial/failfirst.yml" .github/workflows/failfirst-local.yml <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
text = text.replace("uses: hrithiknl17/failfirst@v1", "uses: ./.failfirst-action")
text = text.replace("          gemini-api-key: ${{ secrets.GEMINI_API_KEY }}",
                    "          gemini-api-key: ${{ secrets.GEMINI_API_KEY }}\n          post-comment: \"false\"")
text = text.replace("          ref: ${{ github.event.pull_request.head.sha }}\n", "")
assert "./.failfirst-action" in text and 'post-comment: "false"' in text
open(dst, "w", encoding="utf-8").write(text)
PY

HEAD_SHA="$(git rev-parse HEAD)"
BASE_SHA="$(git rev-parse origin/master)"
HEAD_REPO="$REPO"
[ "$MODE" = "fork" ] && HEAD_REPO="someone-else/liquid-financial"
cat > "$TOOLS/event-$MODE.json" <<JSON
{
  "action": "synchronize",
  "number": 1,
  "repository": {"full_name": "$REPO"},
  "pull_request": {
    "number": 1,
    "draft": false,
    "title": "$(git log -1 --format=%s)",
    "body": "Local act test. \$(echo injected) \`whoami\` should stay text.",
    "head": {"sha": "$HEAD_SHA", "ref": "$BRANCH", "repo": {"full_name": "$HEAD_REPO"}},
    "base": {"sha": "$BASE_SHA", "ref": "master", "repo": {"full_name": "$REPO"}}
  }
}
JSON

echo "-P ubuntu-latest=catthehacker/ubuntu:act-latest" > .actrc

# Belt and braces: no token can reach act, and the workflow must still be dry-run.
unset GITHUB_TOKEN GH_TOKEN
grep -q 'post-comment: "false"' .github/workflows/failfirst-local.yml || { echo "refusing: workflow is not dry-run"; exit 1; }
"$TOOLS/act.exe" pull_request \
  -e "$TOOLS/event-$MODE.json" \
  -W .github/workflows/failfirst-local.yml \
  -s GEMINI_API_KEY \
  --artifact-server-path "$TOOLS/act-artifacts-$MODE" \
  --cache-server-path "$TOOLS/act-cache"
