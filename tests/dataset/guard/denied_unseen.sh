# Each line is one command line the guard denies only because it cannot see what it
# runs: a program named by an expansion, a shell or source reading its input, xargs,
# or an HTTP client reading its options from elsewhere or sending where an expansion says.
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
source <(echo git push)
echo "git push" | dash
curl -X POST "$URL"
curl -X POST $GITHUB_API_URL/repos/a/b
curl -X POST "https://$HOST/repos/a/b"
curl -K config
curl -sK config
wget --execute=post_data=x https://example.com
