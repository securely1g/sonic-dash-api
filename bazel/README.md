# Bazel prebuilt C++ interface

The Bazel module exposes the existing Trixie `libdashapi` packages as a
dependency-owned C++ interface. It does not compile protobuf sources or replace
the Make build. `prebuilt.json` records the AMD64 and ARM64 package hashes and
their Azure build, artifact, member, and producer source revision. Both packages
come from build `1231190` at source
`2ce7ce648ee77a76fcf567191eb4b9ed6cfeed38`.

The module extension downloads the recorded artifact ZIP, accepts only the DEB
member with the pinned SHA-256, and extracts that package with Bazel's repository
APIs. Other ZIP contents do not contribute to the repository. A missing artifact
or changed package fails the fetch; the module does not select a replacement.

## Targets

- `@sonic_dash_api//:dashapi` provides all `dash_api/*.h` headers and the existing
  `libdashapi.so`. It preserves the `dash_api/...` include root and imports the
  shared library without changing its bytes or adding a SONAME. The interface
  does not add protobuf dependencies; consumers provide their selected matching
  protobuf headers and runtime, as SWSS does today.
- `@sonic_dash_api//:prebuilt_files` exposes the selected input DEB, imported C++
  files, and `IMPORTS.json` for validation and artifact retention. This is the
  original input package, not a package produced by Bazel.

The target selects AMD64 or ARM64 from the target CPU and is limited to Linux.
The validated configurations use native Debian Trixie execution and target
architectures with Bazel 8.5.1. Cross execution and other distributions are
outside this import's validation.

## Validation

`//bazel:prebuilt_contract_test` verifies the selected package hash and control
identity, compares every exported header and library byte with the DEB payload,
and checks the ELF architecture, absent SONAME, and `libprotobuf.so.32` runtime
dependency. It uses `dpkg-deb` and `readelf` from the native Trixie test image.

`//bazel:runtime_consumer_test` compiles against `utils.h`, links the imported
library, exercises its C++ and C table-name APIs and protobuf JSON conversion,
and confirms that the loaded file is the selected import. Its test-only Debian
dependency set uses infrastructure 0.0.7's pinned Trixie suites and the existing
Distroless `libprotobuf-dev:libprotobuf` C++ target. Production consumers retain
their own protobuf dependency selection.

Registry CI resolves the immutable module source, fetches the recorded package
for each native architecture, builds `prebuilt_files` and the runtime consumer,
and runs both tests. It needs no local package manifest or registry runner setup
hook. The downstream SWSS build separately validates the generated headers and
linkage with its current protobuf path.
