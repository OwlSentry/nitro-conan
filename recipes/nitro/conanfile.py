import os
from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import (
    apply_conandata_patches, copy, export_conandata_patches, get, rmdir, rm,
)
from conan.tools.apple import fix_apple_shared_install_name

required_conan_version = ">=2.4"


class NitroConan(ConanFile):
    name = "nitro"
    version = "2.11.7"
    description = (
        "NITRO (NITFio) — full-fledged, extensible C/C++ library for reading "
        "and writing the U.S. DoD National Imagery Transmission Format (NITF)."
    )
    license = "LGPL-2.1-or-later"
    url = "https://github.com/OwlSentry/nitro-conan"
    homepage = "https://github.com/mdaus/nitro"
    topics = ("nitf", "nitro", "geospatial", "imagery", "remote-sensing", "dod")

    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"

    options = {
        "shared":       [True, False],
        "fPIC":         [True, False],
        "enable_j2k":   [True, False],   # ENABLE_J2K   (bundled openjpeg)
        "enable_jpeg":  [True, False],   # ENABLE_JPEG  (bundled libjpeg, runtime plugin)
        "enable_zip":   [True, False],   # ENABLE_ZIP   (bundled zlib)
        "enable_pcre":  [True, False],   # ENABLE_PCRE  (bundled pcre2)
        "with_uuid":    [True, False],   # ENABLE_UUID — Linux/FreeBSD only
        "preload_tres": [True, False],   # NITRO 2.11.6+: static TRE preloading (public macro)
        "enable_hdf5":  [True, False],   # CODA_ENABLE_HDF5 — upstream toggle; HDF5 driver is glibc-only
    }
    default_options = {
        "shared":       False,
        "fPIC":         True,
        "enable_j2k":   True,
        "enable_jpeg":  True,
        "enable_zip":   True,
        "enable_pcre":  True,
        "with_uuid":    True,
        "preload_tres": True,
        "enable_hdf5":  False,
        # coda-oss's xml.lite hard-asserts XMLCh == char16_t; CCI xerces defaults
        # to uint16_t. Pin the type so the assert holds.
        "xerces-c/*:char_type": "char16_t",
    }

    implements = ["auto_shared_fpic"]

    @property
    def _min_cppstd(self):
        return 14

    def export_sources(self):
        export_conandata_patches(self)

    def config_options(self):
        if self.settings.os not in ("Linux", "FreeBSD"):
            # coda-oss's bundled uuid driver is gated on UNIX AND NOT APPLE.
            self.options.rm_safe("with_uuid")

    def layout(self):
        cmake_layout(self, src_folder="src")

    def requirements(self):
        self.requires("xerces-c/3.2.5")

    def validate(self):
        if self.settings.os not in ("Linux", "Macos", "FreeBSD"):
            raise ConanInvalidConfiguration(
                f"{self.ref}: Linux, macOS, FreeBSD only. Windows requires "
                f"additional patches."
            )
        if self.settings.compiler.cppstd:
            check_min_cppstd(self, self._min_cppstd)

        xch = self.dependencies["xerces-c"].options.get_safe("char_type")
        if xch != "char16_t":
            raise ConanInvalidConfiguration(
                f"{self.ref} requires xerces-c/*:char_type=char16_t (got {xch}). "
                f"coda-oss's ValidatorXerces.cpp asserts XMLCh == char16_t."
            )

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)
        apply_conandata_patches(self)

        # The remaining source modifications are macOS portability fixes that
        # preserve Linux behavior (every change adds an Apple arm or gates a
        # glibc-only include behind __has_include). They live as replace_in_file
        # rather than patches because content-anchored matching is more robust
        # than line-anchored hunk headers when small upstream drift can occur.

        # Conf.h: gate <features.h> on __has_include and add Apple arms to the
        # CODA_OSS_POSIX*_SOURCE macros so alignedAlloc and the platform dispatch
        # find their POSIX paths on macOS.
        sys_conf_h = os.path.join(
            self.source_folder, "externals", "coda-oss",
            "modules", "c++", "sys", "include", "sys", "Conf.h",
        )
        replace_in_file(
            self, sys_conf_h,
            "#ifndef _WIN32\n"
            "#include <features.h>\n"
            "#endif",
            "#ifndef _WIN32\n"
            "#  if defined(__has_include)\n"
            "#    if __has_include(<features.h>)\n"
            "#      include <features.h>\n"
            "#    endif\n"
            "#  elif defined(__linux__)\n"
            "#    include <features.h>\n"
            "#  endif\n"
            "#endif",
        )
        replace_in_file(
            self, sys_conf_h,
            "#undef CODA_OSS_POSIX_SOURCE\n"
            "#if defined(_POSIX_C_SOURCE) && (_POSIX_C_SOURCE >= 1)\n"
            "#define CODA_OSS_POSIX_SOURCE _POSIX_C_SOURCE\n"
            "#endif",
            "#undef CODA_OSS_POSIX_SOURCE\n"
            "#if defined(_POSIX_C_SOURCE) && (_POSIX_C_SOURCE >= 1)\n"
            "#define CODA_OSS_POSIX_SOURCE _POSIX_C_SOURCE\n"
            "#elif defined(__APPLE__)\n"
            "// macOS is POSIX-compliant but doesn't define _POSIX_C_SOURCE the same way.\n"
            "#define CODA_OSS_POSIX_SOURCE 200809L\n"
            "#endif",
        )
        replace_in_file(
            self, sys_conf_h,
            "#undef CODA_OSS_POSIX2001_SOURCE\n"
            "#if defined(CODA_OSS_POSIX_SOURCE) && (_POSIX_C_SOURCE >= 200112L)\n"
            "#define CODA_OSS_POSIX2001_SOURCE _POSIX_C_SOURCE\n"
            "#endif",
            "#undef CODA_OSS_POSIX2001_SOURCE\n"
            "#if defined(CODA_OSS_POSIX_SOURCE) && (_POSIX_C_SOURCE >= 200112L)\n"
            "#define CODA_OSS_POSIX2001_SOURCE _POSIX_C_SOURCE\n"
            "#elif defined(__APPLE__)\n"
            "#define CODA_OSS_POSIX2001_SOURCE 200809L\n"
            "#endif",
        )
        replace_in_file(
            self, sys_conf_h,
            "#undef CODA_OSS_POSIX2008_SOURCE\n"
            "#if defined(CODA_OSS_POSIX2001_SOURCE) && (_POSIX_C_SOURCE >= 200809L)\n"
            "#define CODA_OSS_POSIX2008_SOURCE _POSIX_C_SOURCE\n"
            "#endif",
            "#undef CODA_OSS_POSIX2008_SOURCE\n"
            "#if defined(CODA_OSS_POSIX2001_SOURCE) && (_POSIX_C_SOURCE >= 200809L)\n"
            "#define CODA_OSS_POSIX2008_SOURCE _POSIX_C_SOURCE\n"
            "#elif defined(__APPLE__)\n"
            "#define CODA_OSS_POSIX2008_SOURCE 200809L\n"
            "#endif",
        )

        # bit.h: detect <byteswap.h> via __has_include rather than __GNUC__
        # (Apple Clang defines __GNUC__ but lacks the glibc header). Fall back
        # to __builtin_bswap_* on platforms without the header.
        bit_h = os.path.join(
            self.source_folder, "externals", "coda-oss",
            "modules", "c++", "coda_oss", "include", "coda_oss", "bit.h",
        )
        replace_in_file(
            self, bit_h,
            '#ifdef __GNUC__\n'
            '#include <byteswap.h>  // "These functions are GNU extensions."\n'
            '#endif',
            "#if defined(__has_include) && __has_include(<byteswap.h>)\n"
            "#  include <byteswap.h>\n"
            "#  define CODA_OSS_HAS_BSWAP_BUILTINS 1\n"
            "#endif",
        )
        replace_in_file(
            self, bit_h,
            "    #elif defined(__GNUC__)\n"
            "    inline uint16_t byteswap(uint16_t val) noexcept\n"
            "    {\n"
            "        return bswap_16(val);\n"
            "    }\n"
            "    inline uint32_t byteswap(uint32_t val) noexcept\n"
            "    {\n"
            "        return bswap_32(val);\n"
            "    }\n"
            "    inline uint64_t byteswap(uint64_t val) noexcept\n"
            "    {\n"
            "        return bswap_64(val);\n"
            "    }",
            "    #elif defined(CODA_OSS_HAS_BSWAP_BUILTINS)\n"
            "    inline uint16_t byteswap(uint16_t val) noexcept\n"
            "    {\n"
            "        return bswap_16(val);\n"
            "    }\n"
            "    inline uint32_t byteswap(uint32_t val) noexcept\n"
            "    {\n"
            "        return bswap_32(val);\n"
            "    }\n"
            "    inline uint64_t byteswap(uint64_t val) noexcept\n"
            "    {\n"
            "        return bswap_64(val);\n"
            "    }\n"
            "    #elif defined(__GNUC__) || defined(__clang__)\n"
            "    inline uint16_t byteswap(uint16_t val) noexcept\n"
            "    {\n"
            "        return __builtin_bswap16(val);\n"
            "    }\n"
            "    inline uint32_t byteswap(uint32_t val) noexcept\n"
            "    {\n"
            "        return __builtin_bswap32(val);\n"
            "    }\n"
            "    inline uint64_t byteswap(uint64_t val) noexcept\n"
            "    {\n"
            "        return __builtin_bswap64(val);\n"
            "    }",
        )

        # OS.h: complete the MacOS arm of PlatformType (upstream had it as a
        # // MacOS comment placeholder).
        sys_os_h = os.path.join(
            self.source_folder, "externals", "coda-oss",
            "modules", "c++", "sys", "include", "sys", "OS.h",
        )
        replace_in_file(
            self, sys_os_h,
            "    Windows,\n"
            "    Linux,\n"
            "    // MacOS\n"
            "};",
            "    Windows,\n"
            "    Linux,\n"
            "    MacOS,\n"
            "};",
        )
        replace_in_file(
            self, sys_os_h,
            "#if defined(_WIN32)\n"
            "constexpr auto Platform = PlatformType::Windows;\n"
            "#elif defined(CODA_OSS_POSIX2008_SOURCE)\n"
            "constexpr auto Platform = PlatformType::Linux;\n"
            "#else\n"
            '#error "Unknown platform."\n'
            "#endif",
            "#if defined(_WIN32)\n"
            "constexpr auto Platform = PlatformType::Windows;\n"
            "#elif defined(__APPLE__)\n"
            "constexpr auto Platform = PlatformType::MacOS;\n"
            "#elif defined(CODA_OSS_POSIX2008_SOURCE)\n"
            "constexpr auto Platform = PlatformType::Linux;\n"
            "#else\n"
            '#error "Unknown platform."\n'
            "#endif",
        )
        replace_in_file(
            self, sys_os_h,
            "template <>\n"
            "inline std::string platformName<PlatformType::Linux>()\n"
            "{\n"
            '    return "linux-gnu";\n'
            "}",
            "template <>\n"
            "inline std::string platformName<PlatformType::Linux>()\n"
            "{\n"
            '    return "linux-gnu";\n'
            "}\n"
            "template <>\n"
            "inline std::string platformName<PlatformType::MacOS>()\n"
            "{\n"
            '    return "darwin";\n'
            "}",
        )

    def generate(self):
        tc = CMakeToolchain(self)
        # Bindings + tests + tooling — all OFF.
        tc.cache_variables["ENABLE_PYTHON"]      = False
        tc.cache_variables["ENABLE_SWIG"]        = False
        tc.cache_variables["ENABLE_JARS"]        = False
        tc.cache_variables["ENABLE_BOOST"]       = False
        tc.cache_variables["CODA_BUILD_TESTS"]   = False
        tc.cache_variables["CODA_INSTALL_TESTS"] = False
        # Optional features. With no *_HOME set, coda-oss compiles its bundled
        # tarballs under externals/coda-oss/modules/drivers/ and links them
        # statically into nrt-c / nitf-c / the plug-ins. The exception is XML,
        # where Xerces from Conan tends to "just work" via XML_HOME.
        tc.cache_variables["ENABLE_J2K"]   = bool(self.options.enable_j2k)
        tc.cache_variables["ENABLE_JPEG"]  = bool(self.options.enable_jpeg)
        tc.cache_variables["ENABLE_ZIP"]   = bool(self.options.enable_zip)
        tc.cache_variables["ENABLE_PCRE"]  = bool(self.options.enable_pcre)
        tc.cache_variables["ENABLE_UUID"]  = bool(self.options.get_safe("with_uuid", False))
        tc.cache_variables["CODA_ENABLE_HDF5"] = bool(self.options.enable_hdf5)
        tc.cache_variables["XML_HOME"] = self.dependencies["xerces-c"].package_folder
        # macOS: keep install_name @rpath-relative so consumers' dyld resolution
        # works after the package moves between cache slots.
        tc.cache_variables["CMAKE_INSTALL_NAME_DIR"] = "@rpath"

        if self.settings.os == "Macos":
            # coda-oss's XML_HOME link-probe only adds `pthread` to its
            # check_cxx_source_compiles call. Apple xerces additionally needs
            # CoreServices/CoreFoundation frameworks (the link-probe patch in
            # 0002 fixes the test source); pre-set the cache variable so the
            # probe is skipped — Conan's xerces is known good.
            tc.cache_variables["XERCES_HOME_VALID"] = True

            # Per-warning -Wno-error=<name> demotions covering two failure modes:
            #  1. Apple Clang (Xcode 15+) default-errors — fail regardless of
            #     -Werror; hit by vintage C in bundled zlib/jpeg/pcre2.
            #  2. -Werror promotions of warnings Apple Clang emits but GCC
            #     doesn't — GCC-only -W flag names, dead assignments, deprecated
            #     POSIX functions in the macOS SDK, etc.
            #
            # Bare -Wno-error doesn't stick because coda-oss's project-level
            # add_compile_options(-Werror) lands *after* our CMAKE_CXX_FLAGS in
            # the compile line. Per-warning demotions ARE sticky: Clang doesn't
            # re-promote them via a later -Werror.
            macos_warning_flags = [
                "-Wno-error=implicit-function-declaration",
                "-Wno-error=implicit-int",
                "-Wno-error=incompatible-function-pointer-types",
                "-Wno-error=unknown-warning-option",
                "-Wno-error=unused-but-set-variable",
                "-Wno-error=deprecated-declarations",
                "-Wno-error=unused-function",
                "-Wno-error=invalid-utf8",   # Manip.cpp Latin-1 high bytes in comments
            ]
            tc.extra_cflags.extend(macos_warning_flags)
            tc.extra_cxxflags.extend(macos_warning_flags)

        # Public header switch — must be visible to consumers too (see package_info).
        if self.options.preload_tres:
            tc.preprocessor_definitions["NITRO_PRELOAD_TRES"] = "1"
        tc.generate()
        CMakeDeps(self).generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        fix_apple_shared_install_name(self)
        copy(self, "COPYING",        src=os.path.join(self.source_folder, "modules", "c", "nitf"),
                                     dst=os.path.join(self.package_folder, "licenses"))
        copy(self, "COPYING.LESSER", src=os.path.join(self.source_folder, "modules", "c", "nitf"),
                                     dst=os.path.join(self.package_folder, "licenses"))
        CMake(self).install()
        # Strip dev/test/desktop cruft that consumers don't need.
        for d in ("share/doc", "share/man", "share/applications", "share/cmake",
                  "lib/pkgconfig", "lib/cmake"):
            rmdir(self, os.path.join(self.package_folder, d))
        if not self.options.shared:
            # Defense in depth — coda-oss should produce only .a in static builds.
            # TRE plugins live in share/nitf/plugins and are unaffected.
            for pat in ("*.so*", "*.dylib", "*.dll"):
                rm(self, pat, os.path.join(self.package_folder, "lib"), recursive=True)

    def package_info(self):
        # Match upstream's installed CMake config so existing find_package(coda-oss)
        # consumers work without changes.
        self.cpp_info.set_property("cmake_file_name",   "coda-oss")
        self.cpp_info.set_property("cmake_target_name", "coda-oss::coda-oss")

        nrt_c = self.cpp_info.components["nrt-c"]
        nrt_c.set_property("cmake_target_name", "nrt-c")
        nrt_c.libs = ["nrt-c"]
        if self.settings.os in ("Linux", "FreeBSD"):
            nrt_c.system_libs = ["dl", "m", "pthread"]

        nitf_c = self.cpp_info.components["nitf-c"]
        nitf_c.set_property("cmake_target_name", "nitf-c")
        nitf_c.libs = ["nitf-c"]
        nitf_c.requires = ["nrt-c"]
        if self.options.preload_tres:
            nitf_c.defines.append("NITRO_PRELOAD_TRES=1")

        # Static-archive link order on a single-pass linker (GNU ld):
        # consumers of others come first, foundations last. except-c++ is the
        # very last because every other coda-oss lib uses except::Throwable.
        cxx_libs = ["nitf-c++"]
        if self.options.enable_j2k:
            cxx_libs += ["j2k-c", "openjpeg"]
        cxx_libs += [
            "logging-c++", "plugin-c++", "io-c++", "mt-c++", "math-c++",
            "re-c++", "sys-c++", "str-c++",
            "types-c++", "mem-c++",
            "except-c++",
        ]
        if self.options.enable_pcre:
            cxx_libs.append("pcre2-8")
        if self.options.get_safe("with_uuid"):
            cxx_libs.append("uuid")

        nitf_cpp = self.cpp_info.components["nitf-c++"]
        nitf_cpp.set_property("cmake_target_name", "nitf-c++")
        nitf_cpp.libs = cxx_libs
        nitf_cpp.requires = ["nitf-c"]
        nitf_cpp.requires.append("xerces-c::xerces-c")

        # Runtime: tell consumers where the TRE plug-ins live so dlopen finds them.
        # This is the ONLY mechanism that actually controls the runtime probe;
        # the NITF_DEFAULT_PLUGIN_PATH define is baked into nitf-c at build time.
        self.runenv_info.define_path(
            "NITF_PLUGIN_PATH",
            os.path.join(self.package_folder, "share", "nitf", "plugins"),
        )