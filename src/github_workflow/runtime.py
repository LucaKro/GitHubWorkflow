"""
The environment the workflow's hooks run it from: which commits of its packages it
holds, whether their branch has moved on, and rebuilding it from there.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from itertools import repeat
from pathlib import Path
from typing import Any

from basstler_domain_model.commands import CommandRunner
from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch

import github_workflow.guard as guard
from github_workflow.command_line import WorkflowCommand
from github_workflow.environment import GitBatchVariable
from github_workflow.exceptions import NotARuntimeError, RuntimeBuildFailedError
from github_workflow.guard import GitWrite, Program
from github_workflow.hooks import HookKey, HookValue
from github_workflow.work import WorkflowStep

# %% what is installed


class RuntimeDistribution(StrEnum):
    """
    The packages the runtime holds, in the order they are installed: the workflow
    depends on the domain model by name, which no index serves.
    """

    DOMAIN_MODEL = "basstler-domain-model"
    """
    The shared GitHub and git model.
    """

    WORKFLOW = "github-workflow"
    """
    The workflow itself.
    """


class DirectUrlKey(StrEnum):
    """
    The keys of the record pip keeps of where a package was installed from
    (``direct_url.json``).
    """

    URL = "url"
    VCS_INFO = "vcs_info"
    COMMIT_ID = "commit_id"
    REQUESTED_REVISION = "requested_revision"


@dataclass(frozen=True)
class InstallSource:
    """
    A git repository a package was installed from, at a commit of a branch.
    """

    url: str
    """
    The repository.
    """

    commit: str
    """
    The commit installed.
    """

    branch: str
    """
    The branch it was installed from.
    """

    @classmethod
    def from_json(cls, record: dict[str, Any]) -> InstallSource | None:
        """
        :param record: pip's record of where a package was installed from.
        :return: The source, ``None`` when the package was not installed from git, as
            an editable install of a checkout is not.
        """
        vcs = record.get(DirectUrlKey.VCS_INFO)
        if vcs is None:
            return None
        return cls(
            record[DirectUrlKey.URL],
            vcs[DirectUrlKey.COMMIT_ID],
            vcs.get(DirectUrlKey.REQUESTED_REVISION, "main"),
        )

    def requirement(self, distribution: RuntimeDistribution) -> str:
        """
        :param distribution: The package.
        :return: The pip requirement installing it from the branch's tip.
        """
        return f"{distribution} @ git+{self.url}@{self.branch}"

    def latest_commit(self, git: GitCommandRunner) -> str | None:
        """
        :param git: Runs git.
        :return: The branch's tip, ``None`` when the repository cannot be reached
            without asking for credentials.
        """
        listed = git.attempt(
            "ls-remote",
            self.url,
            RemoteBranch(self.url, self.branch).reference,
            environment={
                GitBatchVariable.TERMINAL_PROMPT: "0",
                GitBatchVariable.SSH_COMMAND: "ssh -o BatchMode=yes -o ConnectTimeout=5",
            },
        )
        if not listed.succeeded or not listed.output:
            return None
        return listed.output.split()[0]


@dataclass(frozen=True)
class RuntimePackage:
    """
    One package of the runtime, and where it came from.
    """

    distribution: RuntimeDistribution
    """
    The package.
    """

    source: InstallSource
    """
    Where it was installed from.
    """


@dataclass(frozen=True)
class Runtime:
    """
    The packages the running interpreter holds, when it is a runtime: one with every
    package installed from git rather than from a checkout.
    """

    packages: tuple[RuntimePackage, ...]
    """
    Its packages in install order, empty when the interpreter is no runtime.
    """

    @classmethod
    def installed(cls) -> Runtime:
        """
        :return: The running interpreter's runtime.
        """
        packages = []
        for distribution in RuntimeDistribution:
            recorded = importlib.metadata.distribution(distribution).read_text(
                "direct_url.json"
            )
            source = (
                None
                if recorded is None
                else InstallSource.from_json(json.loads(recorded))
            )
            if source is None:
                return cls(())
            packages.append(RuntimePackage(distribution, source))
        return cls(tuple(packages))

    def behind(self, git: GitCommandRunner) -> list[str]:
        """
        :param git: Runs git.
        :return: Each package whose branch moved on, as ``<package> <installed> ->
            <tip>``; a branch that cannot be reached counts as not moved.
        """
        with ThreadPoolExecutor() as pool:
            tips = list(
                pool.map(
                    InstallSource.latest_commit,
                    [package.source for package in self.packages],
                    repeat(git),
                )
            )
        behind = []
        for package, latest in zip(self.packages, tips):
            if latest is not None and latest != package.source.commit:
                behind.append(
                    f"{package.distribution} {package.source.commit[:7]} -> {latest[:7]}"
                )
        return behind

    def notice(self, git: GitCommandRunner) -> str | None:
        """
        :param git: Runs git.
        :return: One line naming the packages whose branch moved on and the command
            updating them, ``None`` when none did.
        """
        behind = self.behind(git)
        if not behind:
            return None
        return (
            f"github-workflow: newer on main ({'; '.join(behind)}); update with "
            f"`{WorkflowCommand.command_line(WorkflowCommand.UPDATE)}`"
        )


# %% switching over


@dataclass(frozen=True)
class RuntimeSwitch:
    """
    The path the hooks run the runtime from, pointed at one build after another.
    """

    location: Path
    """
    The runtime's path, which ends up a link to the build in use.
    """

    def to(self, build: Path) -> None:
        """
        Point the runtime's path at a build in one step, and remove the build it pointed
        at before.

        :param build: The new build, beside the runtime's path.
        """
        if self.location.is_symlink():
            previous = self.location.parent / os.readlink(self.location)
        else:
            previous = self.location.with_name(f".{self.location.name}-retired")
            self.location.rename(previous)
        link = self.location.with_name(f".{self.location.name}-link")
        link.unlink(missing_ok=True)
        link.symlink_to(build.name)
        os.replace(link, self.location)
        if previous.resolve() != build.resolve():
            shutil.rmtree(previous)


# %% rebuilding


@dataclass(frozen=True)
class RuntimeRebuild(WorkflowStep):
    """
    The runtime rebuilt from its branches' tips beside the one in use, checked, and
    switched over to; a build that fails changes nothing.
    """

    runtime: Runtime
    """
    The runtime in use.
    """

    location: Path
    """
    The path the hooks run it from.
    """

    def run(self) -> str:
        if not self.runtime.packages:
            raise NotARuntimeError(str(self.location))
        behind = self.runtime.behind(GitCommandRunner(self.location.parent))
        if not behind:
            return "runtime already at main"
        build = Path(
            tempfile.mkdtemp(prefix=f".{self.location.name}-", dir=self.location.parent)
        )
        runner = CommandRunner(self.location.parent)
        base = (
            Path(sys.base_prefix)
            / "bin"
            / (f"python{sys.version_info.major}.{sys.version_info.minor}")
        )
        python = build / "bin" / "python"
        steps = [
            [str(base), "-m", "venv", "--without-pip", str(build)],
            [sys.executable, "-I", "-m", "pip", "--python", str(python)]
            + ["install", "--quiet", "pip"],
            *(
                [str(python), "-I", "-m", "pip", "install", "--quiet"]
                + [package.source.requirement(package.distribution)]
                for package in self.runtime.packages
            ),
        ]
        for step in steps:
            result = runner.run(*step)
            if not result.succeeded:
                shutil.rmtree(build)
                said = (result.error_output or result.output).splitlines()
                raise RuntimeBuildFailedError(" ".join(step), "".join(said[-1:]))
        push = {
            HookKey.TOOL_NAME: HookValue.BASH_TOOL,
            HookKey.TOOL_INPUT: {HookKey.COMMAND: f"{Program.GIT} {GitWrite.PUSH}"},
        }
        checked = runner.run(
            str(python),
            "-I",
            "-m",
            guard.__name__,
            standard_input=json.dumps(push),
        )
        if HookValue.DENY not in checked.output:
            shutil.rmtree(build)
            raise RuntimeBuildFailedError("checking the rebuilt guard", checked.summary)
        RuntimeSwitch(self.location).to(build)
        return f"runtime rebuilt from main: {'; '.join(behind)}"
