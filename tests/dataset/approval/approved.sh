# Each line is one command line a session runs on its own, which the mod approves.
github-workflow push
github-workflow branch start fix-the-thing
github-workflow commit -m "Fix the thing" src/a.py tests/test_a.py
github-workflow draft --finding 7 --python .venv/bin/python --title "Fix it" --body-file body.md
github-workflow finding file --repository LucaKro/GitHubWorkflow --priority low --title "A title" --body-file finding.md
github-workflow finding prove 7 --test tests/test_proof.py
github-workflow describe --body-file body.md
github-workflow review reply 123 --body-file reply.md
github-workflow review addressed https://github.com/an-upstream-owner/project/pull/9#discussion_r77 --body-file changed.md
github-workflow push 2>&1 | tail -1
cd /some/checkout && github-workflow sync
github-workflow describe --title "Fix 5 things" --body-file body.md
github-workflow finding comment 7 --body-file /tmp/comment.md
github-workflow push 2>&1 | tail -n 20
github-workflow push 2>&1 | head -5
