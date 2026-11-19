"""Exercise the two review rounds with real Git and simulated GitHub and T3."""
import importlib.util
import json
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "workflow/Review.alfredui/review.py"
sys.path.insert(0, str(SOURCE.parent))
spec = importlib.util.spec_from_file_location("review", SOURCE)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def check():
    info = plistlib.loads((SOURCE.parents[1] / "info.plist").read_bytes())
    objects = {obj["uid"]: obj for obj in info["objects"]}
    assert not any(obj["type"].endswith(".hotkey") for obj in objects.values())
    keyword = next(obj for obj in objects.values() if obj["type"].endswith(".keyword"))
    assert keyword["config"]["keyword"] == "prreview" and keyword["config"]["argumenttype"] == 1
    trigger = next(obj for obj in objects.values() if obj["type"].endswith(".universalaction"))
    assert trigger["config"]["acceptsurls"] and trigger["config"]["acceptstext"]
    selection = objects[info["connections"][trigger["uid"]][0]["destinationuid"]]
    assert selection["config"]["variables"] == {"review_selection": "{query}"}
    panel = objects[info["connections"][selection["uid"]][0]["destinationuid"]]
    assert panel["type"].endswith(".alfredui")
    for obj in objects.values():
        if obj["type"].endswith(".external"):
            assert info["connections"][obj["uid"]][0]["destinationuid"] == panel["uid"]
    ui = json.loads(SOURCE.with_name("ui.json").read_text())
    assert ui["variablesconfig"]["review_selection"]["src"] == "variable"
    assert ui["variablesconfig"]["keyword_pr"]["src"] == "args[0]"
    assert any(event["triggers"] == "launched" and
               event["action"]["args"] == ["auto", "{var:review_selection}"]
               for event in ui["window"]["root"]["events"])

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        remote, repo, worktree = (root / name for name in ("remote", "repo", "worktree"))
        remote.mkdir()

        def git(path, *args):
            return subprocess.check_output(
                ["git", "-C", str(path), *args], text=True, stderr=subprocess.DEVNULL
            ).strip()

        def commit(branch, content):
            if git(remote, "symbolic-ref", "--short", "HEAD") != branch:
                git(remote, "switch", branch)
            (remote / "code").write_text(content)
            git(remote, "add", "code")
            git(remote, "commit", "-m", content)
            return git(remote, "rev-parse", "HEAD")

        git(remote, "init", "-b", "main")
        git(remote, "config", "user.email", "test@example.invalid")
        git(remote, "config", "user.name", "Workflow test")
        git(remote, "config", "commit.gpgsign", "false")
        base = commit("main", "base")
        git(remote, "branch", "pr")
        head = commit("pr", "first")
        git(root, "clone", "-b", "main", str(remote), str(repo))

        refs = [root / "context.html", root / "context.docx", root / "SKILL.md"]
        for ref in refs:
            ref.touch()
        run_id = "run-1"
        sent = []
        thread = {
            "providerInstanceId": "codex", "model": "gpt-6.2-sol",
            "worktreePath": str(worktree), "link": "t3-thread://v2/environment/thread",
            "status": "running", "activeRunId": run_id, "latestRunId": run_id,
        }

        def mock_command(*args, **kwargs):
            assert args[:3] == ("gh", "pr", "view"), args
            return json.dumps({"headRefOid": head, "baseRefOid": base, "state": "OPEN", "title": "Fix review target"})

        def mock_git(path, *args):
            if args == ("remote", "get-url", "origin"):
                return "git@github.com:example/repo.git"
            return git(path, *args)

        def mock_t3(action, *args, stdin=None):
            if action == "show":
                assert args[0] == "thread"
                return {"thread": thread, "messages": [
                    {"role": "assistant", "runId": run_id, "text": f"Findings for {run_id}"},
                ]}
            sent.append(stdin)
            if action == "start":
                assert args[args.index("--provider") + 1] == "codex"
                assert args[args.index("--model") + 1] == "gpt-6.2-sol"
                assert args[args.index("--option") + 1] == "reasoningEffort=high"
                assert args[args.index("--worktree") + 1] == head
                git(repo, "worktree", "add", "-b", args[args.index("--branch") + 1], str(worktree), head)
            else:
                assert action == "send" and args[0] == "thread"
                assert git(worktree, "rev-parse", "HEAD") == head
            return {"threadId": "thread", "runId": run_id, "link": thread["link"]}

        with patch.multiple(review, REPO="example/repo", PROJECT=repo, DATA=root / "state", REFERENCES=refs[:2], SKILL=refs[2],
                            command=mock_command, git=mock_git, t3=mock_t3):
            url = "https://github.com/example/repo/pull/42"
            selection = f"[Pull request]({url}#discussion)"
            assert review.number(f"{url}#discussion") == "42"
            assert not review.number("https://github.com/example/other/pull/42")
            assert review.main("auto", "") == {}
            assert review.main("auto", "#42")["update"]["ids"]["status"]["text"]
            assert review.main("auto", "https://github.com/example/other/pull/42")["update"]["ids"]["status"]["text"]
            assert review.main("auto", f"{url} {url}0")["update"]["ids"]["status"]["text"]
            assert not sent
            assert review.main("init", "", "42")["update"]["ids"]["pr"]["text"] == "42"
            assert not sent
            assert not review.main("select", "#42")["update"]["ids"]["rereview"]["enabled"]
            assert review.main("init", url)["update"]["ids"]["pr"]["text"] == "42"
            assert review.main("auto", url)["pulse"]["interval"] == 2
            assert review.main("auto", selection)["pulse"]["interval"] == 2
            assert len(sent) == 1
            assert all(str(ref) in sent[0] for ref in refs)
            assert review.main("review", "#42")["update"]["ids"]["status"]["text"].startswith("A review")
            first_head = head
            thread.update(status="completed", activeRunId=None, pendingBackgroundTasks=[{"awaited": True}])
            assert review.main("poll", "42")["pulse"]["interval"] == 2
            run_id = "run-1-final"
            thread.update(latestRunId=run_id, pendingBackgroundTasks=[])
            assert review.main("poll", "42")["variables"]["report"] == "Findings for run-1-final"
            assert review.read_record("42")["reviewed_head"] == first_head
            head = commit("pr", "updated")
            run_id = "run-2"
            (worktree / "untracked").touch()
            result = review.main("auto", selection)
            assert "local changes" in result["update"]["ids"]["status"]["text"]
            assert len(sent) == 1
            (worktree / "untracked").unlink()
            assert review.main("auto", selection)["pulse"]["interval"] == 2
            assert f"Last completed review head: {first_head}" in sent[-1]
            assert "Re-review this PR" in sent[-1]
            assert "Findings for run-1-final" in sent[-1]
            thread.update(status="completed", latestRunId=run_id)
            assert review.main("poll", "42")["variables"]["report"] == "Findings for run-2"
            assert review.read_record("42")["thread"] == "thread"
            assert review.read_record("42")["reviewed_head"] == head
            assert git(repo, "rev-parse", "HEAD") == base

            dashboard = review.main("init", "")
            fields = dashboard["update"]["ids"]
            assert fields["detailTitle"]["text"] == "PR #42 · Fix review target"
            rows = fields["history"]["data"]["src"]
            assert [row["historyTitle.text"] for row in rows] == ["#42    Re-review", "#42    Review"]
            assert fields["countPrs"]["text"] == "1"
            assert fields["countRounds"]["text"] == "2"
            assert fields["countRereviews"]["text"] == "1"
            previous = review.main("history", rows[1]["uid"], rows[0]["uid"])
            assert previous["variables"]["report"] == "Findings for run-1-final"
            assert review.main("history", rows[0]["uid"], rows[0]["uid"]) == {}
            assert len(sent) == 2

            review.save_record("43", {"status": "interrupted", "reviewed_head": first_head,
                                      "head": head, "findings": "Older saved report"})
            legacy = review.main("history", "43:saved")
            assert legacy["variables"]["report"] == "Older saved report"
            fields = review.history_fields("")
            assert fields["countPrs"]["text"] == "2" and fields["countRounds"]["text"] == "3"
            assert fields["countRereviews"]["text"] == "1"
            assert len(fields["history"]["data"]["src"]) == 4
    print("Keyword, review history, and both review rounds passed with one T3 thread per PR.")


def check_activity():
    head = "a" * 40
    viewer = {"login": "reviewer"}
    contributor = {"login": "contributor"}
    url = "https://github.com/example/repo/pull/42"

    def comment(id, author, message, created="2026-01-02T09:00:00Z"):
        return {"url": f"{url}#discussion_r{id}", "author": author, "bodyText": message, "createdAt": created}

    def thread(root, replies=(), *, resolved=False, outdated=False):
        return {"path": "example.py", "isResolved": resolved, "isOutdated": outdated,
                "first": {"nodes": [root]}, "recent": {"nodes": [root, *replies]}}

    threads = [thread(comment(1, viewer, "Return the empty result"), [comment(2, contributor, "Updated this")]),
               thread(comment(3, viewer, "Resolve this"), resolved=True),
               thread(comment(4, viewer, "Old line"), outdated=True),
               thread(comment(5, contributor, "Another inline comment"))]
    pull = {"title": "Example change", "state": "OPEN", "headRefOid": head, "viewerDidAuthor": False,
            "reviewDecision": "REVIEW_REQUIRED", "reviews": {"nodes": []},
            "comments": {"totalCount": 1, "nodes": [comment(6, contributor, "New tests are ready")]},
            "reviewThreads": {"totalCount": len(threads), "pageInfo": {"hasNextPage": False}, "nodes": []}}
    posts = []

    def mock_command(*args, **kwargs):
        if args[4] == "graphql":
            pull["reviewThreads"].update(totalCount=len(threads), nodes=threads)
            return json.dumps([{"data": {"viewer": viewer, "repository": {"pullRequest": pull}}}])
        assert args[4:10] == ("--method", "POST", "repos/example/repo/pulls/42/reviews", "-f", "event=APPROVE", "-f")
        assert args[10] == f"commit_id={head}"
        posts.append(args)
        pull["reviews"]["nodes"].append({"author": viewer, "state": "APPROVED", "commit": {"oid": head}})
        return json.dumps({"state": "APPROVED", "commit_id": head, "html_url": f"{url}#pullrequestreview-1"})

    with tempfile.TemporaryDirectory() as directory, patch.multiple(review, REPO="example/repo", DATA=Path(directory),
                                                                     command=mock_command):
        review.save_record("42", {"status": "completed", "reviewed_head": head, "rounds": [
            {"id": "saved", "kind": "review", "status": "completed", "head": head,
             "started": "2026-01-03T09:00:00+00:00", "findings": "No new findings."},
        ]})

        def view(action="activity", token=""):
            result = review.main(action, "42", "42:saved", token)
            return result["update"]["ids"], result["variables"]

        fields, variables = view()
        report = fields["findings"]["text"]
        assert "1 open · 1 resolved · 1 outdated" in report and "Updated this" in report
        assert "New tests are ready" in report and "Another inline comment" in report
        assert "No inline findings posted by you" in report and fields["approve"]["enabled"]
        token = variables["approval_token"]
        assert token == f"reviewer:{head}" and not posts

        pull["headRefOid"] = "b" * 40
        fields, _ = view("approve", token)
        assert "New commits since review" in fields["findings"]["text"] and not fields["approve"]["enabled"]
        pull["headRefOid"] = head
        threads.append(thread(comment(7, viewer, "New finding", "2026-01-03T09:00:01Z")))
        fields, _ = view("approve", token)
        assert "1 inline finding posted" in fields["findings"]["text"] and not fields["approve"]["enabled"]
        threads.pop()
        pull["viewerDidAuthor"] = True
        assert not view("approve", token)[0]["approve"]["enabled"]
        pull["viewerDidAuthor"] = False
        assert not view("approve", f"other:{head}")[0]["approve"]["enabled"]
        assert not view("approve")[0]["approve"]["enabled"] and not posts

        fields, _ = view("approve", token)
        assert "Approved on GitHub" in fields["findings"]["text"] and not fields["approve"]["enabled"]
        assert not view("approve", token)[0]["approve"]["enabled"] and len(posts) == 1
        threads.clear()
        pull["comments"] = {"totalCount": 0, "nodes": []}
        assert "No inline or discussion comments on this PR" in view()[0]["findings"]["text"]
        pull["reviewThreads"]["pageInfo"]["hasNextPage"] = True
        assert "GitHub activity unavailable" in view()[0]["findings"]["text"]
        assert not view("approve", token)[0]["approve"]["enabled"] and len(posts) == 1
    print("Activity and approval passed. Changed commits, posted findings and duplicate approval were blocked.")


if __name__ == "__main__":
    check()
    check_activity()
