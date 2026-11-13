# GitHubWorkflow

A personal GitHub workflow for Claude Code sessions: standing notes and per-branch
progress every session starts with, and every write to git and GitHub made through the
workflow's own commands. It is built on the domain model of git and GitHub in
[`domain_model/`](domain_model), shipped with the plugin as a package of its own.

[TUTORIAL.md](TUTORIAL.md) walks through how the parts work together;
[REQUIREMENTS.md](REQUIREMENTS.md) says what the workflow has to do.

> [!IMPORTANT]
> **A cloud session start pushes to the notes branch.** Every session start in a
> Claude Code cloud session commits a request for the comments you tagged (by
> mentioning yourself) to `github-workflow/notes` - a file under `tag-requests/`, and
> the first time the workflow `.github/workflows/read-tagged-comments.yml` - and so
> starts a run of the repository's Actions, which saves the answer under
> `tag-answers/` for the next session start. Nothing else is pushed, and a local
> session start pushes nothing. The run costs Actions minutes on a private repository;
> see [Tagged comments](REQUIREMENTS.md#tagged-comments).

## Licence

This project is licensed under the [Apache License 2.0](LICENSE), except for
`domain_model/src/domain_model/exceptions.py` and
`domain_model/src/domain_model/class_property.py`, which contain code adapted
from [krrood](https://github.com/cram2/krrood) and remain under the GNU Lesser General
Public License, Version 3.

Part of the code and ideas are based on
[basstler](https://github.com/AbdelrhmanBassiouny/basstler) at commit
[`5b6e1b699d8ba69880e5ce15ad0b32c4764b0e60`](https://github.com/AbdelrhmanBassiouny/basstler/tree/5b6e1b699d8ba69880e5ce15ad0b32c4764b0e60),
and changed since. basstler is a personal project by Abdelrhman Bassiouny
(<bido.bassuny@gmail.com>), developed independently of any employer or institution. It is
licensed under the Apache License 2.0 as well; see [NOTICE](NOTICE) for attribution.
