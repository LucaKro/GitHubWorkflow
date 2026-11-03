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
xargs git push < branches.txt
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
curl -X POST https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
curl -d '{"title": "x"}' https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
curl --data-raw x https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
wget --post-data x https://api.github.com/repos/LucaKro/GitHubWorkflow/issues
echo "git push" | bash
cat <<< nothing && git push
if true; then git push origin main; fi
while true; do git push origin main; done
{ git push origin main; }
! git push origin main
f(){ git push origin main; }; f
function f { git push origin main; }
echo push origin main | xargs git
echo -D feature | xargs git branch
$'git' push origin main
G=git; $G push origin main
