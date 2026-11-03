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
