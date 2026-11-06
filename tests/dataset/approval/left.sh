# Each line is one command line the mod leaves to the session's permissions.
github-workflow finding accept 7
github-workflow finding shelve 7
github-workflow finding reject 7 --reason "Not a bug"
github-workflow finding edit 7 --title "Another title"
github-workflow finding prioritize 7 --priority high
github-workflow stack on 3
github-workflow describe 12 --body-file body.md
github-workflow upstream LucaKro/project feature
PATH=/elsewhere github-workflow push
/tmp/github-workflow push
python -m github_workflow push
github-workflow push; rm -rf build
github-workflow push && git push
github-workflow push | sh
github-workflow push > pushed.txt
github-workflow commit -m "$(cat message.txt)" a.py
github-workflow push & github-workflow sync
git push
ls
