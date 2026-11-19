"""GitHub activity and commit-specific approval for the selected pull request."""
import json
import re
from datetime import datetime
from html import escape
from urllib.parse import urlsplit

QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $endCursor: String) {
  viewer { login }
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      title state headRefOid viewerDidAuthor reviewDecision
      comments(last: 6) {
        totalCount
        nodes { author { login } bodyText createdAt url }
      }
      reviews(last: 30, states: [APPROVED, CHANGES_REQUESTED, DISMISSED]) {
        nodes { author { login } state commit { oid } }
      }
      reviewThreads(first: 50, after: $endCursor) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes {
          path isResolved isOutdated
          first: comments(first: 1) {
            totalCount
            nodes { author { login } bodyText createdAt url }
          }
          recent: comments(last: 5) {
            nodes { author { login } bodyText createdAt url }
          }
        }
      }
    }
  }
}
"""


def load(command, repo, pr):
    owner, name = repo.split("/")
    raw = command("gh", "api", "--hostname", "github.com", "graphql", "--paginate", "--slurp",
                  "-f", f"query={QUERY}", "-f", f"owner={owner}", "-f", f"repo={name}",
                  "-F", f"number={pr}", timeout=15)
    pages = json.loads(raw)
    if not pages or any(page.get("errors") for page in pages):
        raise ValueError("GitHub could not load the complete PR activity.")
    pulls = [page["data"]["repository"]["pullRequest"] for page in pages]
    if not all(pulls):
        raise ValueError("GitHub could not find this pull request.")
    pull = pulls[-1]
    if any(page["headRefOid"] != pull["headRefOid"] for page in pulls):
        raise ValueError("The PR changed while loading activity. Refresh to try again.")
    threads = [thread for page in pulls for thread in page["reviewThreads"]["nodes"]]
    if (pull["reviewThreads"]["pageInfo"]["hasNextPage"] or
            len(threads) != pull["reviewThreads"]["totalCount"]):
        raise ValueError("The review threads changed while loading. Refresh to try again.")
    return pages[-1]["data"]["viewer"]["login"], pull, threads


def author(item):
    return (item.get("author") or {}).get("login", "")


def first_comment(thread):
    return next(iter(thread["first"]["nodes"]), {})


def latest_reviewed(entries, head):
    return next((entry for entry in reversed(entries)
                 if entry["status"] == "completed" and entry["head"] == head), None)


def own_threads(threads, viewer):
    return [thread for thread in threads if author(first_comment(thread)).lower() == viewer.lower()]


def approved(pull, viewer):
    last = next((review for review in reversed(pull["reviews"]["nodes"])
                 if author(review).lower() == viewer.lower()), {})
    return last.get("state") == "APPROVED" and (last.get("commit") or {}).get("oid") == pull["headRefOid"]


def round_comment_count(threads, entry):
    if entry is None:
        return None
    if not entry.get("started"):
        return None if threads else 0
    since = datetime.fromisoformat(entry["started"]).replace(microsecond=0)
    return sum(datetime.fromisoformat(first_comment(thread)["createdAt"].replace("Z", "+00:00")) >= since
               for thread in threads)


def eligibility(viewer, pull, threads, entries, busy):
    head = pull["headRefOid"]
    if not viewer or not re.fullmatch(r"[0-9a-f]{40}", head):
        return "GitHub did not confirm the account and commit."
    if pull["state"] != "OPEN":
        return "This PR is closed."
    if pull["viewerDidAuthor"]:
        return "GitHub does not allow approval of your own PR."
    if approved(pull, viewer):
        return "You already approved this commit."
    if busy:
        return "A review is in progress."
    latest = next((entry for entry in reversed(entries) if entry["status"] == "completed"), None)
    if latest is None or latest["head"] != head:
        return "Complete a review of the current commit to approve here."
    count = round_comment_count(own_threads(threads, viewer), latest)
    if count is None:
        return "The saved review has no comment timestamps. Run a re-review to check."
    if count:
        return "This review posted inline findings."
    return ""


def excerpt(text, limit=155):
    flat = " ".join((text or "").split())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return escape(flat).translate(str.maketrans({"[": "&#91;", "]": "&#93;", "{": "&#123;",
                                                "}": "&#125;", "*": "&#42;", "`": "&#96;"}))


def link(comment, label):
    url = urlsplit(comment.get("url", ""))
    if url.scheme == "https" and url.netloc == "github.com" and not re.search(r"[\s<>()]", url.geturl()):
        return f"[{label}]({url.geturl()})"
    return label


def summarize(pull, viewer, threads, entries, reviewed_head):
    own = own_threads(threads, viewer)
    resolved = sum(thread["isResolved"] for thread in own)
    outdated = sum(thread["isOutdated"] and not thread["isResolved"] for thread in own)
    opened = len(own) - resolved - outdated
    replied = sum(any(author(reply) and author(reply).lower() != viewer.lower()
                      and reply["url"] != first_comment(thread)["url"]
                      for reply in thread["recent"]["nodes"]) for thread in own)
    head = pull["headRefOid"]
    if reviewed_head and reviewed_head != head:
        lead = f"**New commits since review** · reviewed `{reviewed_head[:8]}` · current `{head[:8]}`"
    else:
        lead = f"**{'Current commit reviewed' if reviewed_head else 'Current commit'}** · `{head[:8]}`"

    parts = [lead, f"**Your inline threads** · {opened} open · {resolved} resolved · {outdated} outdated",
             f"{len(threads)} inline threads and {pull['comments']['totalCount']} discussion comments on this PR."]
    decision = {"APPROVED": "Approved", "CHANGES_REQUESTED": "Changes requested",
                "REVIEW_REQUIRED": "Review required"}.get(pull.get("reviewDecision"))
    if decision:
        parts.append(f"GitHub review status · **{decision}**")
    if not threads and not pull["comments"]["totalCount"]:
        parts.append("No inline or discussion comments on this PR.")
    if replied:
        parts.append(f"Recent replies on {replied} of your threads.")
    entry = latest_reviewed(entries, head)
    count = round_comment_count(own, entry)
    if count == 0:
        parts.append("**No inline findings posted by you since this review began**" if entry.get("started")
                     else "**No inline findings from your account on this PR**")
    elif count:
        parts.append(f"**{count} inline finding{'s' if count != 1 else ''} posted by you since this review began**")
    if approved(pull, viewer):
        parts.append("**You approved the current commit.**")

    if own:
        lines = []
        for thread in sorted(own, key=lambda item: (item["isResolved"], item["isOutdated"],
                                                   first_comment(item).get("createdAt", "")))[:5]:
            root = first_comment(thread)
            state = "Resolved" if thread["isResolved"] else "Outdated" if thread["isOutdated"] else "Open"
            replies = [comment for comment in thread["recent"]["nodes"]
                       if comment["url"] != root["url"] and author(comment).lower() != viewer.lower()]
            line = f"- **{state}** · {link(root, excerpt(thread['path'], 58))} · {excerpt(root['bodyText'])}"
            if replies:
                reply = replies[-1]
                line += f"\n  - {link(reply, excerpt(author(reply) or 'Reply'))} replied · {excerpt(reply['bodyText'], 110)}"
            lines.append(line)
        parts.append("#### Your review threads\n" + "\n".join(lines))

    others = [thread for thread in threads if author(first_comment(thread)).lower() != viewer.lower()]
    if others:
        lines = []
        for thread in sorted(others, key=lambda item: first_comment(item).get("createdAt", ""), reverse=True)[:4]:
            root = first_comment(thread)
            if root:
                lines.append(f"- {link(root, excerpt(thread['path'], 58))} · "
                             f"{excerpt(author(root) or 'GitHub')} · {excerpt(root['bodyText'], 110)}")
        if lines:
            parts.append("#### Other inline comments\n" + "\n".join(lines))

    discussion = pull["comments"]["nodes"]
    if discussion:
        lines = [f"- {link(comment, excerpt(author(comment) or 'GitHub'))} · "
                 f"{excerpt(comment['createdAt'][:10])} · {excerpt(comment['bodyText'])}"
                 for comment in reversed(discussion)]
        parts.append("#### Recent discussion\n" + "\n".join(lines))
    return "\n\n".join(parts)


def approve(command, repo, pr, head):
    raw = command("gh", "api", "--hostname", "github.com", "--method", "POST",
                  f"repos/{repo}/pulls/{pr}/reviews", "-f", "event=APPROVE",
                  "-f", f"commit_id={head}", timeout=15)
    result = json.loads(raw)
    if result.get("state") != "APPROVED" or result.get("commit_id") != head:
        raise ValueError("GitHub did not confirm approval for the reviewed commit. Refresh Activity.")
    return result
