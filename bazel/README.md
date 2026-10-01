# Bazel source build

Bazel generates the C++ and Python bindings from every `proto/*.proto`, compiles
`misc/utils.cpp`, and generates and compiles the SWIG Python extension. The
build uses the shared SONiC GCC toolchain and the matching Debian Protobuf
3.21.12 compiler and `libprotobuf.so.32` runtime. DASH artifacts are produced
from this checkout; no Azure DASH package is downloaded.

The source-build module uses version `0.0.3`, so its registry versions sort after
the earlier source builds and historical `0.0.0-<commit>` prebuilt
imports independently of Git commit hash ordering. This module version is
separate from the Debian package version.

## Supported configurations

The source workflow builds natively on AMD64 and ARM64 in a pinned Debian Trixie
container, using Bazel 8.5.1 and Python 3.13. The existing Make/Azure path covers
other configurations, including ARMHF and Bookworm; those configurations have
not been validated by this Bazel change.

```sh
# Run inside native Debian Trixie. Add --config=aarch64 on ARM64.
bazel build //:libdashapi_deb //:libdashapi_dbg_deb
bazel test --test_output=errors \
  //bazel:utils_test //bazel:python_test \
  //bazel:runtime_consumer_test //bazel:source_contract_test
```

CI installs package inspection tools (`binutils`, `dpkg-deb`, and `gdb`).
Protobuf and SWIG generation use declared Bazel execution tools. Protobuf's
compiler, runtime libraries and well-known schema inputs come from shared
`sonic-build-infra` build tools, and its reusable generation rules and target
library interface are owned by the registry's `protobuf-debian` module.

## Declared external dependencies

DASH's own generated code, library and bindings are compiled from source.
Declared, pinned APT packages and wheels intentionally supply external
dependencies. Libraries linked into DASH or its tests use the target
configuration; programs run during generation are selected with `cfg = "exec"`.

| Dependency | Version and source | Use |
| --- | --- | --- |
| Protobuf compiler and schema inputs | Debian Protobuf 3.21.12 from shared snapshot-backed build tools | Execution-side code generation |
| C++ Protobuf headers and runtime | Debian Protobuf 3.21.12 through `protobuf-debian` | Target C++ library, `libprotobuf.so.32` |
| Boost Filesystem and System | Debian Boost 1.83 | Target libraries for the existing utility tests |
| SWIG | SWIG 4.3.0 through shared rules: BCR `4.3.0.bcr.2` executable and Debian support files | Execution-side Python wrapper generation |
| Python Protobuf for Bazel | Hash-pinned PyPI `protobuf==6.33.5`, including its native extension | Bazel Python consumers and tests |
| Python Protobuf for installed packages | Declared Debian `python3-protobuf` dependency, version 3.21.12 from the CI snapshot | System Python installation tests |

CI uses the digest-pinned Debian Trixie image dated `20260713`, which predates
the package snapshots. Its inspection tools and installed-package dependencies
use the same fixed Debian snapshots as the pinned infrastructure:
`20260727T143429Z` for Debian
and `20260726T121236Z` for Debian Security. APT retains signature verification;
snapshot entries disable only the expired Release-file validity window. The
validation artifact records the actual APT sources, package policy and installed
package versions. Rebuilding these external dependencies from source is outside
this component migration's scope.

## Generated dependency lock

`MODULE.bazel.lock` is generated locally and ignored by Git. A fresh checkout
does not need it: Bazel's default update mode resolves the declared dependencies
and creates the file. CI explicitly uses `--lockfile_mode=update`, checks that
the tracked checkout stays clean, and retains each architecture's generated
lock under `validation/generated/MODULE.bazel.lock` in its validation artifact.
Do not commit this generated file. Keep dependency versions, registry revisions,
source integrity values and Debian snapshot declarations pinned in their owning
modules; changing lockfile handling does not change those declared inputs.

## Targets and outputs

| Target | Output |
| --- | --- |
| `//:dashapi` | Public C++ headers under `dash_api/` and the source-built shared library |
| `//:shared_library` | Linked `libdashapi.so` for consumers and inspection |
| `//misc:dash_api` | Generated Python modules and SWIG extension for Bazel consumers |
| `//:libdashapi_pkg` | Runtime/install tar, preserving Make's installed paths |
| `//:libdashapi_pkg.debug_symbols` | Detached symbols matched to the packaged library and Python extension |
| `//:libdashapi_deb` | `libdashapi_1.0.0_<architecture>.deb` |
| `//:libdashapi_dbg_deb` | `libdashapi-dbg_1.0.0_<architecture>.deb` |

The runtime package contains the generated C++ headers and `utils.h` under
`/usr/include/dash_api`, `libdashapi.so` under `/usr/lib`, generated Python
modules and typing stubs plus `utils.py` and `_utils.so` under
`/usr/lib/python3/dist-packages/dash_api`, and `/usr/bin/dash_api_utils`.

The library declares `libdashapi.so` as its SONAME so dynamic consumers record
the installed filename. All generated protobuf descriptors are retained during
linking, including messages referenced only by dynamic JSON conversion. The
Python extension resolves Python symbols from its interpreter without an
explicit `libpython` dependency, matching the existing build's behavior.

`sonic_deploy_tar(force_debug_build = True)` splits each packaged ELF into its
stripped runtime copy and detached symbols from the same linked file. Symbols
are installed under `/usr/lib/debug/.build-id`. The runtime tar carries
`DebugSymbolsInfo` for the shared container debug-layer collector. A downstream
debug image can collect these symbols while extending its matching runtime
image; this repository does not build a container image.

## Tests and CI artifacts

- `utils_test` runs the existing five C++ utility tests.
- `python_test` imports every generated Python schema, checks typing stubs and
  protobuf optional/timestamp behavior, and runs the existing CLI roundtrip test.
- `runtime_consumer_test` exercises C++ and C APIs and verifies the process loads
  the selected source-built library.
- `source_contract_test` compares the complete installed inventory with the
  schema inputs, checks runtime and Debian payload equality, architecture,
  SONAME and dependencies, and validates both runtime/debug pairs with build IDs,
  debug-link checksums and GDB source-line lookup.
- CI also installs the generated Debian packages with their declared runtime
  dependencies. `bazel/installed_package_test.py` then checks C API, Python/SWIG,
  and installed CLI roundtrips using system Python, without Bazel runfiles or
  custom library search paths.

The required source checks are `Bazel (AMD64)` and `Bazel (ARM64)`. Open a
successful run under **Actions → Bazel** and download its **Artifacts**:

- `sonic-dash-api-packages-<architecture>-<revision>` contains runtime/debug
  Debian packages and tar archives, headers, the linked library, a compiled
  consumer, and SHA-256 provenance.
- `sonic-dash-api-validation-<architecture>-<revision>` contains test results,
  build events, source action records, environment and APT inputs, declarations,
  and the generated dependency lock used by that native build.

Build/test evidence identifies the tested commit and architecture. The package
inspection verifies symbols for DASH's two ELF outputs; third-party runtime
libraries retain their own separate symbol-package requirements.
