# Each line is one command line the guard lets through.
git status --short
git log --oneline -5 main..feature
git -C /some/checkout diff HEAD~1
git --no-pager show HEAD:README.md
git branch
git branch -a --contains HEAD
git branch --show-current
git remote -v
git remote get-url origin
git config --get user.name
git config user.name
git config --global user.email
git config user.name; git config user.email
git stash list
git fetch origin
git fetch --quiet origin main
git ls-remote origin refs/heads/main
cd /some/checkout && git status | head -5
grep -rn "git push" src
gh pr view 9
gh pr checks 10
gh issue list --state open
gh label list --repo LucaKro/rviz --limit 30 --json name --jq '.[].name'
gh run view 123 --log
gh api repos/LucaKro/GitHubWorkflow/pulls
gh api -X GET repos/LucaKro/GitHubWorkflow
gh api -X GET search/issues -f q='is:pr is:open author:LucaKro'
gh api --method GET repos/LucaKro/GitHubWorkflow/pulls -f state=open
gh api -XGET search/issues -F per_page=100 -f q=repo:LucaKro/GitHubWorkflow
gh api --method=GET repos/LucaKro/GitHubWorkflow/issues -f labels=finding
gh search prs --author LucaKro
curl -fsSL https://raw.githubusercontent.com/LucaKro/GitHubWorkflow/main/README.md
curl -s https://api.github.com/repos/LucaKro/GitHubWorkflow
curl -X POST https://example.com/hook
python -m github_workflow commit -m "Add a file" a.txt
python -m github_workflow push
if git diff --quiet; then echo clean; fi
{ git status; }
git ls-files | xargs grep pattern
git diff -u HEAD~1
git log -p --no-textconv
export PATH=/usr/bin
echo "$CLAUDECODE"
env | grep CLAUDECODE
env PYTHONPATH=src python3 - < script.py
env -u HOME python3 script.py
timeout 600 "$PYTHON" -m pytest -q
env "$PYTHON" -m pytest -q
git archive HEAD -o /tmp/snapshot.tar
git archive --format=zip HEAD > snapshot.zip
git archive HEAD src | tar -x -C /tmp/out
git fetch https://github.com/cram2/cognitive_robot_abstract_machine main
git fetch https://github.com/cram2/cognitive_robot_abstract_machine main:refs/remotes/upstream-readonly/main
git fetch --depth=50 https://github.com/cram2/cognitive_robot_abstract_machine +main:refs/remotes/upstream/main
git fetch --quiet origin +main:refs/remotes/origin/main
git fetch origin +refs/pull/888/head:refs/remotes/pull/888
git branch --show-current 2>&1
git branch -a 2>&1 | head
git tag -l 2>/dev/null
git log --oneline -1 2>/dev/null
git stash list > stashes.txt 2>&1
git remote -v &>/dev/null && echo yes
git merge-tree --write-tree origin/main origin/feature
git merge-tree --write-tree --name-only origin/main origin/feature
git merge-tree --write-tree --merge-base=abc123 main feature
git merge-tree abc123 main feature
gh api graphql -f query='{repository(owner:"cram2",name:"project"){pullRequest(number:877){reviewThreads(first:50){nodes{isResolved}}}}}'
gh api graphql -f query='query($number:Int!){repository(owner:"a",name:"b"){pullRequest(number:$number){title}}}' -F number=877 --jq '.data'
gh api graphql --paginate -f query='{viewer{login}}'
grep -n -i "read-only\|gh \`api\`\|gh api" REQUIREMENTS.md
git apply --check change.patch
git apply --check --reverse change.patch
git apply --stat change.patch
printf '%s\n' 'it runs `gh` for the credential' > reply.md
echo 'see $(git push) here'
echo $'see $(git push) here'
stdbuf -o0 git status
uv run git log --oneline
grep -rn git src
echo git push
github-workflow commit -m "Fix git push behind a wrapper" src/a.py
python -m pytest -k "not slow" tests
rg "gh api" src
sed -n 1,5p README.md
cat .git/HEAD
curl -X POST https://example.com/x -d "$DATA"
source .venv/bin/activate && git status
