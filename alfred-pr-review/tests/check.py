"""Exercise the two review rounds with real Git and simulated GitHub and T3."""
import importlib.util
import json
import plistlib
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "workflow/Review.alfredui/review.py"
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


if __name__ == "__main__":
    check()
