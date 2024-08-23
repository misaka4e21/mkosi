# SPDX-License-Identifier: LGPL-2.1-or-later

from mkosi.context import Context
from mkosi.distributions import centos, join_mirror
from mkosi.installer.rpm import RpmRepository, find_rpm_gpgkey


class Installer(centos.Installer):
    @classmethod
    def default_release(cls) -> str:
        return "oe2403"

    @staticmethod
    def releasever_to_distro_version(releasever: str) -> str:
        table = {
            "oe2203": "openEuler-22.03-LTS",
            "oe2203sp1": "openEuler-22.03-LTS-SP1",
            "oe2203sp2": "openEuler-22.03-LTS-SP2",
            "oe2203sp3": "openEuler-22.03-LTS-SP3",
            "oe2403": "openEuler-24.03-LTS",
        }
        return table.get(releasever, releasever)

    @classmethod
    def pretty_name(cls) -> str:
        return "openEuler"

    @classmethod
    def gpgurls(cls, context: Context) -> tuple[str, ...]:
        return (
            find_rpm_gpgkey(
                context,
                f"RPM-GPG-KEY-openEuler",
                f"https://repo.openeuler.org/{cls.releasever_to_distro_version(context.config.release)}/RPM-GPG-KEY-openEuler",
            ),
        )

    @classmethod
    def repository_variants(cls, context: Context, repo: str) -> list[RpmRepository]:
        if context.config.mirror:
            baseurl = join_mirror(context.config.mirror, f'{cls.releasever_to_distro_version(context.config.release)}/{repo}/$basearch')
            url = f"baseurl={baseurl}"
        else:
            url = f"baseurl=https://repo.openeuler.org/{cls.releasever_to_distro_version(context.config.release)}/{repo}/$basearch"

        return [RpmRepository(repo, url, cls.gpgurls(context))]

    @classmethod
    @listify
    def repositories(cls, context: Context) -> Iterable[RpmRepository]:
        yield from cls.repository_variants(context, "OS")

    @classmethod
    @listify
    def repositories(cls, context: Context) -> Iterable[RpmRepository]:
        if context.config.local_mirror:
            yield from cls.repository_variants(context, "AppStream")
            return

        yield from cls.repository_variants(context, "BaseOS")
        yield from cls.repository_variants(context, "AppStream")
        yield from cls.repository_variants(context, "extras")
        yield from cls.repository_variants(context, "CRB")

        yield from cls.epel_repositories(context)
        yield from cls.sig_repositories(context)

    @classmethod
    def sig_repositories(cls, context: Context) -> list[RpmRepository]:
        return []

    @classmethod
    def install(cls, context: Context) -> None:
        cls.install_packages(context, ["core"], apivfs=False)

    @classmethod
    def architecture(cls, arch: Architecture) -> str:
        a = {
            Architecture.x86_64      : "x86_64",
            Architecture.loongarch64 : "loongarch64",
            Architecture.ppc64_le    : "ppc64le",
            Architecture.riscv64     : "riscv64",
            Architecture.arm64       : "aarch64",
        }.get(arch)

        if not a:
            die(f"Architecture {a} is not supported by {cls.pretty_name()}")

        return a

