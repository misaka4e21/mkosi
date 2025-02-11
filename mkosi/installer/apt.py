# SPDX-License-Identifier: LGPL-2.1-or-later

import dataclasses
import textwrap
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Optional

from mkosi.config import PACKAGE_GLOBS, Config, ConfigFeature
from mkosi.context import Context
from mkosi.installer import PackageManager
from mkosi.log import die
from mkosi.run import run
from mkosi.sandbox import umask
from mkosi.types import _FILE, CompletedProcess, PathString


@dataclasses.dataclass(frozen=True)
class AptRepository:
    types: tuple[str, ...]
    url: str
    suite: str
    components: tuple[str, ...]
    signedby: Optional[Path]

    def __str__(self) -> str:
        return textwrap.dedent(
            f"""\
            Types: {" ".join(self.types)}
            URIs: {self.url}
            Suites: {self.suite}
            Components: {" ".join(self.components)}
            {"Signed-By" if self.signedby else "Trusted"}: {self.signedby or "yes"}

            """
        )


class Apt(PackageManager):
    documentation_exclude_globs = [
        "usr/share/doc/*",
        "usr/share/man/*",
        "usr/share/groff/*",
        "usr/share/gtk-doc/*",
        "usr/share/info/*",
    ]

    @classmethod
    def executable(cls, config: Config) -> str:
        return "apt-get"

    @classmethod
    def subdir(cls, config: Config) -> Path:
        return Path("apt")

    @classmethod
    def cache_subdirs(cls, cache: Path) -> list[Path]:
        return [cache / "archives"]

    @classmethod
    def dpkg_cmd(cls, command: str) -> list[PathString]:
        return [
            command,
            "--admindir=/buildroot/var/lib/dpkg",
            "--root=/buildroot",
        ]

    @classmethod
    def scripts(cls, context: Context) -> dict[str, list[PathString]]:
        cmd = cls.apivfs_script_cmd(context)

        return {
            **{
                command: cmd + cls.env_cmd(context) + cls.cmd(context, command) for command in (
                    "apt",
                    "apt-cache",
                    "apt-cdrom",
                    "apt-config",
                    "apt-extracttemplates",
                    "apt-get",
                    "apt-key",
                    "apt-mark",
                    "apt-sortpkgs",
                )
            },
            **{
                command: cmd + cls.dpkg_cmd(command) for command in(
                    "dpkg",
                    "dpkg-query",
                )
            },
            "mkosi-install"  : ["apt-get", "install"],
            "mkosi-upgrade"  : ["apt-get", "upgrade"],
            "mkosi-remove"   : ["apt-get", "purge"],
            "mkosi-reinstall": ["apt-get", "install", "--reinstall"],
        }

    @classmethod
    def setup(cls, context: Context, repos: Iterable[AptRepository]) -> None:
        (context.pkgmngr / "etc/apt").mkdir(exist_ok=True, parents=True)
        (context.pkgmngr / "etc/apt/apt.conf.d").mkdir(exist_ok=True, parents=True)
        (context.pkgmngr / "etc/apt/preferences.d").mkdir(exist_ok=True, parents=True)
        (context.pkgmngr / "etc/apt/sources.list.d").mkdir(exist_ok=True, parents=True)

        with umask(~0o755):
            # TODO: Drop once apt 2.5.4 is widely available.
            (context.root / "var/lib/dpkg").mkdir(parents=True, exist_ok=True)
            (context.root / "var/lib/dpkg/status").touch()

            (context.root / "var/lib/dpkg/available").touch()

        # We have a special apt.conf outside of pkgmngr dir that only configures "Dir::Etc" that we pass to APT_CONFIG
        # to tell apt it should read config files from /etc/apt in case this is overridden by distributions. This is
        # required because apt parses CLI configuration options after parsing its configuration files and as such we
        # can't use CLI options to tell apt where to look for configuration files.
        config = context.pkgmngr / "etc/apt.conf"
        if not config.exists():
            config.write_text(
                textwrap.dedent(
                    """\
                    Dir::Etc "/etc/apt";
                    """
                )
            )

        sources = context.pkgmngr / "etc/apt/sources.list.d/mkosi.sources"
        if not sources.exists():
            for repo in repos:
                if repo.signedby and not repo.signedby.exists():
                    die(
                        f"Keyring for repo {repo.url} not found at {repo.signedby}",
                        hint="Make sure the right keyring package (e.g. debian-archive-keyring, kali-archive-keyring "
                             "or ubuntu-keyring) is installed",
                    )

            with sources.open("w") as f:
                for repo in repos:
                    f.write(str(repo))

    @classmethod
    def finalize_environment(cls, context: Context) -> dict[str, str]:
        env = {
            "APT_CONFIG": "/etc/apt.conf",
            "DEBIAN_FRONTEND" : "noninteractive",
            "DEBCONF_INTERACTIVE_SEEN": "true",
        }

        if "INITRD" not in context.config.environment and context.config.bootable != ConfigFeature.disabled:
            env["INITRD"] = "No"

        return super().finalize_environment(context) | env

    @classmethod
    def cmd(cls, context: Context, command: str = "apt-get") -> list[PathString]:
        debarch = context.config.distribution.architecture(context.config.architecture)

        cmdline: list[PathString] = [
            command,
            "-o", f"APT::Architecture={debarch}",
            "-o", f"APT::Architectures={debarch}",
            "-o", f"APT::Install-Recommends={str(context.config.with_recommends).lower()}",
            "-o", "APT::Immediate-Configure=off",
            "-o", "APT::Get::Assume-Yes=true",
            "-o", "APT::Get::AutomaticRemove=true",
            "-o", "APT::Get::Allow-Change-Held-Packages=true",
            "-o", "APT::Get::Allow-Remove-Essential=true",
            "-o", "APT::Sandbox::User=root",
            "-o", "Acquire::AllowReleaseInfoChange=true",
            "-o", "Dir::Cache=/var/cache/apt",
            "-o", "Dir::State=/var/lib/apt",
            "-o", "Dir::Log=/var/log/apt",
            "-o", "Dir::State::Status=/buildroot/var/lib/dpkg/status",
            "-o", f"Dir::Bin::DPkg={context.config.find_binary('dpkg')}",
            "-o", "Debug::NoLocking=true",
            "-o", "DPkg::Options::=--root=/buildroot",
            "-o", "DPkg::Options::=--force-unsafe-io",
            "-o", "DPkg::Options::=--force-architecture",
            "-o", "DPkg::Options::=--force-depends",
            "-o", "DPkg::Options::=--no-debsig",
            "-o", "DPkg::Use-Pty=false",
            "-o", "DPkg::Install::Recursive::Minimum=1000",
            "-o", "pkgCacheGen::ForceEssential=,",
        ]

        if not context.config.repository_key_check:
            cmdline += [
                "-o", "Acquire::AllowInsecureRepositories=true",
                "-o", "Acquire::AllowDowngradeToInsecureRepositories=true",
                "-o", "APT::Get::AllowUnauthenticated=true",
            ]

        if not context.config.with_docs:
            cmdline += [f"--option=DPkg::Options::=--path-exclude=/{glob}" for glob in cls.documentation_exclude_globs]
            cmdline += ["--option=DPkg::Options::=--path-include=/usr/share/doc/*/copyright"]

        if context.config.proxy_url:
            cmdline += [
                "-o", f"Acquire::http::Proxy={context.config.proxy_url}",
                "-o", f"Acquire::https::Proxy={context.config.proxy_url}",
            ]

        return cmdline

    @classmethod
    def invoke(
        cls,
        context: Context,
        operation: str,
        arguments: Sequence[str] = (),
        *,
        apivfs: bool = False,
        stdout: _FILE = None,
    ) -> CompletedProcess:
        return run(
            cls.cmd(context) + [operation, *arguments],
            sandbox=cls.sandbox(context, apivfs=apivfs),
            env=cls.finalize_environment(context),
            stdout=stdout,
        )

    @classmethod
    def sync(cls, context: Context, force: bool) -> None:
        cls.invoke(context, "update")

    @classmethod
    def createrepo(cls, context: Context) -> None:
        if not (conf := context.repository / "conf/distributions").exists():
            conf.parent.mkdir(exist_ok=True)
            conf.write_text(
                textwrap.dedent(
                    f"""\
                    Origin: mkosi
                    Label: mkosi
                    Architectures: {context.config.distribution.architecture(context.config.architecture)}
                    Codename: mkosi
                    Components: main
                    Description: mkosi local repository
                    """
                )
            )

        run(
            [
                "reprepro",
                "--ignore=extension",
                "includedeb",
                "mkosi",
                *(d.name for glob in PACKAGE_GLOBS for d in context.repository.glob(glob) if "deb" in glob),
            ],
            sandbox=context.sandbox(
                binary="reprepro",
                options=["--bind", context.repository, context.repository, "--chdir", context.repository],
            ),
        )

        (context.pkgmngr / "etc/apt/sources.list.d").mkdir(parents=True, exist_ok=True)
        (context.pkgmngr / "etc/apt/sources.list.d/mkosi-local.sources").write_text(
            textwrap.dedent(
                """\
                Enabled: yes
                Types: deb
                URIs: file:///repository
                Suites: mkosi
                Components: main
                Trusted: yes
                """
            )
        )

        cls.invoke(
            context,
            "update",
            arguments=[
                "-o", "Dir::Etc::sourcelist=sources.list.d/mkosi-local.sources",
                "-o", "Dir::Etc::sourceparts=-",
                "-o", "APT::Get::List-Cleanup=0",
            ],
        )
