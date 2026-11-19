#!/usr/bin/python3
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
REPO = os.environ.get("review_repository", "").strip()
REPO_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
PROJECT = Path(os.environ.get("review_project", "").strip()).expanduser()
WORKFLOW_DATA = Path(os.environ.get("alfred_workflow_data") or
                     HOME / "Library/Application Support/Alfred/Workflow Data/local.harshal.trellis-pr-review")
DATA = WORKFLOW_DATA / (REPO.lower().replace("/", "_") if REPO_SLUG.fullmatch(REPO) else "unconfigured")
REFERENCES = tuple(Path(line.strip()).expanduser() for line in
                   os.environ.get("review_documents", "").splitlines() if line.strip())
SKILL = (HOME / ".codex/plugins/cache/mattpocock/mattpocock-skills/1.3.2"
         / "skills/engineering/code-review/SKILL.md")
PROVIDER = "codex"
MODEL = "gpt-6.2-sol"
EFFORT = "reasoningEffort=high"
BUSY = {"preparing", "queued", "starting", "running", "waiting", "submitted", "following"}
PR_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/"
                    r"([1-9][0-9]*)(?:[/?#][^\s<>()\[\]]*)?(?=$|[\s<>()\[\]])", re.IGNORECASE)

os.environ["PATH"] = os.pathsep.join((str(HOME / ".local/bin"), "/opt/homebrew/bin",
                                      "/usr/local/bin", os.environ.get("PATH", "/usr/bin:/bin")))


class ReviewError(Exception):
    pass


def command(*args, timeout=25, stdin=None, env=None):
    result = subprocess.run(args, input=stdin, text=True, capture_output=True, timeout=timeout, env=env)
    if result.returncode:
        error = (result.stderr.strip() or result.stdout.strip() or "Command failed.").splitlines()
        raise ReviewError(error[-1][:500])
    return result.stdout


def t3(*args, stdin=None):
    exe = shutil.which("t3") or shutil.which("t3", path=str(HOME / "bin"))
    if exe:
        return json.loads(command(exe, "thread", *args, "--json", stdin=stdin))

    # Alfred can also use the CLI shipped in the running Nightly app.
    for name in ("T3 Code (Nightly)", "T3 Code"):
        contents = Path(f"/Applications/{name}.app/Contents")
        executable = contents / "MacOS" / name
        if executable.is_file():
            entry = contents / "Resources/app.asar/apps/server/dist/bin.mjs"
            env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
            return json.loads(command(str(executable), str(entry), "thread", *args, "--json",
                                      stdin=stdin, env=env))
    raise ReviewError("Install the t3 command in T3 Code → Settings → About.")


def number(value):
    value = value.strip()
    match = re.fullmatch(r"#?([1-9][0-9]*)", value)
    return match[1] if match and len(match[1]) <= 10 else url_number(PR_URL.fullmatch(value))


def url_number(match):
    return match[2] if match and match[1].lower() == REPO.lower() and len(match[2]) <= 10 else ""


def selected_number(value):
    matches = list(PR_URL.finditer(value))
    return url_number(matches[0]) if len(matches) == 1 else ""


def read_record(pr):
    path = DATA / f"{pr}.json"
    return json.loads(path.read_text()) if pr and path.is_file() else {}


def save_record(pr, record):
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=DATA, delete=False) as file:
        json.dump(record, file)
    os.replace(file.name, DATA / f"{pr}.json")


def read_thread(record):
    return t3("show", record["thread"], "--messages", "10")


def refresh(pr, record):
    info = read_thread(record)
    thread = info["thread"]
    run = thread.get("activeRunId") or thread.get("latestRunId")
    if not run:
        return  # T3 may still be provisioning the worktree.
    if record["run"] and run != record["run"]:
        # A child review can wake this thread after the first turn ends.
        messages = info["messages"]
        if record["status"] != "following" or any(
            message["role"] == "user" and message["runId"] == run for message in messages
        ):
            raise ReviewError("This T3 thread has another run. Open it to check the review.")
    record["run"] = run
    record["status"] = thread["status"]
    record["link"] = thread.get("link") or record.get("link", "")
    if thread.get("pendingRequestCount"):
        record["status"] = "waiting"
    elif thread.get("pendingBackgroundTasks"):
        record["status"] = "following"
    elif thread["status"] == "completed":
        findings = [message["text"] for message in info["messages"]
                    if message["runId"] == run and message["role"] == "assistant"
                    and message.get("text", "").strip()]
        if findings:
            record["findings"] = findings[-1]
            record["reviewed_head"] = record["head"]
        else:
            record["status"] = "no_result"
    save_record(pr, record)


def git(directory, *args):
    return command("/usr/bin/git", "-C", str(directory), *args).strip()


def worktree(pr, record, thread, head):
    path = Path(thread.get("worktreePath") or "")
    if (not path.is_absolute() or path.resolve() == PROJECT.resolve() or
            not record["branch"].startswith(f"alfred-review/pr-{pr}-") or
            git(path, "branch", "--show-current") != record["branch"] or
            git(path, "rev-parse", "--path-format=absolute", "--git-common-dir") !=
            git(PROJECT, "rev-parse", "--path-format=absolute", "--git-common-dir")):
        raise ReviewError("The T3 review worktree is missing or has changed. Open it in T3.")
    current = git(path, "rev-parse", "HEAD")
    if current not in (record.get("checkout_head", record["head"]), head) or git(path, "status", "--porcelain"):
        raise ReviewError("The review worktree has local changes. Check it in T3 before retrying.")
    if current != head:
        git(path, "reset", "--keep", head)
    record["checkout_head"] = head
    save_record(pr, record)


def make_prompt(action, url, revision, record):
    prompt_file = "rereview.md" if action == "rereview" else "review.md"
    previous = record.get("reviewed_head")
    previous_head = f"\nLast completed review head: {previous}" if previous else ""
    findings = record.get("findings") if action == "rereview" else None
    prior_report = f"\nPrevious review report for reference:\n{findings}\n" if findings else ""
    paths = "\n".join(f"- {path}" for path in REFERENCES)
    reference_list = f"Reference documents:\n{paths}\n" if paths else ""
    return f"""Review target: {url}
PR base commit: {revision['baseRefOid']}
PR head commit: {revision['headRefOid']}{previous_head}

The current directory is the dedicated T3 worktree for this PR. Verify that HEAD equals the pinned PR head before reviewing. Use the pinned base as the fixed point for the three-dot diff. Keep the worktree unchanged and leave other checkouts alone. If HEAD differs, stop and report the mismatch.

{(HERE / prompt_file).read_text().strip()} Wait for both review axes to finish before issuing your final report.
{prior_report}

{reference_list}Review skill path: {SKILL}

Before posting each comment, check that GitHub still reports the pinned PR head. Stop posting if the head moved, and report that the PR needs a re-review. Anchor each comment to a line in the current GitHub diff and use the pinned head as the commit ID. Publish only the authorized review comments. Leave the PR's approval state, labels, and code unchanged.
"""


def launch(pr, action, record):
    if not PROJECT.is_absolute() or not PROJECT.is_dir():
        raise ReviewError("Set the local T3 project checkout in Alfred → Workflows → PR Review.")
    if action == "rereview" and not record.get("reviewed_head"):
        raise ReviewError("Run a first review before re-reviewing.")
    if action == "review" and record.get("reviewed_head"):
        raise ReviewError("A review already exists. Use Re-review to keep its context.")

    thread = None
    if record:
        thread = read_thread(record)["thread"]
        if thread.get("activeRunId") or thread["status"] in BUSY:
            raise ReviewError("A review is already running. Open it in T3 if it needs input.")
        if (thread["providerInstanceId"], thread["model"]) != (PROVIDER, MODEL):
            raise ReviewError("The review thread's model changed. Set it back to Codex GPT-6.2 Sol at high in T3.")

    for path in (*REFERENCES, SKILL):
        if not path.is_file() or not os.access(path, os.R_OK):
            raise ReviewError(f"Required context file is unavailable: {path}")
    url = f"https://github.com/{REPO}/pull/{pr}"
    revision = json.loads(command("gh", "pr", "view", url, "--json", "baseRefOid,headRefOid,state"))
    if revision["state"] != "OPEN":
        raise ReviewError("Choose an open pull request.")
    head, base = revision["headRefOid"], revision["baseRefOid"]
    if not all(re.fullmatch(r"[a-f0-9]{40}", sha) for sha in (head, base)):
        raise ReviewError("GitHub did not supply valid PR commit IDs.")
    remote = git(PROJECT, "remote", "get-url", "origin")
    if remote.lower().removesuffix(".git") not in (
            f"git@github.com:{REPO.lower()}", f"https://github.com/{REPO.lower()}"):
        raise ReviewError("The local checkout's origin does not match the configured repository.")
    git(PROJECT, "fetch", "--no-tags", "--no-write-fetch-head", "origin", base, head)

    prompt = make_prompt(action, url, revision, record)
    if thread and thread.get("worktreePath"):
        worktree(pr, record, thread, head)
        result = t3("send", record["thread"], "-", stdin=prompt)
    elif action == "review":
        record["branch"] = f"alfred-review/pr-{pr}-{uuid.uuid4().hex[:8]}"
        result = t3("start", str(PROJECT), "-", "--title", f"{REPO.rsplit('/', 1)[-1]} PR #{pr} review",
                    "--provider", PROVIDER, "--model", MODEL, "--option", EFFORT,
                    "--worktree", head, "--branch", record["branch"], stdin=prompt)
    else:
        raise ReviewError("The review worktree is unavailable. Open the thread in T3.")

    record.update(thread=result["threadId"], run=result["runId"], head=head,
                  status="submitted",
                  link=result.get("link") or record.get("link", ""))
    save_record(pr, record)


def thread_url(link):
    match = re.fullmatch(r"\[[^\n]+\]\(([^\s]+)\)", link)
    url = match[1] if match else link
    return url if url.startswith(("t3-thread://", "https://app.t3.codes/")) else ""


def render(pr, record, *, fill=False, error=""):
    state = record.get("status")
    active = state in BUSY
    reviewed = bool(record.get("reviewed_head"))
    statuses = {
        "waiting": "T3 needs input",
        "completed": "Review complete",
        "failed": "Review failed · open in T3",
        "interrupted": "Review stopped",
        "cancelled": "Review cancelled",
        "rolled_back": "Review rolled back",
        "no_result": "No findings received · open in T3",
    }
    status = statuses.get(state, "Reviewing…" if active else "")
    if status and record.get("head"):
        status += f" · {record['head'][:8]}"
    findings = record.get("findings", "")
    if findings and record.get("reviewed_head") != record.get("head"):
        findings = f"**Previous review**\n\n{findings}"
    link = thread_url(record.get("link", ""))
    fields = {
        "pr": {"enabled": True},
        "review": {"enabled": bool(pr) and not active and not reviewed},
        "rereview": {"enabled": reviewed and not active},
        "status": {"text": error or status},
        "findings": {"text": findings},
        "open": {"enabled": bool(link)},
        "copy": {"enabled": bool(record.get("findings"))},
    }
    if fill:
        fields["pr"]["text"] = pr
        fields["pr"]["focus"] = True
    return {
        "update": {"ids": fields},
        "variables": {"selected_pr": pr, "thread_url": link, "report": record.get("findings", "")},
        "pulse": {"interval": 2 if active else 0},
    }


def main(action, value):
    if action == "auto" and not value:
        return {}
    if not REPO_SLUG.fullmatch(REPO):
        return render("", {}, error="Set the GitHub repository in Alfred → Workflows → PR Review.")
    pr = selected_number(value) if action in ("init", "auto") else number(value)
    selection_error = "Select one PR link from the configured repository."
    if action == "init":
        if value:
            if not pr:
                return render("", {}, error=selection_error)
            view = render(pr, read_record(pr), fill=True, error="Opening review…")
            for field in ("pr", "review", "rereview"):
                view["update"]["ids"][field]["enabled"] = False
            view["pulse"]["interval"] = 0
            return view
        clipboard = command("/usr/bin/pbpaste", timeout=2).strip()
        recent = max(DATA.glob("[0-9]*.json"), key=lambda path: path.stat().st_mtime, default=None)
        pr = url_number(PR_URL.fullmatch(clipboard)) or (recent.stem if recent else "")
        return render(pr, read_record(pr), fill=True)
    if not pr:
        error = selection_error if action == "auto" else "Enter a PR number or URL from the configured repository."
        return render("", {}, error=error if value.strip() else "")

    record = read_record(pr)
    if action == "select" or (action == "poll" and record.get("status") not in BUSY):
        return render(pr, record)

    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / f"{pr}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {} if action == "poll" else render(pr, record, error="This review is being updated.")
        record = read_record(pr)
        try:
            if record.get("status") in BUSY:
                refresh(pr, record)
            if action == "auto" and record.get("status") not in BUSY:
                action = "rereview" if record.get("reviewed_head") else "review"
            if action in ("review", "rereview"):
                launch(pr, action, record)
        except (ReviewError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            return render(pr, record, error=str(error))
    return render(pr, record)


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")))
    except (ReviewError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(json.dumps(render("", {}, error=str(error))))
