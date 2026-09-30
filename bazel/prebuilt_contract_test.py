"""Check that the public import preserves the selected libdashapi DEB files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*arguments: str) -> str:
    result = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--runtime-tar", required=True, type=Path)
    parser.add_argument("--architecture", required=True, choices=("amd64", "arm64"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    entry = manifest["packages"][args.architecture]
    library = args.library
    repository = library.parents[3]
    deb = repository / entry["filename"]
    require(sha256(deb) == entry["sha256"], "imported DEB hash differs from the pinned input")
    require(json.loads((repository / "IMPORTS.json").read_text()) == entry, "import provenance differs from the pinned input")

    fields = dict(
        line.split(": ", 1)
        for line in run("dpkg-deb", "--field", str(deb), "Package", "Version", "Architecture").splitlines()
    )
    require(fields == {
        "Package": entry["package"],
        "Version": entry["version"],
        "Architecture": args.architecture,
    }, "imported DEB control identity differs from the pinned input")

    expected = {}
    process = subprocess.Popen(
        ["dpkg-deb", "--fsys-tarfile", str(deb)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(process.stdout is not None, "dpkg-deb did not provide a payload stream")
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        for member in archive:
            path = PurePosixPath(member.name.removeprefix("./"))
            selected_header = path.parent == PurePosixPath("usr/include/dash_api") and path.suffix == ".h"
            if not member.isfile() or not (selected_header or str(path) == "usr/lib/libdashapi.so"):
                continue
            stream = archive.extractfile(member)
            require(stream is not None, "selected payload member is unreadable")
            expected[str(path)] = hashlib.sha256(stream.read()).hexdigest()
    process.stdout.close()
    require(process.stderr is not None, "dpkg-deb did not provide an error stream")
    stderr = process.stderr.read()
    process.stderr.close()
    require(process.wait() == 0, "dpkg-deb could not read the selected payload: " + stderr.decode(errors="replace"))

    headers = repository / "payload/usr/include/dash_api"
    selected = {"usr/lib/libdashapi.so": library}
    selected.update({"usr/include/dash_api/" + path.name: path for path in headers.glob("*.h")})
    require(bool(expected) and set(selected) == set(expected), "public header/library inventory differs from the selected DEB")
    require(all(sha256(path) == expected[name] for name, path in selected.items()), "public header/library bytes differ from the selected DEB")

    with tarfile.open(args.runtime_tar) as archive:
        members = archive.getmembers()
        require(len(members) == 1, "runtime package must contain only the imported shared library")
        member = members[0]
        require(member.name.removeprefix("./") == "usr/lib/libdashapi.so" and member.isfile(),
                "runtime package library has the wrong installed path or file type")
        require(member.uid == 0 and member.gid == 0 and member.mode == 0o644,
                "runtime package library has incorrect ownership or permissions")
        stream = archive.extractfile(member)
        require(stream is not None and hashlib.sha256(stream.read()).hexdigest() == expected["usr/lib/libdashapi.so"],
                "runtime package library differs from the selected DEB")

    header = run("readelf", "--file-header", str(library))
    machine = "Advanced Micro Devices X86-64" if args.architecture == "amd64" else "AArch64"
    require(re.search(r"Machine:\s+" + re.escape(machine) + r"\s*$", header, re.MULTILINE) is not None, "DASH library architecture differs from the selected package")
    dynamic = run("readelf", "--dynamic", str(library))
    require("(SONAME)" not in dynamic, "DASH library unexpectedly declares a SONAME")
    needed = sorted(re.findall(r"Shared library: \[([^]]+)\]", dynamic))
    require("libprotobuf.so.32" in needed, "DASH library no longer uses the selected protobuf ABI")

    print(json.dumps({
        "architecture": args.architecture,
        "deb_sha256": entry["sha256"],
        "header_count": len(selected) - 1,
        "library_sha256": expected["usr/lib/libdashapi.so"],
        "runtime_tar_sha256": sha256(args.runtime_tar),
        "needed": needed,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
