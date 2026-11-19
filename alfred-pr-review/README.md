# PR Review for Alfred

Start or repeat a GitHub pull request review from Alfred. T3 Code runs Codex GPT-6.2 Sol at high and keeps a separate Git checkout for each pull request.

## Set up

1. Open [PR Review.alfredworkflow](dist/PR%20Review.alfredworkflow?raw=true) and choose Import in Alfred 6 with Powerpack.
2. In Alfred → Workflows → PR Review, set the GitHub repository and the path to its local T3 Code project.
3. To include reference documents, add one local path per line in Reference Documents.

Keep T3 Code running. The local T3 CLI must support `t3 thread start --option`. The workflow can also use the CLI bundled with T3 Code on this Mac. Install the Matt Pocock code-review skill and sign in to GitHub with `gh auth login` before the first review.

## Use

Select a pull request link, press ⌘/, and choose Review or re-review PR. The action accepts a link or plain text containing one link from the configured repository. It starts a first review when no completed review exists. After a review completes, the action sends the follow-up prompt to the same thread. If a review is active, the action shows that run in Alfred.

Type `prreview` to open the dashboard. To open a specific pull request, type its number after the keyword, for example `prreview 123`. The keyword opens the panel without starting a review.

Select a round in History to read its findings. Filter by pull request number or title. The dashboard counts pull requests reviewed, completed rounds, and completed re-reviews. Records from older versions include the saved report and latest attempt when available.

Choose Activity to see recent GitHub discussion and inline comments. It shows whether your threads are open, resolved, or outdated and quotes recent replies. The commit indicator shows when new code arrived after the last review. Choose Activity again to refresh.

After a completed review of the current commit, Activity checks for new inline findings from your GitHub account. If it finds none, choose Approve PR and confirm. The workflow checks the account, comments, and commit again before it submits the approval. Choose Report to return to the saved findings.

Press ⌘↩ to review or ⌘⇧↩ to re-review. Press ⌘O to open the thread in T3 Code or ⌘⇧C to copy the displayed findings.

Starting a review authorizes the reviewer to post verified, important inline comments with your GitHub account. Keep the review thread on the configured model and effort. A re-review uses the thread's existing settings.

## Build and test

From this folder, run `python3 build.py` to package the workflow. Run `python3 tests/check.py` to test both review rounds with a temporary Git repository and simulated T3 and GitHub calls.
