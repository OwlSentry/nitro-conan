cmake_minimum_required(VERSION 3.15)
project(test_package LANGUAGES C CXX)

find_package(nitro CONFIG REQUIRED)

add_executable(test_package test_package.cpp)
set_property(TARGET test_package PROPERTY CXX_STANDARD 14)

# nitf-c++ transitively pulls in nitf-c, nrt-c, all coda-oss support
# modules, and (if enabled) j2k-c + bundled openjpeg.
target_link_libraries(test_package PRIVATE NITRO::nitf-c++)