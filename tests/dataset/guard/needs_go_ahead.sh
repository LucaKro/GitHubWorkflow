# Each line is one workflow command line the guard asks the person to confirm.
python -m github_workflow finding accept 3
python3 -m github_workflow finding shelve 3
/home/someone/.virtualenvs/githubworkflow-runtime/bin/python -m github_workflow finding reject 3 --reason "Not a bug"
python -m github_workflow cleanup
python -m github_workflow stack on 4 5
python -m github_workflow describe 4 --body-file description.md
cd /checkout && python -I -m github_workflow cleanup
