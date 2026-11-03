# Each line is one command line the coarse guard lets through: it names none of git, gh,
# curl or wget.
ls -la
python -m pytest -q tests
cat README.md
rg GitHubWorkflow src
