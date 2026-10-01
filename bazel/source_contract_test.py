"""Check source-built DASH packages, their complete install tree and split symbols."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import zlib


PYTHON_DIR = "usr/lib/python3/dist-packages/dash_api"
LIBRARY = "usr/lib/libdashapi.so"
EXTENSION = PYTHON_DIR + "/_utils.so"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(*arguments: str) -> str:
    result = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    require(result.returncode == 0, "command failed: " + " ".join(arguments) + "\n" + result.stderr + result.stdout)
    return result.stdout


def inventory(archive: tarfile.TarFile) -> dict[str, tuple[bytes, int]]:
    result = {}
    for member in archive:
        name = PurePosixPath(member.name)
        require(not name.is_absolute() and ".." not in name.parts, "unsafe archive path: " + member.name)
        require(member.uid == member.gid == 0, "installed archive member is not owned by root: " + member.name)
        if member.isdir():
            continue
        require(member.isfile(), "unexpected non-regular installed file: " + member.name)
        key = str(name)
        require(key not in result, "duplicate installed file: " + key)
        stream = archive.extractfile(member)
        require(stream is not None, "unreadable archive file: " + key)
        result[key] = (stream.read(), member.mode & 0o777)
    return result


def tar_inventory(path: Path) -> dict[str, tuple[bytes, int]]:
    with tarfile.open(path) as archive:
        return inventory(archive)


def deb_inventory(path: Path) -> dict[str, tuple[bytes, int]]:
    result = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(path)], capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        return inventory(archive)


def package_fields(path: Path) -> dict[str, str]:
    return dict(
        line.split(": ", 1)
        for line in run("dpkg-deb", "--field", str(path), "Package", "Version", "Architecture").splitlines()
    )


def build_id(path: Path) -> str:
    matches = re.findall(r"Build ID: ([0-9a-f]+)", run("readelf", "--notes", str(path)))
    require(len(matches) == 1, "expected one ELF build ID: " + str(path))
    return matches[0]



def check_debuglink(binary: Path, symbols: Path) -> None:
    dump = run("readelf", "--hex-dump=.gnu_debuglink", str(binary))
    contents = bytearray()
    for line in dump.splitlines():
        # readelf emits up to four 8-hex-digit words before its ASCII column.
        # Capture only those words; text in the ASCII column is not section data.
        match = re.match(r"^\s+0x[0-9a-fA-F]+\s+((?:[0-9a-fA-F]{8}(?:\s|$)){1,4})", line)
        if match:
            contents.extend(bytes.fromhex(match.group(1)))
    require(b"\0" in contents, "runtime ELF has no readable debuglink filename")
    terminator = contents.index(0)
    filename = bytes(contents[:terminator]).decode("utf-8")
    require(filename == symbols.name, "runtime debuglink does not name its matching symbols")
    # The filename is NUL-terminated, padded to four bytes, then followed by a
    # CRC stored in the ELF's byte order. GDB's build-ID lookup alone would not
    # prove that this fallback debuglink checksum matches the shipped file.
    checksum_offset = (terminator + 1 + 3) & ~3
    require(len(contents) == checksum_offset + 4, "malformed runtime debuglink section")
    elf_header = binary.read_bytes()[:6]
    require(elf_header[:4] == b"\x7fELF" and elf_header[5] in (1, 2), "unsupported ELF byte order")
    checksum = int.from_bytes(contents[checksum_offset:], "little" if elf_header[5] == 1 else "big")
    require(checksum == zlib.crc32(symbols.read_bytes()), "runtime debuglink CRC differs from its debug file")


def check_architecture(path: Path, architecture: str) -> None:
    machine = {"amd64": "Advanced Micro Devices X86-64", "arm64": "AArch64"}[architecture]
    header = run("readelf", "--file-header", str(path))
    require(re.search(r"Machine:\s+" + re.escape(machine) + r"\s*$", header, re.MULTILINE) is not None, "ELF has the wrong architecture: " + str(path))


def materialize(root: Path, files: dict[str, tuple[bytes, int]]) -> None:
    # Paths have already been checked and all members are regular files.
    for relative, (content, mode) in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        destination.chmod(mode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-tar", type=Path, required=True)
    parser.add_argument("--debug-tar", type=Path, required=True)
    parser.add_argument("--runtime-deb", type=Path, required=True)
    parser.add_argument("--debug-deb", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--proto", type=Path, action="append", required=True)
    parser.add_argument("--architecture", choices=("amd64", "arm64"), required=True)
    args = parser.parse_args()

    proto_names = {source.stem for source in args.proto}
    require(len(proto_names) == len(args.proto), "duplicate protobuf source names")
    require(all(source.is_file() for source in args.proto), "protobuf source missing from test inputs")
    # Derive installed names from the actual sources so adding a new proto must
    # also update generation and packaging; do not freeze a successful count.
    expected = {
        LIBRARY, EXTENSION, "usr/include/dash_api/utils.h", "usr/bin/dash_api_utils",
        PYTHON_DIR + "/__init__.py", PYTHON_DIR + "/utils.py",
    }
    for name in proto_names:
        expected.update({
            "usr/include/dash_api/" + name + ".pb.h",
            PYTHON_DIR + "/" + name + "_pb2.py",
            PYTHON_DIR + "/" + name + "_pb2.pyi",
        })

    runtime = tar_inventory(args.runtime_tar)
    debug = tar_inventory(args.debug_tar)
    require(set(runtime) == expected, "runtime install inventory mismatch; missing=" + str(sorted(expected - set(runtime))) + "; unexpected=" + str(sorted(set(runtime) - expected)))
    require(runtime == deb_inventory(args.runtime_deb), "runtime DEB payload differs from its deploy tar")
    require(debug == deb_inventory(args.debug_deb), "debug DEB payload differs from its symbols tar")
    for path, (_, mode) in runtime.items():
        expected_mode = 0o755 if path == "usr/bin/dash_api_utils" else 0o644
        require(mode == expected_mode, "unexpected installed file mode: " + path + " " + oct(mode))
    require(all(not path.endswith(".debug") for path in runtime), "debug files leaked into the runtime package")

    runtime_fields = package_fields(args.runtime_deb)
    debug_fields = package_fields(args.debug_deb)
    require(runtime_fields["Package"] == "libdashapi", "unexpected runtime package name")
    require(debug_fields["Package"] == "libdashapi-dbg", "unexpected debug package name")
    require(runtime_fields["Architecture"] == debug_fields["Architecture"] == args.architecture, "DEB architecture mismatch")
    require(runtime_fields["Version"] == debug_fields["Version"], "runtime/debug package version mismatch")
    debug_dependencies = run("dpkg-deb", "--field", str(args.debug_deb), "Depends")
    require("libdashapi (= " + runtime_fields["Version"] + ")" in debug_dependencies, "debug DEB must depend on the exact runtime version")
    runtime_dependencies = run("dpkg-deb", "--field", str(args.runtime_deb), "Depends")
    for package in ("libprotobuf32t64", "python3-protobuf", "python3-click"):
        require(re.search(r"(?:^|[,|]\s*)" + re.escape(package) + r"(?:\s|,|$)", runtime_dependencies) is not None, "runtime DEB omits dependency: " + package)

    records = {}
    with tempfile.TemporaryDirectory(prefix="dash-source-contract-") as temporary:
        root = Path(temporary)
        materialize(root, runtime)
        materialize(root, debug)
        expected_debug_paths = set()
        for relative in (LIBRARY, EXTENSION):
            binary = root / relative
            check_architecture(binary, args.architecture)
            dynamic = run("readelf", "--dynamic", str(binary))
            needed = re.findall(r"Shared library: \[([^]]+)\]", dynamic)
            require("libprotobuf.so.32" in needed, "DASH binary must retain the selected protobuf ABI: " + relative)
            require(not any(name.startswith("libprotobuf-lite") for name in needed), "DASH binary unnecessarily requires protobuf-lite: " + relative)
            if relative == LIBRARY:
                require(re.findall(r"Library soname: \[([^]]+)\]", dynamic) == ["libdashapi.so"], "DASH SONAME differs from its public runtime filename")
            else:
                require(not any(name.startswith("libpython") for name in needed), "Python extension must resolve Python symbols from its interpreter")
            sections = run("readelf", "--section-headers", "--wide", str(binary))
            require(not re.search(r"\s\.debug_(?:info|line)\s", sections), "runtime ELF retains DWARF: " + relative)
            identifier = build_id(binary)
            debug_path = "usr/lib/debug/.build-id/" + identifier[:2] + "/" + identifier[2:] + ".debug"
            expected_debug_paths.add(debug_path)
            symbols = root / debug_path
            require(symbols.is_file(), "matching debug file missing: " + debug_path)
            require(build_id(symbols) == identifier, "debug file build ID differs from runtime ELF")
            require(".debug_info" in run("readelf", "--section-headers", "--wide", str(symbols)), "split symbols omit DWARF")
            check_debuglink(binary, symbols)
            # Load the installed runtime ELF, not the .debug file explicitly:
            # gdb must discover its matching symbols through the installed tree.
            gdb = run(
                "gdb", "--nx", "--nh", "--batch",
                "-iex", "set auto-load off",
                "-iex", "set debuginfod enabled off",
                "-ex", "set debug-file-directory " + str(root / "usr/lib/debug"),
                "-ex", "file " + str(binary),
                "-ex", "info line dash::TableNameToTypeUrl",
            )
            require(re.search(r'Line \d+ of "[^"]*utils\.cpp"', gdb) is not None, "gdb cannot resolve source lines through split symbols: " + relative + "\n" + gdb)
            records[relative] = {"build_id": identifier, "debug_file": debug_path, "needed": needed}
        require(set(debug) == expected_debug_paths, "debug package includes missing or unrelated symbols")
        require(len(expected_debug_paths) == 2, "library and extension unexpectedly share a build ID")
        check_architecture(args.library, args.architecture)

    print(json.dumps({
        "architecture": args.architecture,
        "protobuf_sources": len(proto_names),
        "installed_files": len(runtime),
        "debug_files": len(debug),
        "runtime_tar_sha256": hashlib.sha256(args.runtime_tar.read_bytes()).hexdigest(),
        "elf": records,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
