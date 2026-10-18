#!/bin/bash
# Run only in the disposable native Debian CI container.
set -euo pipefail
test -f /.dockerenv
test "${SONIC_DEB_TEST_CONTAINER:-}" = 1
package_directory=$(realpath "$1")
export DEBIAN_FRONTEND=noninteractive
packages=(libdashapi libprotobuf32t64)
for package in "${packages[@]}"; do
    test "$(dpkg-query -W -f='${Status}' "$package")" = 'install ok installed'
done
test "$(dpkg-query -W -f='${Version}' libdashapi)" = 1.0.0
test "$(dpkg-query -W -f='${Version}' libprotobuf32t64)" = 3.21.12+sonic.1
ldconfig -p | grep -F libprotobuf.so.32
dpkg-query -S /usr/lib/libdashapi.so
apt-get check
test -z "$(dpkg --audit)"
apt-get -y --reinstall --no-install-recommends install "$package_directory"/*.deb
apt-get check
apt-get -y remove "${packages[@]}"
test ! -e /usr/lib/libdashapi.so
test ! -e /usr/bin/dash_api_utils
test ! -d /usr/lib/python3/dist-packages/dash_api
apt-get -y --no-install-recommends install "$package_directory"/*.deb
apt-get -y purge "${packages[@]}"
test ! -e /usr/lib/libdashapi.so
test ! -d /usr/lib/python3/dist-packages/dash_api
if ldconfig -p | grep -F libprotobuf.so.32; then
    echo 'Protobuf remained in the library cache after purge' >&2
    exit 1
fi
apt-get check
test -z "$(dpkg --audit)"
printf '%s\n' '{"configuration":"passed","source_protobuf_upgrade":"passed","reinstall":"passed","remove":"passed","purge":"passed"}' > "$package_directory/installation.json"
