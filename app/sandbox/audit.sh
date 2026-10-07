#!/bin/sh
# Collect the audit bundle of one run from the sandbox `kculture` (host side, read-only OpenShell calls).
#   sh app/sandbox/audit.sh <run_id> [--since <duration, e.g. 30m>]
# Writes outputs/audit/<run_id>/ (git-ignored):
#   run/                  the run folder /hackathon/output/<run_id> (run.json, trace.jsonl, course/answer, publish.json)
#   openshell-logs.txt    openshell logs kculture --since <duration> -n <lines>, credential-looking values masked
#   policy-list.txt       openshell policy list kculture (revision history: VERSION HASH STATUS CREATED ERROR)
#   policy-current.txt    openshell policy get kculture (the revision in force when the bundle was made)
#   audit.md              trace publish_attempt events and api.github.com ALLOWED/DENIED lines on one UTC timeline
# --since defaults to the time since the run started (from run_id) plus 5 minutes. Lines: AUDIT_LOG_LINES (5000).
# `sandbox download` overwrites silently and keeps symlinks, so the run folder lands in a temporary folder first,
# is refused if it holds anything but regular files and folders, and only then moves into place. An existing
# bundle is never overwritten.
# Exit: 0 bundle written and every publish attempt paired with a matching log verdict; 1 bundle written but some
# attempt is unpaired or contradicts the log, or the download/OpenShell call failed; 2 usage error or bundle exists.
set -eu
usage() { echo "usage: audit.sh <run_id> [--since <duration, e.g. 30m>]" >&2; exit 2; }
[ $# -eq 1 ] || [ $# -eq 3 ] || usage
run_id=$1
case $run_id in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
  *) echo "run_id must look like YYYYMMDDTHHMMSSZ-xxxx: $run_id" >&2; exit 2;;
esac
since=
if [ $# -eq 3 ]; then
  [ "$2" = --since ] || usage
  since=$3
  case $since in ''|*[!0-9smhd]*) usage;; esac
fi
sandbox=kculture
lines=${AUDIT_LOG_LINES:-5000}
case $lines in ''|*[!0-9]*) echo "AUDIT_LOG_LINES must be a number" >&2; exit 2;; esac
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
out="$root/outputs/audit/$run_id"
[ ! -e "$out" ] || { echo "already exists: outputs/audit/$run_id (move it away to collect again)" >&2; exit 2; }
command -v openshell >/dev/null 2>&1 || { echo "openshell CLI not found" >&2; exit 2; }
correlate="$here/audit_correlate.py"
[ -n "$since" ] || since=$(python3 "$correlate" since "$run_id")

tmp=$(mktemp -d "${TMPDIR:-/tmp}/kculture-audit.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
trap 'exit 130' INT TERM
mkdir "$tmp/dl" "$tmp/bundle"

# `sandbox download` only reads under the workspace /sandbox (outside it: "outside the sandbox workspace").
# So copy the run folder to /sandbox/work/dl/ with exec first (stdin closed: exec never returns otherwise), then download.
# run_id was checked against its pattern above, so it is safe inside the sh -c string.
stage_dir=/sandbox/work/dl
echo "+ openshell sandbox exec -n $sandbox --no-tty -- cp -R /hackathon/output/$run_id $stage_dir/"
openshell sandbox exec -n "$sandbox" --no-tty --timeout 60 -- \
  sh -c "rm -rf $stage_dir/$run_id && mkdir -p $stage_dir && cp -R /hackathon/output/$run_id $stage_dir/" \
  < /dev/null >/dev/null || { echo "copy into the workspace failed: /hackathon/output/$run_id" >&2; exit 1; }
echo "+ openshell sandbox download $sandbox $stage_dir/$run_id"
openshell sandbox download "$sandbox" "$stage_dir/$run_id" "$tmp/dl" < /dev/null >/dev/null || {
  echo "download failed: $stage_dir/$run_id" >&2; exit 1; }
openshell sandbox exec -n "$sandbox" --no-tty --timeout 30 -- rm -rf "$stage_dir/$run_id" < /dev/null >/dev/null 2>&1 || true
special=$(find "$tmp/dl" ! -type f ! -type d -print | sed "s#^$tmp/dl/##" | head -n 5)
if [ -n "$special" ]; then
  echo "refusing: the downloaded run folder holds links or special files (not followed):" >&2
  printf '  %s\n' $special >&2
  exit 1
fi
if [ -f "$tmp/dl/$run_id/trace.jsonl" ] || [ -f "$tmp/dl/$run_id/run.json" ]; then
  mv "$tmp/dl/$run_id" "$tmp/bundle/run"
elif [ -f "$tmp/dl/trace.jsonl" ] || [ -f "$tmp/dl/run.json" ]; then
  mv "$tmp/dl" "$tmp/bundle/run"
else
  echo "the download has no run.json or trace.jsonl" >&2; exit 1
fi

echo "+ openshell logs $sandbox --since $since -n $lines"
openshell logs "$sandbox" --since "$since" -n "$lines" > "$tmp/logs.raw" 2> "$tmp/logs.err" || {
  python3 "$correlate" redact < "$tmp/logs.err" >&2; echo "openshell logs failed" >&2; exit 1; }
python3 "$correlate" redact < "$tmp/logs.raw" > "$tmp/bundle/openshell-logs.txt"
echo "+ openshell policy list $sandbox"
openshell policy list "$sandbox" > "$tmp/list.raw" 2>&1 || { echo "openshell policy list failed" >&2; exit 1; }
python3 "$correlate" redact < "$tmp/list.raw" > "$tmp/bundle/policy-list.txt"
echo "+ openshell policy get $sandbox"
openshell policy get "$sandbox" > "$tmp/get.raw" 2>&1 || { echo "openshell policy get failed" >&2; exit 1; }
python3 "$correlate" redact < "$tmp/get.raw" > "$tmp/bundle/policy-current.txt"

rc=0
python3 "$correlate" report --run-dir "$tmp/bundle/run" --logs "$tmp/bundle/openshell-logs.txt" \
  --policy-list "$tmp/bundle/policy-list.txt" --policy-current "$tmp/bundle/policy-current.txt" \
  > "$tmp/bundle/audit.md" || rc=$?
[ "$rc" -le 1 ] || { echo "audit.md could not be made (exit $rc)" >&2; exit 1; }
mkdir -p "$root/outputs/audit"
[ ! -e "$out" ] || { echo "already exists: outputs/audit/$run_id (created meanwhile; nothing moved)" >&2; exit 2; }
mv "$tmp/bundle" "$out"
echo "bundle: outputs/audit/$run_id/ (run/, openshell-logs.txt, policy-list.txt, policy-current.txt, audit.md)"
exit "$rc"
