import os
from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import apply_conandata_patches, copy, export_conandata_patches, get, rmdir, rm
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
        "enable_xml":    [True, False],   # XML_HOME (Xerces-C — wired below if True)
        "with_uuid":     [True, False],   # ENABLE_UUID — Linux/FreeBSD only
        "preload_tres":  [True, False],   # NITRO 2.11.6+: static TRE preloading (public macro)
    }
    default_options = {
        "shared":        False,
        "fPIC":          True,
        "enable_j2k":    True,
        "enable_jpeg":   True,
        "enable_zip":    True,
        "enable_pcre":   True,
        "enable_xml":    False,
        "with_uuid":     True,
        "preload_tres":  True,
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
        if self.options.enable_xml:
            self.requires("xerces-c/3.2.5")

    def validate(self):
        if self.settings.os not in ("Linux", "Macos", "FreeBSD"):
            raise ConanInvalidConfiguration(
                f"{self.ref}: Linux, macOS, FreeBSD only. Windows requires "
                f"additional patches."
            )
        if self.settings.compiler.cppstd:
            check_min_cppstd(self, self._min_cppstd)
        if self.options.enable_xml:
            xch = self.dependencies["xerces-c"].options.get_safe("char_type")
            if xch != "char16_t":
                raise ConanInvalidConfiguration(
                    f"{self.ref} with enable_xml=True requires xerces-c/*:char_type=char16_t "
                    f"(got {xch}). coda-oss's ValidatorXerces.cpp asserts XMLCh == char16_t."
                )

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)
        apply_conandata_patches(self)

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
        if self.options.enable_xml:
            tc.cache_variables["XML_HOME"] = self.dependencies["xerces-c"].package_folder
        # macOS: keep install_name @rpath-relative so consumers' dyld resolution
        # works after the package moves between cache slots.
        tc.cache_variables["CMAKE_INSTALL_NAME_DIR"] = "@rpath"
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
        if self.options.enable_xml:
            nitf_cpp.requires.append("xerces-c::xerces-c")

        # Runtime: tell consumers where the TRE plug-ins live so dlopen finds them.
        # This is the ONLY mechanism that actually controls the runtime probe;
        # the NITF_DEFAULT_PLUGIN_PATH define is baked into nitf-c at build time.
        self.runenv_info.define_path(
            "NITF_PLUGIN_PATH",
            os.path.join(self.package_folder, "share", "nitf", "plugins"),
        )