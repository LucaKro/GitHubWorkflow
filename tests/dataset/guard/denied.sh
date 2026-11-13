# Each line is one command line the guard denies.
git push origin feature
git push --force-with-lease origin feature
git commit -m "Change"
git add .
git switch -c feature
git checkout main
git reset --hard HEAD~1
git rebase main
git branch new-branch
git branch -D old-branch
git tag v1.0
git remote add upstream https://github.com/someone/project
git config user.name Someone
git config --global user.email someone@example.com
git fetch origin main:main
git stash
git -c alias.publish=push publish
git -c core.pager=less log
GIT_EXTERNAL_DIFF=program git diff
git grep -O less pattern
git publish
ls && git push
git status; git commit -m "Change"
echo $(git push)
echo `git push`
env -u HOME git push
timeout 10 git push
sudo -u someone git push
bash -c "git push"
bash -lc "git commit -m Change"
sh -c 'cd /tmp && git push'
eval "git push"
gh pr create --title Change
gh pr merge 9
gh pr comment 9 --body Thanks
gh issue close 3
gh repo edit --delete-branch-on-merge
gh api -X DELETE repos/LucaKro/GitHubWorkflow/git/refs/heads/feature
gh api repos/LucaKro/GitHubWorkflow/issues -f title=Finding
gh api --method PATCH repos/LucaKro/GitHubWorkflow
gh api -X GET repos/LucaKro/GitHubWorkflow/issues --input body.json
gh api -X POST repos/LucaKro/GitHubWorkflow/issues -f title=Finding
gh api -fX GET repos/LucaKro/GitHubWorkflow/issues -f title=Finding
curl -X POST https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
curl -d '{"title": "x"}' https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
curl --data-raw x https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
wget --post-data x https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
cat <<< nothing && git push
if true; then git push origin main; fi
while true; do git push origin main; done
{ git push origin main; }
! git push origin main
f(){ git push origin main; }; f
function f { git push origin main; }
git ls-remote --upload-pack='touch pwned' .
git ls-remote -u program origin
git ls-remote --receive-pack=program origin
git fetch --upload-pack='touch pwned' .
git fetch -u origin
git fetch --exec=program origin
git diff --output=file
git log --output file
git diff --ext-diff
git log -p --textconv
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor GIT_CONFIG_VALUE_0=program; git status
declare -x GIT_PAGER=program; git log
set -a; GIT_PAGER=program; git log
env GIT_EXTERNAL_DIFF=program git diff
CLAUDECODE= python3 push.py
unset CLAUDECODE; python3 push.py
export -n CLAUDECODE
export CLAUDECODE=
env -u CLAUDECODE python3 push.py
env --unset=CLAUDECODE python3 push.py
env -C build -u CLAUDECODE python3 push.py
env -i python3 push.py
env - python3 push.py
git archive --remote=https://github.com/LucaKro/GitHubWorkflow main
git archive --remote origin main
git archive HEAD -o .git/hooks/pre-commit
git archive -o.git/hooks/pre-commit HEAD
git fetch https://github.com/cram2/cognitive_robot_abstract_machine main:main
git fetch https://github.com/cram2/cognitive_robot_abstract_machine main:refs/heads/main
git fetch ext::sh main
git fetch file:///tmp/repository main
git fetch git@github.com:cram2/cognitive_robot_abstract_machine.git main
git branch 2 > out.txt
git branch "2">out.txt
> out.txt git push
git push 2>&1
gh api graphql -f query='mutation{addComment(input:{subjectId:"x",body:"y"}){clientMutationId}}'
gh api graphql -f query='{viewer{login}} mutation{deleteIssue(input:{issueId:"x"}){clientMutationId}}'
gh api graphql -F query=@mutation.graphql
gh api graphql -X POST -f query='{viewer{login}}'
gh api graphql --input body.json
echo \\`git push`
echo `echo \`git push\``
echo "a \` b" && git push
git apply change.patch
git apply --check --index change.patch
git apply --stat --apply change.patch
echo "see `git push` here"
echo 'quoted' $(git push)
echo $(bash -c 'git push')
find . -exec git push \;
stdbuf -o0 git push
setsid git push
ionice git push
flock /tmp/l git push
parallel git push ::: x
npx git push
busybox git push
ssh localhost git push
script -c "git push" /dev/null
dash -c "git push"
ksh -c "git push"
fish -c "git push"
builtin command git push
trap 'git push' EXIT
coproc git push
rm .git/hooks/pre-push
chmod -x .git/hooks/pre-push
echo x > .git/hooks/pre-push
echo x >> .git/config
sed -i s/a/b/ .git/config
cp x .git/config
dd if=x of=.git/config
git log > .git/hooks/pre-push
echo x > ~/.gitconfig
echo x > ~/.config/git/config
echo x > /etc/gitconfig
readonly CLAUDECODE=
local CLAUDECODE=
printf -v CLAUDECODE ''
read CLAUDECODE < /dev/null
let CLAUDECODE=0
curl -X POST https://API.GITHUB.COM/x
