import os
from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import (
    apply_conandata_patches, copy, export_conandata_patches, get, rmdir, rm,
    replace_in_file,
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
        "shared":        [True, False],
        "fPIC":          [True, False],
        "enable_j2k":    [True, False],   # ENABLE_J2K   (bundled openjpeg)
        "enable_jpeg":   [True, False],   # ENABLE_JPEG  (bundled libjpeg, runtime plugin)
        "enable_zip":    [True, False],   # ENABLE_ZIP   (bundled zlib)
        "enable_pcre":   [True, False],   # ENABLE_PCRE  (bundled pcre2)
        "with_uuid":     [True, False],   # ENABLE_UUID — Linux/FreeBSD only
        "preload_tres":  [True, False],   # NITRO 2.11.6+: static TRE preloading (public macro)
        "enable_hdf5":   [True, False],   # ENABLE_HDF5 — Linux-only in current form
    }
    default_options = {
        "shared":        False,
        "fPIC":          True,
        "enable_j2k":    True,
        "enable_jpeg":   True,
        "enable_zip":    True,
        "enable_pcre":   True,
        "with_uuid":     True,
        "preload_tres":  True,
        # coda-oss's xml.lite hard-asserts XMLCh == char16_t; CCI xerces defaults
        # to uint16_t. Pin the type so the assert holds.
        "xerces-c/*:char_type": "char16_t",
         "enable_hdf5":  False,
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

        # Add an option gate around the bundled HDF5 driver. Defaults ON, so
        # Linux builds behave exactly as before. The macOS branch of generate()
        # flips it off because the vendored H5pubconf.h includes <features.h>,
        # which is glibc-only. Settings-agnostic by design — Conan 2 forbids
        # self.settings access in source().
        drivers_cml = os.path.join(
            self.source_folder, "externals", "coda-oss",
            "modules", "drivers", "CMakeLists.txt",
        )
        replace_in_file(
            self, drivers_cml,
            'add_subdirectory("hdf5")',
            'option(CODA_BUILD_HDF5 "Build the bundled HDF5 driver" ON)\n'
            'if (CODA_BUILD_HDF5)\n'
            '    add_subdirectory("hdf5")\n'
            'endif()',
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
        tc.cache_variables["ENABLE_J2K"]  = bool(self.options.enable_j2k)
        tc.cache_variables["ENABLE_JPEG"] = bool(self.options.enable_jpeg)
        tc.cache_variables["ENABLE_ZIP"]  = bool(self.options.enable_zip)
        tc.cache_variables["ENABLE_PCRE"] = bool(self.options.enable_pcre)
        tc.cache_variables["ENABLE_UUID"] = bool(self.options.get_safe("with_uuid", False))
        tc.cache_variables["XML_HOME"] = self.dependencies["xerces-c"].package_folder
        # macOS: keep install_name @rpath-relative so consumers' dyld resolution
        # works after the package moves between cache slots.
        tc.cache_variables["CMAKE_INSTALL_NAME_DIR"] = "@rpath"
        if self.settings.os == "Macos":
            # coda-oss's XML_HOME link-probe (modules/drivers/xml/xerces/
            # CMakeLists.txt:36-50) only adds `pthread` to its check_cxx_source_
            # compiles call. Apple xerces needs CoreServices/CoreFoundation
            # frameworks too, so the probe fails. Skip it — Conan's xerces is
            # known good.
            tc.cache_variables["XERCES_HOME_VALID"] = True
            # Xcode 15 / Apple clang 15+ defaults -Wimplicit-function-declaration
            # to an error. coda-oss's vendored zlib (gzlib.c) calls lseek without
            # including <unistd.h> because gzguts.h gates that include on
            # HAVE_UNISTD_H, which the driver build doesn't set. Demote to warning
            # so the bundled C drivers (zlib, jpeg, pcre2) still compile cleanly.
            tc.extra_cflags.append("-Wno-error=implicit-function-declaration")
            # coda-oss unconditionally passes GCC-only warning flags (-Wduplicated-
            # branches, -Wtrampolines, -Wno-maybe-uninitialized) on non-MSVC builds.
            # Apple clang doesn't recognise them and errors under -Werror. Demote
            # unknown-warning-option to a warning so they stay visible in logs but
            # don't fail the build. Applies to both C and C++ — Backtrace.cpp is C++,
            # the driver sources are C.
            unknown_warn = "-Wno-error=unknown-warning-option"
            tc.extra_cflags.append(unknown_warn)
            tc.extra_cxxflags.append(unknown_warn)
            tc.cache_variables["CODA_BUILD_HDF5"] = False

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