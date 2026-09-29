"""Pinned prebuilt C++ interface for the existing SONiC DASH packages."""

_ARCHITECTURES = {
    "amd64": "x86_64",
    "arm64": "arm64",
}

_ARCHIVE_SUFFIXES = [".xz", ".gz", ".zst", ""]

def _file_url(path):
    value = str(path)
    for char, escaped in {
        "%": "%25",
        " ": "%20",
        "#": "%23",
        "?": "%3F",
        "[": "%5B",
        "]": "%5D",
        "{": "%7B",
        "}": "%7D",
        "|": "%7C",
        "\\": "%5C",
        "^": "%5E",
        "`": "%60",
        "\"": "%22",
        "<": "%3C",
        ">": "%3E",
        "\n": "%0A",
        "\r": "%0D",
        "\t": "%09",
    }.items():
        value = value.replace(char, escaped)
    return "file://" + value

def _archive_in(directory, basename):
    matches = [
        directory.get_child(basename + suffix)
        for suffix in _ARCHIVE_SUFFIXES
        if directory.get_child(basename + suffix).exists
    ]
    if len(matches) != 1:
        fail("Expected one {} archive in {}, found {}".format(basename, directory, matches))
    return matches[0]

def _prebuilt_repository_impl(rctx):
    rctx.download(
        url = rctx.attr.artifact_url,
        output = "_artifact.zip",
    )
    rctx.extract("_artifact.zip", output = "_artifact", watch_archive = "no")
    member = rctx.path("_artifact/" + rctx.attr.member)
    if not member.exists:
        fail("DASH artifact is missing {}".format(rctx.attr.member))

    # The ZIP is the acquisition envelope. Only this hash-verified DEB member
    # contributes files to the repository and its public C++ interface.
    downloaded = rctx.download(
        url = _file_url(member),
        output = rctx.attr.filename,
    )
    if downloaded.sha256 != rctx.attr.sha256:
        fail("DASH DEB SHA-256 mismatch: expected {}, got {}".format(rctx.attr.sha256, downloaded.sha256))

    rctx.extract(rctx.attr.filename, output = "_deb", watch_archive = "no")
    rctx.extract(_archive_in(rctx.path("_deb"), "data.tar"), output = "payload", watch_archive = "no")
    for path in [
        "payload/usr/include/dash_api/types.pb.h",
        "payload/usr/lib/libdashapi.so",
    ]:
        if not rctx.path(path).exists:
            fail("DASH DEB is missing {}".format(path.removeprefix("payload/")))

    rctx.template(
        "BUILD.bazel",
        rctx.attr._build_template,
        substitutions = {
            "{CPU}": rctx.attr.cpu,
            "{DEB_FILENAME}": rctx.attr.filename,
        },
        executable = False,
    )
    rctx.file("IMPORTS.json", rctx.attr.provenance + "\n", executable = False)
    rctx.delete("_artifact.zip")
    rctx.delete("_artifact")
    rctx.delete("_deb")

_prebuilt_repository = repository_rule(
    implementation = _prebuilt_repository_impl,
    attrs = {
        "artifact_url": attr.string(mandatory = True),
        "cpu": attr.string(mandatory = True),
        "filename": attr.string(mandatory = True),
        "member": attr.string(mandatory = True),
        "provenance": attr.string(mandatory = True),
        "sha256": attr.string(mandatory = True),
        "_build_template": attr.label(default = Label("//bazel:BUILD.prebuilt.bazel")),
    },
)

def _prebuilt_impl(mctx):
    manifest = json.decode(mctx.read(Label("//bazel:prebuilt.json")))
    if type(manifest) != "dict" or manifest.get("schema_version") != 1 or manifest.get("distribution") != "trixie":
        fail("DASH prebuilt manifest must use schema_version 1 and distribution trixie")
    packages = manifest.get("packages")
    if type(packages) != "dict" or sorted(packages.keys()) != sorted(_ARCHITECTURES.keys()):
        fail("DASH prebuilt manifest must contain amd64 and arm64 packages")

    for architecture, cpu in _ARCHITECTURES.items():
        entry = packages[architecture]
        filename = "libdashapi_1.0.0_{}.deb".format(architecture)
        if type(entry) != "dict" or entry.get("architecture") != architecture or entry.get("package") != "libdashapi" or entry.get("version") != "1.0.0" or entry.get("filename") != filename:
            fail("Invalid DASH package identity for {}".format(architecture))
        sha256 = entry.get("sha256")
        if type(sha256) != "string" or len(sha256) != 64 or any([char not in "0123456789abcdef" for char in sha256.elems()]):
            fail("Invalid DASH package SHA-256 for {}".format(architecture))
        provenance = entry.get("provenance")
        if type(provenance) != "dict" or type(provenance.get("artifact")) != "string" or type(provenance.get("download_url")) != "string":
            fail("Invalid DASH artifact provenance for {}".format(architecture))
        if not provenance["download_url"].startswith("https://") or entry.get("member") != provenance["artifact"] + "/" + filename:
            fail("Invalid DASH artifact selection for {}".format(architecture))

        _prebuilt_repository(
            name = "sonic_dash_api_prebuilt_" + architecture,
            artifact_url = provenance["download_url"],
            cpu = cpu,
            filename = filename,
            member = entry["member"],
            provenance = json.encode_indent(entry),
            sha256 = sha256,
        )

prebuilt = module_extension(implementation = _prebuilt_impl)
