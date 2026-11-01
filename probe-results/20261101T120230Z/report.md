# Probe report

## Environment

- **python**: 3.13.18
- **cloud session**: true
- **token variable set**: True
- **checked-out branch**: cloud-probe
- **git author**: LucaKro <luc_kro@uni-bremen.de>
- **git**: git version 2.43.0
- **curl**: curl 8.5.0 (x86_64-pc-linux-gnu) libcurl/8.5.0 OpenSSL/3.0.13 zlib/1.3 brotli/1.1.0 zstd/1.5.5 libidn2/2.3.7 libpsl/0.21.2 (+libidn2/2.3.7) libssh/0.10.6/openssl/zlib nghttp2/1.59.0 librtmp/2.3 OpenLDAP/2.6.10
- **gh**: gh version 2.89.0 (2026-03-26)
- **repository**: LucaKro/GitHubWorkflow
- **default branch**: main

## domain model, used live

| check | ok | detail | s |
|---|---|---|---|
| authenticated-login | yes | LucaKro | 0.34 |
| labels | yes | accessibility, bug, documentation, duplicate, enhancement, good first issue, help wanted, invalid, question, wontfix | 0.35 |
| open-pull-requests | yes | 0 open | 0.42 |
| check-state | yes | not reported | 0.78 |
| pull-request-review-state | yes | read through rest: 0 review threads, checks not reported | 2.24 |

## git: a notes branch on the repository

| check | ok | detail | s |
|---|---|---|---|
| push probe/notes-20261101T120230Z | yes | pushed | 1.42 |
| read probe/notes-20261101T120230Z back | yes | 0ff8695932216f526101b2de17f8f9a02d333440	refs/heads/probe/notes-20261101T120230Z | 0.36 |
| delete probe/notes-20261101T120230Z | NO | fatal: the remote end hung up unexpectedly | 0.42 |
| push claude/probe-notes-20261101T120230Z | yes | pushed | 1.4 |
| read claude/probe-notes-20261101T120230Z back | yes | 0ff8695932216f526101b2de17f8f9a02d333440	refs/heads/claude/probe-notes-20261101T120230Z | 0.36 |
| delete claude/probe-notes-20261101T120230Z | NO | fatal: the remote end hung up unexpectedly | 0.41 |

## issues: the finding boards

| check | ok | detail | s |
|---|---|---|---|
| issues enabled | yes | 200 True | 0.32 |
| create the unreviewed label | yes | 201 | 0.35 |
| file a finding as unreviewed | yes | 201 | 0.42 |
| list the unreviewed board right after filing | yes | 200 finding listed: False | 0.32 |
| comment the rejection reason | yes | 201 | 0.51 |
| close it as not planned | yes | 200 #3 | 0.85 |
| read it back directly | yes | 200 state closed, reason not_planned | 0.25 |
| list the rejected board right after closing | yes | 200 close reason: [] | 0.34 |
| delete the label | yes | 204 | 0.38 |

## pull requests: draft, review threads, base

| check | ok | detail | s |
|---|---|---|---|
| push probe/pull-request-20261101T120230Z | yes | cfbdf9e0deba66df3dba286cf60242d51a55cff6 | 1.44 |
| open a draft pull request | yes | 201 | 1.09 |
| read its state | yes | 200 draft True, mergeable_state unknown, 0 review requests | 0.42 |
| count its review threads (proxy route) | yes | 200 0 entries | 0.34 |
| compare it with its base | yes | 200 ahead 1, behind 0 | 0.3 |
| read the checks on its head | yes | 200 0 check runs | 0.25 |
| close it | yes | 200 #4 | 1.06 |
| delete probe/pull-request-20261101T120230Z | NO | fatal: the remote end hung up unexpectedly | 0.42 |

## signals beside the repository

| check | ok | detail | s |
|---|---|---|---|
| search pull requests waiting on my review | yes | 200 8 waiting | 0.78 |
