# Each line is one workflow command line the guard lets run without asking.
python -m github_workflow branch start feature
python -m github_workflow branch discard
python -m github_workflow commit -m "Add a file" a.txt
python -m github_workflow push
python -m github_workflow notes save
python -m github_workflow draft --title Change --body-file description.md
python -m github_workflow finding list
python -m github_workflow details 4
python -m github_workflow --help
python -m github_workflow cleanup
cd /checkout && python -I -m github_workflow cleanup
python -m github_workflow finding comment 3 --body-file comment.md
github-workflow cleanup
python -m github_workflow describe --body-file description.md
python -m github_workflow describe --title "A sharper title"
