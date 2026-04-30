import os
from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import (
    apply_conandata_patches, copy, export_conandata_patches, get, rmdir, rm,
)
from conan.tools.scm import Version

required_conan_version = ">=2.0.9"


class NitroConan(ConanFile):
    name = "nitro"
    description = (
        "NITRO (NITFio) — full-fledged, extensible C/C++ library for reading "
        "and writing the U.S. DoD National Imagery Transmission Format (NITF)."
    )
    license = "LGPL-3.0-or-later"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://github.com/mdaus/nitro"
    topics = ("nitf", "nitro", "geospatial", "imagery", "remote-sensing", "dod")

    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"

    options = {
        "shared":         [True, False],
        "fPIC":           [True, False],
        "with_openjpeg":  [True, False],   # ENABLE_J2K
        "with_jpeg":      [True, False],   # ENABLE_JPEG
        "with_zlib":      [True, False],   # ENABLE_ZIP
        "with_pcre2":     [True, False],   # ENABLE_PCRE
        "with_xml":       [True, False],   # XML_HOME (Xerces-C)
        "with_uuid":      [True, False],   # ENABLE_UUID — Linux only
        "preload_tres":   [True, False],   # 2.11.6+ static TRE preloading
    }
    default_options = {
        "shared":         False,
        "fPIC":           True,
        "with_openjpeg":  True,
        "with_jpeg":      True,
        "with_zlib":      True,
        "with_pcre2":     True,
        "with_xml":       False,
        "with_uuid":      True,
        "preload_tres":   True,
    }

    # ---- helpers ---------------------------------------------------------

    @property
    def _min_cppstd(self):
        # NITRO-2.11.x requires C++14
        return 14

    @property
    def _compilers_minimum_version(self):
        return {
            "gcc": "7",
            "clang": "5",
            "apple-clang": "10",
            "msvc": "192",      # VS 2019 16.2
            "Visual Studio": "16",
        }

    # ---- recipe lifecycle ------------------------------------------------

    def export_sources(self):
        export_conandata_patches(self)

    def config_options(self):
        if self.settings.os == "Windows":
            self.options.rm_safe("fPIC")
            self.options.rm_safe("with_uuid")  # uuid driver is *nix-only
        if self.settings.os == "Macos":
            # macOS provides uuid via libSystem; coda-oss's bundled uuid driver
            # is gated on UNIX AND NOT APPLE. Force off to avoid confusion.
            self.options.with_uuid = False

    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")

    def layout(self):
        cmake_layout(self, src_folder="src")

    # ---- dependencies ----------------------------------------------------

    def requirements(self):
        # NITRO/coda-oss bundles its own openjpeg, libjpeg, pcre2, zlib,
        # xerces-c under externals/coda-oss/modules/drivers/. The upstream
        # *_HOME mechanism for using external installs is not robust against
        # ConanCenter's layouts (e.g. openjpeg headers at include/openjpeg-2.5/).
        # We let coda-oss compile its bundled versions; they end up linked
        # statically into nrt-c / nitf-c / the j2k plug-in. This matches what
        # upstream's own conanfile.py does.
        pass

    def validate(self):
        # We deliberately limit the recipe to POSIX to start with; Windows
        # builds work upstream but install-tree layout and DLL exports
        # require additional patching that is out of scope here.
        if self.settings.os not in ("Linux", "Macos", "FreeBSD"):
            raise ConanInvalidConfiguration(
                f"{self.ref}: this recipe currently supports Linux, macOS, FreeBSD. "
                f"Windows support requires additional patches; PRs welcome."
            )

        if self.settings.compiler.cppstd:
            check_min_cppstd(self, self._min_cppstd)
        minver = self._compilers_minimum_version.get(str(self.settings.compiler))
        if minver and Version(self.settings.compiler.version) < minver:
            raise ConanInvalidConfiguration(
                f"{self.ref} requires {self.settings.compiler} >= {minver} for C++14."
            )

        # arm64 sanity: works, but emit a hint if cross-building.
        if self.settings.arch not in ("x86_64", "armv8", "armv8.3"):
            self.output.warning(
                f"{self.ref}: arch {self.settings.arch} is untested upstream; "
                f"x86_64 and armv8 (Apple Silicon, Linux aarch64) are exercised."
            )

    def build_requirements(self):
        self.tool_requires("cmake/[>=3.22 <4]")

    # ---- source ----------------------------------------------------------

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)

    def _patch_sources(self):
        # All source modifications live as unified diffs under patches/
        # and are registered in conandata.yml.
        apply_conandata_patches(self)

    # ---- generate / build ------------------------------------------------

    def generate(self):
        tc = CMakeToolchain(self)

        # Build flavour
        tc.cache_variables["BUILD_SHARED_LIBS"]   = bool(self.options.shared)
        tc.cache_variables["CMAKE_POSITION_INDEPENDENT_CODE"] = bool(
            self.options.get_safe("fPIC", True) or self.options.shared
        )

        # Bindings + tests + tooling — all OFF
        tc.cache_variables["ENABLE_PYTHON"]       = False
        tc.cache_variables["ENABLE_SWIG"]         = False
        tc.cache_variables["ENABLE_JARS"]         = False
        tc.cache_variables["ENABLE_BOOST"]        = False
        tc.cache_variables["CODA_BUILD_TESTS"]    = False
        tc.cache_variables["CODA_INSTALL_TESTS"]  = False
        tc.cache_variables["NITRO_PYTHON"]        = False  # legacy alias, harmless

        # Optional features → coda-oss flags. With no *_HOME set, coda-oss
        # compiles the bundled tarball under externals/coda-oss/modules/drivers/
        # and links it statically into nrt-c / nitf-c / the plug-ins.
        tc.cache_variables["ENABLE_J2K"]   = bool(self.options.with_openjpeg)
        tc.cache_variables["ENABLE_JPEG"]  = bool(self.options.with_jpeg)
        tc.cache_variables["ENABLE_ZIP"]   = bool(self.options.with_zlib)
        tc.cache_variables["ENABLE_PCRE"]  = bool(self.options.with_pcre2)
        tc.cache_variables["ENABLE_UUID"]  = bool(
            self.options.get_safe("with_uuid", False)
        )

        # NITRO 2.11.6+ feature
        tc.preprocessor_definitions["NITRO_PRELOAD_TRES"] = (
            "1" if self.options.preload_tres else "0"
        )

        tc.generate()

        deps = CMakeDeps(self)
        deps.generate()

    def build(self):
        self._patch_sources()
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    # ---- package ---------------------------------------------------------

    def package(self):
        copy(self, "COPYING",         dst=os.path.join(self.package_folder, "licenses"),
             src=os.path.join(self.source_folder, "modules", "c", "nitf"))
        copy(self, "COPYING.LESSER",  dst=os.path.join(self.package_folder, "licenses"),
             src=os.path.join(self.source_folder, "modules", "c", "nitf"))

        cmake = CMake(self)
        cmake.install()

        # Strip CLI/test/dev cruft installed by coda-oss & nitro.
        rmdir(self, os.path.join(self.package_folder, "share", "doc"))
        rmdir(self, os.path.join(self.package_folder, "share", "man"))
        rmdir(self, os.path.join(self.package_folder, "share", "applications"))
        rmdir(self, os.path.join(self.package_folder, "share", "cmake"))
        rmdir(self, os.path.join(self.package_folder, "lib", "pkgconfig"))
        rmdir(self, os.path.join(self.package_folder, "lib", "cmake"))
        # Drop sample apps (show_nitf, show_nitf++, etc.)
        if os.path.isdir(os.path.join(self.package_folder, "bin")):
            rmdir(self, os.path.join(self.package_folder, "bin"))
        # Static-only builds: kill any stray .so/.dylib/.dll except TRE plugins.
        if not self.options.shared:
            patterns = ["*.so*", "*.dylib", "*.dll"]
            libdir = os.path.join(self.package_folder, "lib")
            for pat in patterns:
                rm(self, pat, libdir, recursive=True)
            # TRE plugins must remain shared even in static builds — they
            # live in share/nitf/plugins and are dlopen()ed.

    # ---- package_info: model components matching the actual installed libs

    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "nitro")
        self.cpp_info.set_property("cmake_target_name", "nitro::nitro")
        self.cpp_info.set_property("pkg_config_name",  "nitro")

        # ---- nrt-c: low-level NITF runtime (C only) ---------------------
        nrt_c = self.cpp_info.components["nrt-c"]
        nrt_c.set_property("cmake_target_name", "NITRO::nrt-c")
        nrt_c.set_property("cmake_target_aliases", ["nrt-c"])
        nrt_c.libs = ["nrt-c"]
        nrt_c.includedirs = ["include"]
        if self.settings.os in ("Linux", "FreeBSD"):
            nrt_c.system_libs = ["dl", "m", "pthread"]
        if self.settings.os == "Macos":
            nrt_c.frameworks = ["CoreFoundation"]

        # ---- nitf-c: NITF reader/writer (C only) ------------------------
        nitf_c = self.cpp_info.components["nitf-c"]
        nitf_c.set_property("cmake_target_name", "NITRO::nitf-c")
        nitf_c.set_property("cmake_target_aliases", ["nitf-c"])
        nitf_c.libs = ["nitf-c"]
        nitf_c.requires = ["nrt-c"]
        nitf_c.defines = [
            f'NITF_DEFAULT_PLUGIN_PATH="{os.path.join(self.package_folder, "share", "nitf", "plugins")}"',
        ]

        # ---- nitf-c++: full C++ NITF API + bundled coda-oss support ----
        # Lib order matters for static archives on GNU ld (single-pass).
        # The observed dep direction is sys-c++ → str-c++ (sys-c++/DateTime.cpp
        # uses str::getPrecision<T>), so str-c++ must come AFTER sys-c++.
        # Likewise io-c++ and mt-c++ build on top of sys-c++, so they go
        # before sys-c++. CMake silently de-duplicates target_link_libraries
        # entries (keeps first), so listing a lib twice is a no-op — the
        # order has to be right on the first pass.
        # The j2k-c plug-in wrapper and bundled openjpeg are folded in here
        # when with_openjpeg=True; bundled libjpeg is loaded at runtime via
        # the JPEG TRE plug-in (share/nitf/plugins/), not link-time.
        nitf_cpp = self.cpp_info.components["nitf-c++"]
        nitf_cpp.set_property("cmake_target_name", "NITRO::nitf-c++")
        nitf_cpp.set_property("cmake_target_aliases", ["nitf-c++"])
        cxx_libs = ["nitf-c++"]
        if self.options.with_openjpeg:
            cxx_libs += ["j2k-c", "openjpeg"]
        cxx_libs += [
            # High-level coda-oss modules first (consumers of others)
            "logging-c++",
            "plugin-c++",
            "io-c++",
            "mt-c++",
            "math-c++",
            # sys-c++ before str-c++: sys-c++/DateTime.cpp uses str::*<T>
            "sys-c++",
            "str-c++",
            "re-c++",
            "types-c++",
            "mem-c++",
            "except-c++",
        ]
        if self.options.with_pcre2:
            cxx_libs.append("pcre2-8")
        if self.options.get_safe("with_uuid"):
            cxx_libs.append("uuid")
        nitf_cpp.libs = cxx_libs
        nitf_cpp.requires = ["nitf-c"]

        # ---- Aggregate target: nitro::nitro = nitf-c++ ------------------
        # Default top-level target is what most users want.
        nitro_agg = self.cpp_info.components["nitro"]
        nitro_agg.set_property("cmake_target_name", "nitro::nitro")
        nitro_agg.requires = ["nitf-c++"]

        # Runtime: tell consumers where the TRE plug-ins live so dlopen works.
        plugin_dir = os.path.join(self.package_folder, "share", "nitf", "plugins")
        self.runenv_info.define_path("NITF_PLUGIN_PATH", plugin_dir)
        self.cpp_info.builddirs = []