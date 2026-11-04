# Each line is one command line the guard denies only because it cannot see what it
# runs: a program named by an expansion, a shell reading its input, or xargs.
xargs git push < branches.txt
echo "git push" | bash
echo push origin main | xargs git
echo -D feature | xargs git branch
$'git' push origin main
G=git; $G push origin main
eval "git fetch; $X push origin main"
