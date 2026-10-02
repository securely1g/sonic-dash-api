# Bazel source build

Bazel generates C++ and Python bindings from every `proto/*.proto`, compiles
DASH's utility library and SWIG extension, and produces runtime and matching
debug tar archives. Native AMD64 and ARM64 builds are supported on Debian
Trixie with Bazel 8.5.1 and Python 3.13. Other configurations, including ARMHF
and Bookworm, continue to use the existing Make build.

```sh
# Run inside native Debian Trixie. Add --config=aarch64 on ARM64.
bazel build //:libdashapi_pkg //:libdashapi_pkg.debug_symbols
bazel test --test_output=errors \
  //bazel:utils_test //bazel:python_test \
  //bazel:runtime_consumer_test //bazel:source_contract_test
```

The contract test depends on both archives, so the test command also builds
them. Archive inspection requires `tar`, `binutils`, and `gdb`.

## Targets and deployment

| Target | Output |
| --- | --- |
| `//:dashapi` | Public C++ headers and the source-built shared library |
| `//:shared_library` | Linked `libdashapi.so` |
| `//misc:dash_api` | Generated Python modules and SWIG extension for Bazel consumers |
| `//:libdashapi_pkg` | Runtime/install tar with Make's installed paths |
| `//:libdashapi_pkg.debug_symbols` | Detached symbols for the packaged library and extension |

The runtime tar installs headers under `/usr/include/dash_api`,
`libdashapi.so` under `/usr/lib`, Python modules, typing stubs and the SWIG
extension under `/usr/lib/python3/dist-packages/dash_api`, and the
`/usr/bin/dash_api_utils` CLI. One install mapping defines both package inputs
and their destination paths and modes.

The library's SONAME is `libdashapi.so`. Every protobuf descriptor is retained
for dynamic JSON conversion. The Python extension resolves Python symbols
from its interpreter without linking `libpython`.

`sonic_deploy_tar(force_debug_build = True)` produces the stripped runtime
and detached symbols from the same linked ELF files. Symbols install under
`/usr/lib/debug/.build-id`; `DebugSymbolsInfo` lets downstream debug containers
collect them while extending the matching runtime image. Containers can consume
the tars directly. This component does not define Bazel DEB or container targets.

## Dependencies

[`MODULE.bazel`](../MODULE.bazel) declares versions and
[`.bazelrc`](../.bazelrc) uses one reviewed SONiC registry branch,
`codex/protobuf-source-tools`, plus Bazel Central Registry for CI and local
commands. The branch supplies the execution-tool and Protobuf entries that
are not yet on registry `main`, from [infra #10](https://github.com/securely1g/sonic-build-infra/pull/10),
[registry #24](https://github.com/securely1g/sonic-bazel-registry/pull/24), and
[registry #25](https://github.com/securely1g/sonic-bazel-registry/pull/25).

| Dependency | Role |
| --- | --- |
| Debian Protobuf 3.21.12 | Declared execution-side compiler/schema inputs and target C++ headers/runtime through the shared infrastructure and `protobuf-debian` module |
| SWIG 4.3.0 | Execution-side wrapper generation through shared SONiC rules |
| Debian Boost Filesystem and System 1.83 | Target libraries for the existing C++ utility tests |
| Hash-pinned Python wheels | Protobuf 6.33.5 for Bazel consumers; Click and Pytest for tests |
| Debian `python3-protobuf` 3.21.12 | System-Python validation of the installed tars |

DASH itself is compiled from source; pinned APT packages and wheels supply
external dependencies. The Distroless override keeps the native protobuf header
fix selected despite older dependency versions that sort above it. CI verifies
the resolved infrastructure and Distroless declarations and retains the module graph.

The deployed runtime needs `libc6`, `libgcc-s1`, `libstdc++6`,
`libprotobuf32t64`, Python 3.13, `python3-click`, and `python3-protobuf`.
[CI](../.github/workflows/bazel.yml) installs these and its inspection tools
from the same signed Debian snapshots as the shared toolchain, inside a
digest-pinned Trixie image. Snapshot dates and the image digest are recorded in
the workflow; actual APT sources and installed versions are retained as evidence.

`MODULE.bazel.lock` is ignored and generated in update mode from a fresh
checkout. CI retains it under `validation/generated/MODULE.bazel.lock` and
checks that tracked files stay clean. Keep package locks, versions, source
integrity values pinned; follow the maintained registry branch and do not commit
this generated lock.

## Validation and artifacts

| Test | Coverage |
| --- | --- |
| `utils_test` | Existing five C++ utility tests |
| `python_test` | Every generated module and stub, optional/timestamp behavior, and the existing CLI roundtrip test |
| `runtime_consumer_test` | C++/C API behavior and loading of the selected source-built library |
| `source_contract_test` | Complete tar inventory, ownership, modes, architecture, SONAME, dependencies, build IDs, debuglink checksums and GDB source-line lookup |
| `installed_tar_test.py` (CI) | Installed C/Python/SWIG/CLI roundtrips with system Python and standard paths, without Bazel runfiles or custom library search paths |

Required source checks are `Bazel (AMD64)` and `Bazel (ARM64)`. Both run the
four Bazel tests uncached, extract the built tars with their external runtime
dependencies, and run installed-consumer validation. Their Actions artifacts are:

- `sonic-dash-api-packages-<architecture>-<revision>`: runtime/debug tars,
  headers, linked library, compiled consumer and SHA-256 provenance.
- `sonic-dash-api-validation-<architecture>-<revision>`: test results,
  build/test events, generation/compilation actions, environment and dependency
  records, declarations and the generated lock.

Evidence identifies the tested revision and architecture. Symbol checks cover
DASH's two ELF outputs; external runtime libraries need their own matching symbols.
