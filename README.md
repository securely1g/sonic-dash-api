# sonic-dash-api

This repository hosts the DASH API definition for the SONiC project. The schema of DASH APP DB is at [DASH APP DB](https://github.com/sonic-net/DASH/blob/main/documentation/general/dash-sonic-hld.md#32-dash-app-db) and all entries of DASH APP DB will be encoded as protobuf.

The [Bazel source build](bazel/README.md) generates C++ and Python bindings and
builds native Trixie runtime and debug tar archives for AMD64 and ARM64.

## Protobuf Convention

1. File name use underscore case, E.G. `acl_rule.proto`
2. All file except common utility should include and only include one message of entry and one message of its key.
3. Message name of entry use camel case. E.G. `AclRule`.
4. Message name of entry key use the entry name with a fixed postfix `Key`. E.G. `AclRuleKey`.
5. If the value of entry is a list, the item use the entry name with a fixed postfix `Item`. E.G. `RouteTypeItem`.
6. Member variable use underscore case. E.G. `src_addr`.
7. For enumerations type, the enum name use camel case, E.G. `IpVersion`
8. The field of enum use full capital with underscore case, and the enum name use as the prefix for each field. E.G. 
`IP_VERSION_IPV4`

## Redis DB

1. Table name will be full capital with underscore. And the prefix `DASH` and postfix `Table` will be added to entry name. E.G. `DASH_VNET_MAPPING_TABLE`
2. The key message is sequentially joint as the Redis key with colon separator. E.G. `AclRuleKey{group_id=group1, rule_num=3}`, the key of Redis entry will be `DASH_ACL_RULE_TABLE:group1:3`
3. The value is the entry message with the bytes array of protobuf

## GNMI

TODO

### Debian runtime packages

Bazel can also build actual packages for `apt-get install`:

```sh
bazel build //:libdashapi_deb //:libprotobuf32t64_deb
```

`libdashapi` uses the same compiled library, generated Python bindings and
headers as the existing runtime TAR. Its metadata comes from `debian/control`
and `debian/changelog`; Debian's tools calculate dependencies from the compiled
files. The Protobuf module owns the matching source-built `libprotobuf32t64`
package and its library-cache trigger. Existing runtime and debug TARs remain
available.

CI validates both Debian archives on native AMD64 and ARM64, installs them with
APT, checks the existing installed consumers, then exercises reinstall, removal
and purge. It also upgrades Debian's Protobuf package to the SONiC source build.
While the package-tool and registry prerequisites are in Draft, CI selects the
reviewed dependency branch through `bazel/ci/prepare_debian_registry.py`; the
normal `.bazelrc` continues to use the registry's `main` branch.

The Debian package also declares the Python interpreter, Click and Protobuf
dependencies used by its installed CLI and generated modules. Debian's original
`dh_python3` helper generates bytecode setup and cleanup scripts, while keeping
the existing `_utils.so` name and script shebang. Removal checks import the
package first and then verify that no Python cache directory remains.
