# Each line is one command line the guard denies only because it cannot see what it
# runs: a program named by an expansion, a shell reading its input, or xargs.
xargs git push < branches.txt
echo "git push" | bash
echo push origin main | xargs git
echo -D feature | xargs git branch
$'git' push origin main
G=git; $G push origin main
eval "git fetch; $X push origin main"
X=git; eval "$X push origin main"
X=git; bash -c "$X push origin main"
X=git; env "$X" push origin main
X=git; sudo "$X" push origin main
X=git; timeout 5 "$X" push origin main
X=git; echo main | xargs "$X" push origin
