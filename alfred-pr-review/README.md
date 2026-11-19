# PR Review for Alfred

Start or repeat a GitHub pull request review from Alfred. T3 Code runs Codex GPT-6.2 Sol at high and keeps a separate Git checkout for each pull request.

## Set up

1. Open [PR Review.alfredworkflow](dist/PR%20Review.alfredworkflow?raw=true) and choose Import in Alfred 6 with Powerpack.
2. In Alfred → Workflows → PR Review, set the GitHub repository and the path to its local T3 Code project.
3. To include reference documents, add one local path per line in Reference Documents.

Keep T3 Code running. The local T3 CLI must support `t3 thread start --option`. The workflow can also use the CLI bundled with T3 Code on this Mac. Install the Matt Pocock code-review skill and sign in to GitHub with `gh auth login` before the first review.

## Use

Select a pull request link, press ⌘/, and choose Review or re-review PR. The action accepts a link or plain text containing one link from the configured repository. It starts a first review when no completed review exists. After a review completes, the action sends the follow-up prompt to the same thread. If a review is active, the action shows that run in Alfred.

To open the panel without starting a review, press ⌃⌥⌘R or type `prreview`. Enter a pull request number or URL. Press ⌘↩ to review or ⌘⇧↩ to re-review. Press ⌘O to open the thread in T3 Code or ⌘⇧C to copy the findings.

Starting a review authorizes the reviewer to post verified, important inline comments with your GitHub account. Keep the review thread on the configured model and effort. A re-review uses the thread's existing settings.

## Build and test

From this folder, run `python3 build.py` to package the workflow. Run `python3 tests/check.py` to test both review rounds with a temporary Git repository and simulated T3 and GitHub calls.
