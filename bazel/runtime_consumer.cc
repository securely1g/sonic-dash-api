#include <dash_api/utils.h>
#include <dlfcn.h>
#include <limits.h>
#include <stdlib.h>

#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "expected the source-built libdashapi path\n";
        return 1;
    }

    try {
        const std::string table = "DASH_APPLIANCE_TABLE";
        const std::string expected = "sonic/dash.appliance.Appliance";
        if (dash::TableNameToTypeUrl(table) != expected) {
            throw std::runtime_error("C++ table-name conversion failed");
        }
        char output[128] = {};
        if (::TableNameToTypeUrl(table.c_str(), output, sizeof(output)) != expected.size() + 1 || output != expected) {
            throw std::runtime_error("C table-name conversion failed");
        }

        const std::string binary = dash::JsonStringToPbBinary(table, "{}");
        const std::string json = dash::PbBinaryToJsonString(table, binary);
        if (json.find('{') == std::string::npos || json.find('}') == std::string::npos) {
            throw std::runtime_error("protobuf JSON round trip failed");
        }

        void *symbol = dlsym(RTLD_DEFAULT, "TableNameToTypeUrl");
        Dl_info info = {};
        char expected_path[PATH_MAX] = {};
        char loaded_path[PATH_MAX] = {};
        if (symbol == nullptr || dladdr(symbol, &info) == 0 || info.dli_fname == nullptr ||
            realpath(argv[1], expected_path) == nullptr || realpath(info.dli_fname, loaded_path) == nullptr ||
            std::strcmp(expected_path, loaded_path) != 0) {
            throw std::runtime_error("consumer did not load the selected libdashapi file");
        }
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }

    std::cout << "validated the source-built libdashapi C++ and C interfaces\n";
    return 0;
}
