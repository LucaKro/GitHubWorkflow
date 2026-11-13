# How the workflow works

A walk through the workflow as a session meets it: what it is given when it starts, how
it changes git and GitHub, and what stops it from doing so in any other way.
[REQUIREMENTS.md](REQUIREMENTS.md) says what the workflow has to do and why; this file
shows how the parts fit together.

## The idea

A Claude Code session reads git and GitHub freely, but writes to them only through one
program, `github-workflow`. Each of its commands checks the rules before it writes: only
repositories owned by `LucaKro`, never the default branch directly, never a force push,
no commit crediting an assistant. Everything else exists to make that hold and to make it
comfortable:

| Part | What it does | Where |
|---|---|---|
| Session start | Loads the notes, reports the repository's state, brings branches up to date | `hooks/session-start.sh`, `session_start.py`, `report.py` |
| Guard | Denies a direct write to git or GitHub before it runs | `hooks/guard.sh`, `guard.py`, `coarse_guard.py` |
| Commands | The only way to write | `__main__.py`, `command_line.py`, `command_steps.py` |
| Approval | Lets a session run its own commands without a permission prompt | `hooks/approval.ts`, `approval.py` |
| Push hook | Checks every push from a session, however it was started | `push_hook.py`, `templates/pre_push.sh` |
| Notes branch | Keeps notes, progress and the queues GitHub Actions work through | `notes/`, `workflow_templates.py` |

Git and GitHub themselves are modelled in [`domain_model/`](domain_model); the workflow
package holds only the rules and the commands built on that model.

## 1. A session starts

The `SessionStart` hook installs the runtime (a virtual environment built from the
plugin's own source, with no download) and then runs `github_workflow.session_start` in
the checkout. That does four things.

1. **Loads the notes.** It fetches the branch `github-workflow/notes` from your
   repository and writes two sections into `CLAUDE.local.md`, which Claude Code reads
   like `CLAUDE.md`: your standing notes (`notes.md`) and the progress of the checked-out
   branch (`progress/<branch>.md`). The file is added to `.git/info/exclude`, so it is
   never committed.
2. **Installs the push hook** into the checkout (see [section 7](#7-what-stops-a-direct-write)).
3. **Reports the repository's state**, each section computed in a process of its own so
   that one failing section cannot hide the others:
   - `setup`: what is turned off on the repository (issues, Discussions, Actions), with
     the link to turn it on. The workflow never changes settings itself.
   - `pull-requests`: one line per open pull request, with its signals (failed checks,
     conflicts, unresolved threads). Only the fact is shown; `github-workflow details
     <number>` shows the detail.
   - `findings`: the open findings, grouped by stage and named with their priority.
   - `cleanup`: how many branches are ready for deletion.
   - `freshness`: what was brought up to date (see [section 4](#4-keeping-branches-up-to-date)).
   - `upstream-merges`: fork pull requests whose upstream pull request was merged, which
     are closed here.
4. **Tells the model how to behave**: the notes begin with a short header listing the
   commands and the rules (file findings on your own, never run `upstream`, never get
   around a refusal).

If the hook ran too early or was cut off, the first prompt (`UserPromptSubmit`) reports
instead. The session start never fails the session: whatever goes wrong becomes one red
line.

## 2. Doing a piece of work

The usual path from a task to a pull request:

```bash
github-workflow branch start fix-parser          # from GitHub's default branch
# ... edit files, run tests ...
github-workflow commit -m "Fix the parser" src/parser.py tests/test_parser.py
github-workflow push
github-workflow draft --title "Fix the parser" --body-file /tmp/description.md
```

What each step checks:

- **`branch start <name> [--on <branch>]`** fetches the base from your remote, creates the
  branch from it and checks it out. A base your fork lacks, such as an upstream release
  branch, is fetched from the repository it was forked from. Started from the default
  branch, it also fast-forwards your local default branch.
- **`commit -m <message> <paths>`** stages exactly the paths given and commits them as
  you. It refuses on the default branch, on a detached `HEAD`, during a merge, and when
  the author, committer or a `Co-authored-by:` trailer names an assistant. It adds the
  line "Made with AI assistance" itself.
- **`push`** pushes the work branch to your remote and sets its upstream. Never forced.
- **`draft`** opens a draft pull request from the pushed branch onto the default branch.
  It labels every issue the description closes (`Fixes #12`) `pull request opened`. With
  `--on <number>` it stacks the draft on another pull request, using GitHub's native
  stacks; with `--replaces <number>` it closes the pull request it replaces.

Afterwards, on the work branch's own pull request, a session may do these without asking:

```bash
github-workflow describe --title "..." --body-file /tmp/description.md
github-workflow label --add bug --remove wip
github-workflow review list
github-workflow review reply <comment id> --body-file /tmp/reply.md
github-workflow review resolve <comment id>      # only once the fix is pushed
```

`describe <number>` rewrites another pull request, and `stack on <below> <above>` moves
one in a stack. Both are your decisions: a session runs them only when you said so.

Every command prints one line saying what it did. A refusal says why and what to run
instead, never a traceback.

## 3. Review, and what a session may close

Review threads are read through whichever API the place reaches: GraphQL on your machine
and in Actions, the proxy's REST routes in a cloud session. `review list` shows each
thread with the identifier of its first comment, which `review reply` and `review
resolve` take.

A session closes things on its own only in these cases, always labelled `closed by
session`, with a comment saying why, and entered in the repository's "Session log"
discussion:

- a pull request it discards (`branch discard`) or replaces (`draft --replaces`),
- a fork's pull request whose upstream pull request was merged,
- a finding whose fix is merged and whose proof test now passes (`finding close`).

Nothing is ever deleted except branches, by `cleanup`.

## 4. Keeping branches up to date

At session start, and before `push`, `draft` and `describe` of the own pull request, the
workflow brings two things up to date without being asked:

- On a fork, the default branch is fast-forwarded to the upstream's when it is behind and
  has no commits of its own.
- The work branch is merged with the branch its pull request targets, when it is behind,
  the working tree is clean and `git merge-tree` shows no conflict.

It never rebases and never forces. What it cannot do is reported, for the session to
settle with `sync`:

| Command | What it does |
|---|---|
| `sync` | Follows GitHub's copy of the checked-out branch: fast-forward, or move to the branch GitHub rebased when every local commit had been pushed, even after a plain `git fetch` |
| `sync --base` | Merges GitHub's default branch into the work branch |
| `sync --on <number>` | Merges another open pull request's branch, to build on it |
| `sync --upstream` | Fast-forwards a fork's default branch to its upstream's |
| `sync --continue <files>` | Commits a conflicting merge once the files are resolved |
| `sync --abort` | Undoes a conflicting merge |

A conflicting merge is left in progress with its files named. Until it is finished or
undone, nothing is committed or pushed on the branch.

## 5. Findings

A finding is something a session notices outside its current work. It is filed as an
issue and not acted on.

```bash
github-workflow finding file --priority medium --title "..." --body-file /tmp/finding.md
github-workflow finding file ... --test tests/test_shows_it.py   # filed already proven
github-workflow finding list
```

Its life is carried by labels:

| Label | Meaning | Who sets it |
|---|---|---|
| `finding: unreviewed` | Filed, waiting for you | the session, when filing |
| `finding: accepted` | You confirmed it | you (on GitHub, or `finding accept` on your word) |
| `finding: shelved` | Set aside for now | you |
| `finding: incorrect` | Rejected; closed as not planned | you |
| `finding: proven` / `finding: unproven` | Whether a test shows it | the code, after running the test |
| `priority: critical` … `priority: low` | How urgent | the session, when filing |

**Proof.** `finding prove <number> --test <file>` exports the default branch as GitHub
has it into a scratch directory, adds the test and runs it with pytest. Only a test that
fails there, and is not merely broken, proves the finding. The test is posted on the
issue with the commit it failed on; it is never committed. `--on <pull request or
branch>` runs it on another branch.

**Working on one** needs your word, and the finding accepted and proven:

```bash
github-workflow finding recheck 12                 # does the proof still fail?
github-workflow draft --finding 12 --title "..." --body-file /tmp/description.md
# ... after the pull request is merged ...
github-workflow finding close 12 --fixed-by 34     # closes only if the proof now passes
```

What the workflow itself refused unnecessarily is filed the same way on this repository,
from any session, with `--repository LucaKro/GitHubWorkflow`.

An **idea** is not a finding. `idea file` queues it on the notes branch, and the
repository's Actions post it to Discussions. A session files one only when you ask.

## 6. Forks and their upstream

On a fork, a draft's description ends with the command line that opens it upstream:

```bash
github-workflow upstream LucaKro/<fork> <branch>
```

Only you run that. The guard denies it to a session, and the command itself refuses
where Claude Code's marker variable is set. It opens the pull request upstream, links the
two and labels the fork's one `opened upstream`.

From then on `review list` also shows the upstream pull request's reviews and threads.
On your machine they are read directly. A cloud session cannot reach the upstream, so it
writes a request to the notes branch; an Actions workflow there reads GitHub's answers
and saves them, and the session replays them. Nothing is ever written upstream: after
changing something for an upstream comment, the session says so on the fork's pull
request with `review addressed <comment number or address> --body-file <what changed>`.

`clone <owner/name>` clones any repository to read it. Somebody else's goes into the
plugin's data directory and carries the push hook, so nothing can be pushed from it.

## 7. What stops a direct write

Four layers, from the first to the last resort:

1. **The guard** (`PreToolUse` hook) reads every Bash command line, file write and GitHub
   tool call before it runs. It looks through shells and wrappers (`bash -c`, `env`,
   `timeout`, `eval`, subshells), and any other program given one of them (`stdbuf git
   push`, `trap 'git push' EXIT`), for `git`, `gh`, `curl` and `wget`. Text in single
   quotes is text: `echo 'run $(git push)'` only prints.
   - Git and `gh` are judged by an allowlist of reading forms: `git status`, `git log`,
     `git fetch`, `gh pr view` pass; anything else counts as writing.
   - `curl` and `wget` may read GitHub but not send to it.
   - Writing git's configuration or hooks with a file tool, a redirection or a program
     such as `rm` or `sed -i` is denied.
   - `git apply --check` and `--stat` pass; applying a patch does not. `git worktree add
     --detach <dir> <commit>` gives a second copy at a commit to read and test in, and
     `remove` and `prune` tidy it away; a worktree on a branch is denied.
   - A command it cannot see into (a program named by `$variable`, a shell reading its
     input, `xargs git`, `curl -K` or an address in `$URL`) is denied and shown to you.
   - A denial names the workflow command that does the job, when there is one.
2. **Fallbacks.** When the runtime is broken, the guard runs from the plugin's source on
   the standard library alone. When that fails too, a coarse guard denies every call
   naming `git`, `gh`, `curl` or `wget`. Only when nothing runs is every call blocked.
3. **The push hook** in the checkout catches a push started any other way, such as from a
   script: it refuses a push to somebody else's repository or to the default branch. It
   checks only pushes from a session (where `CLAUDECODE` is set); your own pass.
4. **The commands' own checks** (`WritePolicy` and each step) refuse before writing.

The guard catches accidents, not intent. A write to GitHub's API from a script is not
seen by any layer; only a token scoped to your repositories stops that, at GitHub.

**Permission prompts.** The plugin's mod (`hooks/approval.ts`) approves a Bash call that
is exactly one workflow command a session may run on its own, with at most `cd` before it
and `head` or `tail` filtering its output after it, and every file it is given inside the
working or the temporary directory. Commands that are your decision (`finding accept`,
`describe <number>`, `stack on`) are never approved this way, so Claude Code asks you.

## 8. Notes, progress and the notes branch

`CLAUDE.local.md` holds a block the workflow owns. A session edits only between the
markers of a section; the `Stop` and `SessionEnd` hooks save the edits to the notes
branch after every turn, since a cloud container can disappear without the session
ending. `notes save` does the same by hand. A save that fails is shown to you and the
edits stay in the file.

The notes branch (`github-workflow/notes`) also carries what Actions do for a session
that cannot do it itself:

| On the notes branch | What an Actions workflow does with it |
|---|---|
| `ready-for-deletion.md` | Deletes each listed branch while it is still at the listed commit |
| `discussion-posts/` | Posts queued ideas and session-log entries to Discussions |
| `upstream-review-requests/` | Reads an upstream pull request's reviews and saves the answers |

These workflows live only on the notes branch, never on the default branch or upstream.

## 9. Cleaning up

A branch is ready for deletion when its pull request is closed or merged, or it was
marked with `branch discard`, and it is still at the commit it had then. The default
branch and the notes branch are never deleted, nor a branch with an open pull request
from or into it. `cleanup` deletes the ready branches in one push, each under a lease on
its commit. Where the session may not delete branches, as in a cloud session, it lists
them on the notes branch for the Actions workflow.

## 10. Who decides what

| A session, on its own | A session, when you say so | Only you |
|---|---|---|
| start, switch and discard branches; commit; push | accept, shelve, reject, edit or prioritize a finding | open a pull request upstream (`upstream`) |
| open drafts; describe, label and answer reviews on its own pull request | describe another pull request | change repository settings |
| sync and merge its branch; fast-forward a fork's default branch | change a stack (`stack on`) | merge pull requests |
| file, prove, recheck and comment on findings; close a fixed one | post an idea | set `pull request: shelved` |
| clone to read; clean up branches; save notes | set up the label workflow (`finding automate`) | unresolve a thread |

## 11. Finding your way in the code

| To change | Look in |
|---|---|
| A command's words, arguments or who may run it | `command_line.py` (`RunnableCommand`) |
| What a command builds from the session | `command_steps.py` (one `CommandStep` per command) |
| Branches, commits, pushes, drafts, sync | `work.py` |
| The rules every write passes | `policy.py`, `remotes.py`, `settings.py` |
| Findings and proofs | `findings.py`, `proofs.py`, `label_events.py` |
| The own pull request: labels and review threads | `own_pull_request.py` |
| Forks: upstream proposals, following merges, upstream reviews | `upstream.py`, `upstream_reviews.py`, `freshness.py` |
| Cleanup and discarded branches | `cleanup.py` |
| The session start report | `session_start.py`, `report.py`, `report_lines.py`, `pull_request_overview.py` |
| Notes | `notes/` |
| What the guard allows | `guard.py` here; the reading forms in `domain_model/git/reading.py` and `domain_model/github/reading_calls.py` |
| The Actions workflows on the notes branch | `workflow_templates.py`, `templates/` |
| The runtime install and the launcher | `install.py`, `plugin.py`, `hooks/runtime.sh` |
