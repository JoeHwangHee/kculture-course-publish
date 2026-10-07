#!/usr/bin/env python3
"""상위·하위 오케스트레이터 사이의 작업 공간과 지시·보고 파일을 다룬다.

트랙마다 main 루트의 `app/.orch/<트랙>/` 아래에 둘을 둔다(git 제외 폴더).
  wt/   하위 오케스트레이터의 git worktree(브랜치 `track/<트랙>`)
  log/  작업기록 폴더. 지시·보고 파일(NNNN-<보낸 쪽>-<종류>.md), 알림 flag(.flag → 읽으면 .ack), worklog.md

명령(종료 코드: 0 성공, 1 받을 것 없음·대상 없음·시간 초과, 2 사용법·전제 조건 오류, 3 git·OS 실패)
  spawn  <트랙> --scope app/<디렉터리>/   worktree와 작업기록 폴더를 만든다(상위, main 폴더에서)
  launch <트랙> [--print]                  새 터미널 창에서 하위 오케스트레이터 세션을 띄운다(macOS)
  send   <트랙> --from top|sub --kind <종류> --body-file <파일|->   지시·보고 파일과 flag를 만든다
  inbox  [<트랙>] --for top|sub            읽지 않은 flag를 보인다(있으면 0, 없으면 1). 본문 경로는 지금 폴더 기준
  wait   [<트랙>] --for top|sub [--timeout 초]   읽지 않은 flag가 생길 때까지 기다린다(백그라운드 실행용)
  ack    <트랙> <번호> --for top|sub        flag를 .ack로 바꾼다(읽음 처리)
  log    <트랙> <내용...>                    worklog.md에 시각과 한 줄을 덧붙인다
  status                                   트랙별 브랜치, 브랜치에만 있는 커밋 수, 읽지 않은 flag 수, 최종 보고 여부

표준 라이브러리만 쓴다. 시스템 python3(3.9)에서 돈다.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

TRACK_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
KINDS = {"top": ("instruction", "answer"), "sub": ("report", "request", "final")}
MSG_RE = re.compile(r"^(\d{4})-(top|sub)-([a-z]+)\.(md|flag|ack)$")
LOCK_RE = re.compile(r"^\.(\d{4})\.lock$")
ORCH_DIR = os.path.join("app", ".orch")


class Fail(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code


def git(args, cwd=None):
    try:
        out = subprocess.run(["git"] + args, cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
    except OSError as e:
        raise Fail(3, "git을 실행하지 못했다: %s" % e)
    if out.returncode != 0:
        raise Fail(3, "git %s 실패: %s" % (" ".join(args), out.stderr.strip()))
    return out.stdout.strip()


def main_root():
    common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if os.path.basename(common) != ".git":
        raise Fail(2, "main 폴더의 .git을 찾지 못했다")
    return os.path.dirname(common)


def check_track(track):
    if not TRACK_RE.match(track or ""):
        raise Fail(2, "트랙 이름은 영문 소문자·숫자·하이픈 31자 이하다: %r" % track)
    return track


def track_dir(root, track):
    return os.path.join(root, ORCH_DIR, check_track(track))


def log_dir(root, track):
    d = os.path.join(track_dir(root, track), "log")
    if not os.path.isdir(d):
        raise Fail(1, "트랙 %s의 작업기록 폴더가 없다(spawn 전)" % track)
    return d


def all_tracks(root):
    base = os.path.join(root, ORCH_DIR)
    if not os.path.isdir(base):
        return []
    return sorted(t for t in os.listdir(base)
                  if TRACK_RE.match(t) and os.path.isdir(os.path.join(base, t, "log")))


def infer_track(root, track):
    if track:
        return check_track(track)
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch.startswith("track/"):
        return check_track(branch[len("track/"):])
    return None


def now():
    return datetime.datetime.now().strftime("%H:%M:%S")


def cmd_spawn(a):
    root = main_root()
    track = check_track(a.track)
    scope = a.scope.rstrip("/") + "/"
    if not (scope.startswith("app/") and len(scope) > len("app/")) or ".." in scope or scope.startswith("app/."):
        raise Fail(2, "--scope는 app/<디렉터리>/ 꼴이다: %r" % a.scope)
    if os.path.realpath(git(["rev-parse", "--show-toplevel"])) != os.path.realpath(root):
        raise Fail(2, "spawn은 main 폴더에서 부른다(트랙 worktree 안이 아니다)")
    probe = os.path.join(ORCH_DIR, track, "wt", "x")
    ignored = subprocess.run(["git", "check-ignore", "-q", probe], cwd=root).returncode
    if ignored != 0:
        raise Fail(2, ".gitignore가 app/.orch/를 빼지 않는다. 먼저 .gitignore에 넣는다")
    d = track_dir(root, track)
    if os.path.exists(d):
        raise Fail(2, "트랙 %s가 이미 있다" % track)
    branch = "track/" + track
    if subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/" + branch], cwd=root,
                      stdout=subprocess.DEVNULL).returncode == 0:
        raise Fail(2, "브랜치 %s가 이미 있다. 새 트랙 이름을 쓴다" % branch)
    git(["worktree", "add", "-b", branch, os.path.join(d, "wt"), a.base], cwd=root)
    os.makedirs(os.path.join(d, "log"))
    meta = {"track": track, "scope": scope, "branch": branch, "base": a.base,
            "base_commit": git(["rev-parse", a.base], cwd=root),
            "created": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "log", "worklog.md"), "w", encoding="utf-8") as f:
        f.write("# 작업기록: %s\n\n- 범위: `%s`\n- 브랜치: `%s`(base %s %s)\n\n"
                % (track, scope, branch, a.base, meta["base_commit"][:7]))
    print("spawn %s %s %s" % (track, branch, os.path.relpath(os.path.join(d, "wt"), root)))
    return 0


def launch_prompt(track):
    return ("너는 트랙 %s의 하위 오케스트레이터다. 한국어로 답한다. 먼저 CLAUDE.md의 "
            "'하위 오케스트레이터 세션이라면' 절을 읽고 따른다. 지시는 "
            "`python3 scripts/orch.py inbox %s --for sub`로 확인한다." % (track, track))


def cmd_launch(a):
    root = main_root()
    track = check_track(a.track)
    d = track_dir(root, track)
    wt = os.path.join(d, "wt")
    if not os.path.isdir(wt):
        raise Fail(2, "트랙 %s의 worktree가 없다(spawn 먼저)" % track)
    launcher = os.path.join(d, "log", "launch.sh")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write("#!/bin/zsh\ncd %s || exit 1\nexec claude -n track-%s %s\n"
                % (sh_quote(wt), track, sh_quote(launch_prompt(track))))
    os.chmod(launcher, 0o755)
    if a.print_only or sys.platform != "darwin":
        print("launch %s %s" % (track, launcher))
        return 0
    cmd = "zsh " + sh_quote(launcher)
    script = 'tell application "Terminal" to do script "%s"' % cmd.replace("\\", "\\\\").replace('"', '\\"')
    rc = subprocess.run(["osascript", "-e", script, "-e",
                         'tell application "Terminal" to activate']).returncode
    if rc != 0:
        raise Fail(3, "터미널 창을 열지 못했다. 직접 실행: zsh %s" % launcher)
    print("launch %s" % track)
    return 0


def sh_quote(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


def next_number(d):
    nums = []
    for n in os.listdir(d):
        m = MSG_RE.match(n) or LOCK_RE.match(n)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def cmd_send(a):
    root = main_root()
    track = infer_track(root, a.track)
    if not track:
        raise Fail(2, "트랙을 정할 수 없다(인자로 준다)")
    if a.kind not in KINDS[a.sender]:
        raise Fail(2, "%s 쪽이 보낼 수 있는 종류: %s" % (a.sender, ", ".join(KINDS[a.sender])))
    d = log_dir(root, track)
    if a.body_file == "-":
        body = sys.stdin.read()
    else:
        try:
            with open(a.body_file, encoding="utf-8") as f:
                body = f.read()
        except OSError as e:
            raise Fail(2, "본문 파일을 읽지 못했다: %s" % e)
    if not body.strip():
        raise Fail(2, "본문이 비었다")
    header = "<!-- %s %s → %s, %s -->\n" % (track, a.sender, "sub" if a.sender == "top" else "top", now())
    for _ in range(20):
        n = next_number(d)
        try:
            # 번호는 보낸 쪽·종류와 상관없는 이름으로 먼저 예약한다(양쪽이 동시에 보내도 겹치지 않게)
            fd = os.open(os.path.join(d, ".%04d.lock" % n), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        stem = "%04d-%s-%s" % (n, a.sender, a.kind)
        tmp = os.path.join(d, ".%s.tmp" % stem)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(header + body)
        os.replace(tmp, os.path.join(d, stem + ".md"))
        open(os.path.join(d, stem + ".flag"), "w").close()
        print("send %s %04d %s %s" % (track, n, a.sender, a.kind))
        return 0
    raise Fail(3, "번호를 잡지 못했다")


def unread(root, tracks, reader):
    sender = "sub" if reader == "top" else "top"
    rows = []
    for t in tracks:
        d = os.path.join(root, ORCH_DIR, t, "log")
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            m = MSG_RE.match(n)
            if m and m.group(4) == "flag" and m.group(2) == sender:
                md = os.path.join(d, n[:-len(".flag")] + ".md")
                rows.append((t, m.group(1), m.group(3), os.path.relpath(md, os.getcwd())))
    return rows


def resolve_tracks(root, track, reader):
    t = infer_track(root, track)
    if t:
        if not os.path.isdir(os.path.join(root, ORCH_DIR, t, "log")):
            raise Fail(2, "트랙 %s의 작업기록 폴더가 없다(이름 확인)" % t)
        return [t]
    if reader == "sub":
        raise Fail(2, "하위 쪽은 트랙을 정해야 한다(인자 또는 track/ 브랜치)")
    return all_tracks(root)


def cmd_inbox(a):
    root = main_root()
    rows = unread(root, resolve_tracks(root, a.track, a.reader), a.reader)
    for r in rows:
        print("%s %s %s %s" % r)
    return 0 if rows else 1


def cmd_wait(a):
    root = main_root()
    deadline = time.time() + a.timeout
    while True:
        rows = unread(root, resolve_tracks(root, a.track, a.reader), a.reader)
        if rows:
            for r in rows:
                print("%s %s %s %s" % r)
            return 0
        if time.time() >= deadline:
            print("timeout", file=sys.stderr)
            return 1
        time.sleep(a.interval)


def cmd_ack(a):
    root = main_root()
    track = infer_track(root, a.track)
    d = log_dir(root, track)
    sender = "sub" if a.reader == "top" else "top"
    num = "%04d" % int(a.number)
    hits = [n for n in os.listdir(d) if n.startswith("%s-%s-" % (num, sender)) and n.endswith(".flag")]
    if not hits:
        print("읽지 않은 flag가 없다: %s %s" % (track, num), file=sys.stderr)
        return 1
    for n in hits:
        os.replace(os.path.join(d, n), os.path.join(d, n[:-len(".flag")] + ".ack"))
    print("ack %s %s" % (track, num))
    return 0


def cmd_log(a):
    root = main_root()
    track = infer_track(root, a.track)
    d = log_dir(root, track)
    text = " ".join(a.text).strip()
    if not text:
        raise Fail(2, "내용이 비었다")
    with open(os.path.join(d, "worklog.md"), "a", encoding="utf-8") as f:
        f.write("- %s %s\n" % (now(), text.replace("\n", " ")))
    return 0


def cmd_status(a):
    root = main_root()
    tracks = all_tracks(root)
    if not tracks:
        print("트랙 없음")
        return 1
    print("트랙\t브랜치\t브랜치에만 있는 커밋(squash 뒤에도 0이 되지 않음)\t상위가 안 읽음\t하위가 안 읽음\t최종 보고")
    for t in tracks:
        d = os.path.join(root, ORCH_DIR, t)
        branch = "track/" + t
        try:
            ahead = git(["rev-list", "--count", "main.." + branch], cwd=root)
        except Fail:
            ahead = "?"
        top_n = len(unread(root, [t], "top"))
        sub_n = len(unread(root, [t], "sub"))
        final = "있음" if any(MSG_RE.match(n) and n.endswith("-sub-final.md")
                             for n in os.listdir(os.path.join(d, "log"))) else "없음"
        print("%s\t%s\t%s\t%d\t%d\t%s" % (t, branch, ahead, top_n, sub_n, final))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="orch.py", description="오케스트레이터 작업 공간·지시·보고")
    s = p.add_subparsers(dest="cmd")
    x = s.add_parser("spawn")
    x.add_argument("track")
    x.add_argument("--scope", required=True)
    x.add_argument("--base", default="main")
    x = s.add_parser("launch")
    x.add_argument("track")
    x.add_argument("--print", dest="print_only", action="store_true")
    x = s.add_parser("send")
    x.add_argument("track", nargs="?")
    x.add_argument("--from", dest="sender", required=True, choices=("top", "sub"))
    x.add_argument("--kind", required=True)
    x.add_argument("--body-file", required=True)
    for name in ("inbox", "wait"):
        x = s.add_parser(name)
        x.add_argument("track", nargs="?")
        x.add_argument("--for", dest="reader", required=True, choices=("top", "sub"))
        if name == "wait":
            x.add_argument("--timeout", type=int, default=3600)
            x.add_argument("--interval", type=int, default=5)
    x = s.add_parser("ack")
    x.add_argument("track")
    x.add_argument("number")
    x.add_argument("--for", dest="reader", required=True, choices=("top", "sub"))
    x = s.add_parser("log")
    x.add_argument("track")
    x.add_argument("text", nargs="+")
    s.add_parser("status")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    if not a.cmd:
        build_parser().print_usage(sys.stderr)
        return 2
    fn = {"spawn": cmd_spawn, "launch": cmd_launch, "send": cmd_send, "inbox": cmd_inbox,
          "wait": cmd_wait, "ack": cmd_ack, "log": cmd_log, "status": cmd_status}[a.cmd]
    try:
        return fn(a)
    except Fail as e:
        print("orch: %s" % e, file=sys.stderr)
        return e.code
    except ValueError as e:
        print("orch: 값 오류: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
