"""Retain the tested DASH import and its native C++ consumer with provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET


TESTS = ("prebuilt_contract_test", "runtime_consumer_test")
DECLARATIONS = (".bazelversion", ".bazelrc", "MODULE.bazel", "MODULE.bazel.lock", "bazel/prebuilt.json")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(repo: Path, *arguments: str) -> str:
    result = subprocess.run(arguments, cwd=repo, capture_output=True, text=True)
    require(result.returncode == 0, "command failed: " + " ".join(arguments) + "\n" + result.stderr + result.stdout)
    return result.stdout.strip()


def module_version(text: str, rule: str) -> str:
    versions = []
    for stanza in re.findall(r"\b" + rule + r"\s*\((.*?)\)", text, re.DOTALL):
        if re.search(r'\bname\s*=\s*"sonic-build-infra"', stanza):
            match = re.search(r'\bversion\s*=\s*"([^"]+)"', stanza)
            require(match is not None, "infrastructure declaration has no version")
            versions.append(match.group(1))
    require(len(versions) == 1, "expected exactly one infrastructure declaration")
    return versions[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=("amd64", "arm64"), required=True)
    parser.add_argument("--bazel-config", choices=("", "default", "aarch64"), default="default")
    parser.add_argument("--image", required=True, help="Pinned container image used by the workflow")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for owned in ("provenance.json", "import", "consumer", "validation/tests", "validation/declarations"):
        require(not (output / owned).exists(), "output already contains a previous collection: " + owned)

    machine = {"amd64": "x86_64", "arm64": "aarch64"}[args.architecture]
    require(platform.system() == "Linux" and platform.machine() == machine, "runner CPU is not the selected native architecture")
    require(run(repo, "dpkg", "--print-architecture") == args.architecture, "container architecture differs from the native runner")
    os_release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    require(os_release.get("VERSION_CODENAME", "").strip('"') == "trixie", "validation requires native Debian Trixie")

    options = ["--lockfile_mode=error"]
    if args.bazel_config and args.bazel_config != "default":
        options.append("--config=" + args.bazel_config)

    def bazel(command: str, *arguments: str) -> str:
        return run(repo, "bazel", command, *options, *arguments)

    platform_name = {"amd64": "x86_64_trixie", "arm64": "aarch64_trixie"}[args.architecture]
    platform_label = "@sonic_build_infra//platforms:" + platform_name
    canonical = bazel("cquery", "config(" + platform_label + ", target)", "--output=starlark", "--starlark:expr=target.label.repo_name")
    require(re.fullmatch(r"[A-Za-z0-9._+-]+", canonical) is not None, "infrastructure canonical repository is ambiguous")
    # Bazel 8 info does not apply the root module's apparent-repository mapping
    # to platform flags. Keep the same platforms, using their resolved labels.
    canonical_platform = "@@" + canonical + "//platforms:" + platform_name
    info_options = ["--platforms=" + canonical_platform, "--host_platform=" + canonical_platform]
    execution_root = Path(bazel("info", *info_options, "execution_root"))
    testlogs = Path(bazel("info", *info_options, "bazel-testlogs"))

    def files(target: str) -> list[Path]:
        names = bazel("cquery", "config(" + target + ", target)", "--output=files").splitlines()
        require(bool(names), "target has no materialized outputs: " + target)
        paths = [execution_root / name for name in names]
        require(all(path.is_file() for path in paths), "target output is missing: " + target)
        return paths

    def retain(source: Path, relative: str | Path) -> None:
        require(source.is_file(), "required artifact is missing: " + str(source))
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        shutil.copymode(source, destination)

    imported = files("//:prebuilt_files")
    libraries = [path for path in imported if path.name == "libdashapi.so"]
    require(len(libraries) == 1, "expected one selected DASH shared library")
    import_root = libraries[0].parents[3]
    entry = json.loads((repo / "bazel/prebuilt.json").read_text())["packages"][args.architecture]
    relative_files = {path.relative_to(import_root).as_posix() for path in imported}
    required = {entry["filename"], "IMPORTS.json", "payload/usr/lib/libdashapi.so", "payload/usr/include/dash_api/utils.h", "payload/usr/include/dash_api/types.pb.h"}
    require(required <= relative_files, "prebuilt_files omits required input or consumer artifacts")
    require(sha256(import_root / entry["filename"]) == entry["sha256"], "selected input DEB differs from its pinned hash")
    require(json.loads((import_root / "IMPORTS.json").read_text()) == entry, "selected import provenance differs from its manifest")
    for source in imported:
        retain(source, Path("import") / source.relative_to(import_root))

    consumers = files("//bazel:runtime_consumer_test")
    require(len(consumers) == 1, "expected one compiled runtime consumer")
    elf_header = run(repo, "readelf", "--file-header", str(consumers[0]))
    elf_machine = {"amd64": "Advanced Micro Devices X86-64", "arm64": "AArch64"}[args.architecture]
    require(re.search(r"Machine:\s+" + re.escape(elf_machine) + r"\s*$", elf_header, re.MULTILINE) is not None, "compiled consumer is not native to the selected architecture")
    retain(consumers[0], "consumer/runtime_consumer_test")

    for test in TESTS:
        directory = testlogs / "bazel" / test
        result = ET.parse(directory / "test.xml").getroot()
        suites = list(result.iter("testsuite"))
        require(any(int(suite.get("tests", "0")) > 0 for suite in suites), "test result contains no executed cases: " + test)
        require(all(int(suite.get(field, "0")) == 0 for suite in suites for field in ("failures", "errors", "skipped")), "test suite reports incomplete or failed cases: " + test)
        require(not any(element.tag in ("failure", "error", "skipped") for element in result.iter()), "test result is not a complete pass: " + test)
        for filename in ("test.log", "test.xml"):
            retain(directory / filename, Path("validation/tests") / test / filename)

    for declaration in DECLARATIONS:
        retain(repo / declaration, Path("validation/declarations") / declaration)
    declared_version = module_version((repo / "MODULE.bazel").read_text(), "bazel_dep")
    fetched_module = execution_root / "external" / canonical / "MODULE.bazel"
    require(fetched_module.is_file(), "resolved infrastructure MODULE.bazel is missing")
    require(module_version(fetched_module.read_text(), "module") == declared_version, "resolved infrastructure version differs from the declaration")
    retain(fetched_module, "validation/declarations/resolved-sonic-build-infra.MODULE.bazel")

    inventory = {
        path.relative_to(output).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    provenance = {
        "schema_version": 1,
        "scope": "Pinned prebuilt C++ import and native consumer; the retained DEB is an input package, not a Bazel-produced package. Debug symbols and protobuf source compilation are outside this validation.",
        "source": {
            "revision": run(repo, "git", "rev-parse", "HEAD"),
            "tree": run(repo, "git", "rev-parse", "HEAD^{tree}"),
            "tracked_worktree_dirty": bool(run(repo, "git", "status", "--porcelain", "--untracked-files=no")),
        },
        "environment": {
            "architecture": args.architecture,
            "uname_machine": platform.machine(),
            "distribution": "trixie",
            "container_image_input": args.image,
            "bazel": run(repo, "bazel", "--version"),
            "bazel_config": args.bazel_config,
            "platform": platform_label,
        },
        "github": {
            name.removeprefix("GITHUB_").lower(): os.environ[name]
            for name in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_WORKFLOW", "GITHUB_EVENT_NAME", "GITHUB_SHA")
            if name in os.environ
        },
        "import": entry,
        "infrastructure": {
            "version": declared_version,
            "canonical_repository": canonical,
            "module_sha256": sha256(fetched_module),
        },
        "tests": ["//bazel:" + test for test in TESTS],
        "files": inventory,
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(f"Retained {len(inventory)} files for native {args.architecture} validation in {output}")


if __name__ == "__main__":
    main()
