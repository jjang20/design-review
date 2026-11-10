#!/usr/bin/env python3
"""Test-kit helper (S0-4): the deterministic parts of the setup and check skills.

The skills (Claude) do the things only Claude can do: publish the dashboard, call the
database tool, look at which connectors are connected. This script keeps what must not
vary: the five steps, the resume state file, the fixed failure phrases, the summary text,
and the clipboard. Standard library only.

    python3 drs_kit.py estimate
    python3 drs_kit.py start --env cli
    python3 drs_kit.py mark dashboard pass
    python3 drs_kit.py mark db fail --code no-db-tool
    python3 drs_kit.py status
    python3 drs_kit.py deliver
    python3 drs_kit.py engine-ping
    python3 drs_kit.py dashboard-check   # REUSE <url> | PUBLISH

Privacy by construction: the summary is built only from fixed words (step names, pass/fail,
failure codes, connector names, environment name, a date). There is no free-text field, so
a name, an e-mail, an account address, a link or slide content cannot get in (GD-19).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

KIT_VERSION = "0.0.2"
STATE_VERSION = 1

STEPS = [
    ("plugin", "플러그인 설치 확인"),
    ("engine", "빈 엔진 응답"),
    ("dashboard", "대시보드 게시 · 주소 저장"),
    ("db", "데이터베이스 도구 · 대기열 한 바퀴"),
    ("connectors", "덱 커넥터 연결"),
]
STEP_IDS = [s for s, _ in STEPS]
STEP_NAMES = dict(STEPS)

ENVS = {"cli": "Claude Code CLI", "desktop": "Claude 데스크톱 앱", "unknown": "알 수 없음"}
CONNECTORS = {"canva": "Canva", "google_slides": "Google Slides"}

# code -> (what the summary says, the one line "다음에 할 일" shown to the tester)
FAILURES = {
    "plugin-not-found": ("플러그인을 찾지 못함", "다음에 할 일: 설치 안내 문단을 Claude에 다시 붙여 넣으세요."),
    "engine-error": ("빈 엔진이 응답하지 않음", "다음에 할 일: 점검을 다시 실행하세요. 같은 오류가 나면 이 요약을 그대로 보내 주세요."),
    "no-artifact-tool": ("대시보드를 게시할 도구가 없음", "다음에 할 일: Claude 설정에서 아티팩트 기능이 켜져 있는지 확인한 뒤 점검을 다시 실행하세요."),
    "publish-failed": ("대시보드 게시 실패", "다음에 할 일: 점검을 다시 실행하세요. 이어서 시작합니다."),
    "no-db-tool": ("데이터베이스 도구가 이 세션에 없음", "다음에 할 일: 새 대화를 열어 점검을 다시 실행하세요. 같은 오류가 나면 이 요약을 그대로 보내 주세요."),
    "roundtrip-failed": ("대기열 한 바퀴 실패", "다음에 할 일: 점검을 다시 실행하세요. 같은 오류가 나면 이 요약을 그대로 보내 주세요."),
    "none-connected": ("연결된 덱 커넥터가 없음", "다음에 할 일: Claude 설정의 커넥터에서 Canva 또는 Google Slides를 승인한 뒤 점검을 다시 실행하세요."),
    "other": ("원인 불명", "다음에 할 일: 점검을 다시 실행하고, 같은 오류가 나면 이 요약을 그대로 보내 주세요."),
}

ESTIMATE = (
    "예상 시간: 약 6분 (커넥터 승인에 걸리는 시간 포함)\n"
    "클릭 횟수: 약 5번 (문단 붙여 넣기 1 · 설치 승인 1 · 커넥터 승인 1~2 · 요약 붙여 넣기 1)\n"
    "중간에 멈춰도 됩니다. 다시 시작하면 끝낸 단계는 건너뛰고 이어서 합니다."
)


def detect_env(entrypoint=None):
    """Map Claude Code's CLAUDE_CODE_ENTRYPOINT to one of ENVS. Anything unrecognised is 'unknown', never a guess."""
    if entrypoint is None:
        entrypoint = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")
    e = entrypoint.lower()
    if e == "cli":
        return "cli"
    if "desktop" in e:
        return "desktop"
    return "unknown"


def now_utc():
    return datetime.now(timezone.utc)


def state_dir():
    return os.environ.get("DRS_KIT_HOME") or os.path.join(os.path.expanduser("~"), ".config", "template-drs")


def state_path():
    return os.path.join(state_dir(), "kit-state.json")


def new_state(env="unknown", now=None):
    now = now or now_utc()
    return {
        "version": STATE_VERSION,
        "kit_version": KIT_VERSION,
        "env": env if env in ENVS else "unknown",
        "started": now.strftime("%Y-%m-%d"),
        "steps": {s: {"status": "pending", "code": None} for s in STEP_IDS},
        "connectors": [],
    }


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOTICES = {
    "new": "",
    "resumed": "이전에 하던 곳에서 이어서 합니다.",
    "env_changed": "환경이 바뀌어서 처음부터 새로 시작합니다.",
    "completed": "이전 점검이 이미 끝나서 새로 시작합니다.",
    "invalid": "이전 상태 파일을 읽을 수 없어서 새로 시작합니다.",
    "unknown_env": "환경을 알 수 없어서 이어하지 않고 처음부터 새로 시작합니다.",
}


def validate_state(st):
    """True only for a state this script could have written. A hand-edited or damaged file is not trusted:
    the summary is built from these fields, so nothing outside the fixed vocabulary may pass."""
    try:
        if not isinstance(st, dict) or st.get("version") != STATE_VERSION or st.get("kit_version") != KIT_VERSION:
            return False
        if st.get("env") not in ENVS:
            return False
        started = st.get("started")
        if not isinstance(started, str) or not DATE_RE.match(started):
            return False
        datetime.strptime(started, "%Y-%m-%d")
        steps = st.get("steps")
        if not isinstance(steps, dict) or list(steps) != STEP_IDS:
            return False
        for rec in steps.values():
            if not isinstance(rec, dict) or set(rec) != {"status", "code"}:
                return False
            if rec["status"] not in ("pass", "fail", "pending"):
                return False
            if rec["status"] == "fail":
                if rec["code"] not in FAILURES:
                    return False
            elif rec["code"] is not None:
                return False
        conns = st.get("connectors")
        if not isinstance(conns, list) or any(c not in CONNECTORS for c in conns):
            return False
        return True
    except (TypeError, ValueError):
        return False


def read_state(path=None):
    """(state, problem). problem is None for a valid state, 'missing' when there is no file, 'invalid' otherwise."""
    path = path or state_path()
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "invalid"
    return (st, None) if validate_state(st) else (None, "invalid")


def load_state(path=None):
    return read_state(path)[0]


def save_state(st, path=None):
    path = path or state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".kit-state-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def start(env="unknown", path=None, now=None):
    """Begin a run. Returns (state, reason); reason is a key of NOTICES.

    'resumed' only when the same run is still going: the file is valid, the environment is known and the
    same one, and some step is not passed yet. A different environment, an already finished check, or a damaged
    file starts a new run, so a pass can never be carried over to a place it was not measured in.
    """
    env = env if env in ENVS else "unknown"
    st, problem = read_state(path)
    if st is None:
        reason = "invalid" if problem == "invalid" else "new"
    elif env == "unknown" or st["env"] == "unknown":
        # an unknown environment can not be told apart from another one, so a pass is never carried over
        reason = "unknown_env"
    elif st["env"] != env:
        reason = "env_changed"
    elif next_step(st) is None:
        reason = "completed"
    else:
        save_state(st, path)
        return st, "resumed"
    st = new_state(env, now)
    save_state(st, path)
    return st, reason


def mark(st, step, status, code=None, connectors=None):
    if step not in STEP_IDS:
        raise ValueError(f"unknown step: {step}")
    if status not in ("pass", "fail"):
        raise ValueError("status must be pass or fail")
    if status == "fail":
        code = code if code in FAILURES else "other"
    else:
        code = None
    st["steps"][step] = {"status": status, "code": code}
    if step == "connectors":
        st["connectors"] = sorted({c for c in (connectors or []) if c in CONNECTORS})
    return st


def next_step(st):
    """First step that is not passed yet, or None when all five passed."""
    for s in STEP_IDS:
        if st["steps"][s]["status"] != "pass":
            return s
    return None


def progress(step):
    return f"{STEP_IDS.index(step) + 1}/{len(STEP_IDS)} · {STEP_NAMES[step]}"


def status_view(st):
    done = sum(1 for s in STEP_IDS if st["steps"][s]["status"] == "pass")
    nxt = next_step(st)
    return {
        "passed": done,
        "total": len(STEP_IDS),
        "next": nxt,
        "next_progress": progress(nxt) if nxt else None,
        "steps": {s: dict(st["steps"][s]) for s in STEP_IDS},
        "env": st["env"],
        "connectors": st["connectors"],
    }


def build_summary(st):
    """The exact text that would be sent. Fixed words only; see the module docstring."""
    lines = [f"[Template DRS 시험 키트 {KIT_VERSION}] {st['started']}", f"환경: {ENVS.get(st['env'], ENVS['unknown'])}"]
    passed, first_block = 0, None
    for i, s in enumerate(STEP_IDS, 1):
        rec = st["steps"][s]
        if rec["status"] == "pass":
            passed += 1
            tail = "통과"
            if s == "connectors" and st["connectors"]:
                tail += " (" + ", ".join(CONNECTORS[c] for c in st["connectors"]) + ")"
        elif rec["status"] == "fail":
            tail = "실패 (" + FAILURES.get(rec["code"], FAILURES["other"])[0] + ")"
            first_block = first_block or i
        else:
            tail = "하지 않음"
            first_block = first_block or i
        lines.append(f"{i}. {STEP_NAMES[s]} — {tail}")
    if passed == len(STEP_IDS):
        one = f"{len(STEP_IDS)}단계 모두 통과."
    else:
        one = f"{len(STEP_IDS)}단계 중 {passed}단계 통과, {first_block}번에서 멈춤."
    lines.append("한 줄 요약: " + one)
    return "\n".join(lines)


def clipboard_command(platform=None, which=shutil.which):
    """Pick the clipboard program for this machine. None means: show the text for manual copy.

    Why this works for the tester: in Claude Code CLI and in the desktop app's Code tab, Claude's
    shell runs on the tester's own computer, so the system clipboard program is the right target.
    Cloud sessions and sandboxes run elsewhere; there is no tester clipboard to reach, so we
    return None instead of writing to a clipboard nobody can paste from.
    """
    platform = platform or sys.platform
    if platform == "darwin":
        order = [["pbcopy"]]
    elif platform.startswith("win"):
        order = [["clip.exe"], ["clip"]]
    else:
        order = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for cmd in order:
        if which(cmd[0]):
            return cmd
    return None


def copy_to_clipboard(text, platform=None, which=shutil.which, run=subprocess.run):
    cmd = clipboard_command(platform, which)
    if cmd is None:
        return False
    try:
        data = text.encode("utf-16le") if cmd[0].startswith("clip") else text.encode("utf-8")
        r = run(cmd, input=data, timeout=10, capture_output=True)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "index.html")
ARTIFACT_URL_RE = re.compile(r"^https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+$")


def dashboard_file():
    return os.path.join(state_dir(), "dashboard.json")


def page_hash(page=None):
    with open(page or PAGE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def dashboard_check(path=None, page=None):
    """('REUSE', url) only when the saved page is known to be the one this plugin ships; else ('PUBLISH', None).

    The saved file has to carry the sha256 of the page that was published. A file written by an older
    version (no hash), a different page, or a damaged file is not trusted: an old page may still make
    outside calls or store free text (G-5), so it is published again.
    """
    try:
        with open(path or dashboard_file(), encoding="utf-8") as f:
            d = json.load(f)
        url, sha = d.get("url"), d.get("sha256")
    except (OSError, ValueError, AttributeError):
        return "PUBLISH", None
    if isinstance(url, str) and ARTIFACT_URL_RE.match(url) and sha == page_hash(page):
        return "REUSE", url
    return "PUBLISH", None


def dashboard_save(url, path=None, page=None):
    if not isinstance(url, str) or not ARTIFACT_URL_RE.match(url):
        raise ValueError("not an artifact address")
    path = path or dashboard_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"url": url, "sha256": page_hash(page)}, f)


def engine_ping():
    """Run the empty engine once, in-process, so the skills need one simple command instead of a pipe."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
    import noop_engine  # noqa: E402

    return noop_engine.run({"id": "kit-ping", "type": "ping", "payload": {"echo": "kit"}})


def _load_or_exit():
    st, problem = read_state()
    if st is None:
        if problem == "invalid":
            sys.exit("시험 상태 파일이 올바르지 않습니다. start를 실행해 새로 시작하세요.")
        sys.exit("시험 상태가 없습니다. 먼저 start를 실행하세요.")
    return st


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estimate")
    p = sub.add_parser("start")
    p.add_argument("--env", choices=sorted(ENVS) + ["auto"], default="auto", help="auto: read CLAUDE_CODE_ENTRYPOINT")
    p = sub.add_parser("mark")
    p.add_argument("step", choices=STEP_IDS)
    p.add_argument("status", choices=["pass", "fail"])
    p.add_argument("--code", default=None)
    p.add_argument("--connectors", default="", help="comma list of: " + ",".join(CONNECTORS))
    sub.add_parser("status")
    sub.add_parser("summary")
    sub.add_parser("deliver")
    p = sub.add_parser("next-action")
    p.add_argument("code")
    sub.add_parser("reset")
    sub.add_parser("engine-ping")
    sub.add_parser("dashboard-check")
    p = sub.add_parser("dashboard-save")
    p.add_argument("url")
    args = ap.parse_args(argv)

    if args.cmd == "estimate":
        print(ESTIMATE)
    elif args.cmd == "start":
        st, reason = start(detect_env() if args.env == "auto" else args.env)
        out = status_view(st)
        out["resumed"] = reason == "resumed"
        out["reason"] = reason
        out["notice"] = NOTICES[reason]
        print(json.dumps(out, ensure_ascii=False))
    elif args.cmd == "mark":
        st = _load_or_exit()
        mark(st, args.step, args.status, args.code, [c for c in args.connectors.split(",") if c])
        save_state(st)
        if args.status == "fail":
            print(FAILURES[st["steps"][args.step]["code"]][1])
        else:
            print(f"{progress(args.step)} 통과")
    elif args.cmd == "status":
        print(json.dumps(status_view(_load_or_exit()), ensure_ascii=False))
    elif args.cmd == "summary":
        print(build_summary(_load_or_exit()))
    elif args.cmd == "deliver":
        text = build_summary(_load_or_exit())
        print(text)
        print("COPIED" if copy_to_clipboard(text) else "MANUAL")
    elif args.cmd == "next-action":
        print(FAILURES.get(args.code, FAILURES["other"])[1])
    elif args.cmd == "engine-ping":
        out = engine_ping()
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    elif args.cmd == "dashboard-check":
        verdict, url = dashboard_check()
        print(f"{verdict} {url}" if url else verdict)
    elif args.cmd == "dashboard-save":
        try:
            dashboard_save(args.url)
        except ValueError:
            sys.exit("artifact 주소 모양이 아닙니다. 게시가 돌려준 주소를 그대로 넣으세요.")
        print("대시보드 주소를 저장했습니다.")
    elif args.cmd == "reset":
        try:
            os.remove(state_path())
        except FileNotFoundError:
            pass
        print("시험 상태를 지웠습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
