// Minimal smoke test: construct a NITF 2.1 Record via the C++ wrapper.
// This exercises the C++ surface, base C library, and (transitively) all
// coda-oss support modules linked in. No plug-in loading required.
//
// Catches the coda-oss except::Throwable base class — nitf::NITFException
// derives from it but NOT from std::exception, so a bare std::exception
// handler will let the exception escape and abort the program.
#include <iostream>
#include <import/nitf.hpp>

int main() {
    try {
        nitf::Record record(NITF_VER_21);
        std::cout << "NITRO smoke test PASSED -- nitf::Record constructed.\n";
        return 0;
    } catch (const except::Throwable& e) {
        std::cerr << "NITRO except::Throwable: " << e.toString() << "\n";
        return 1;
    } catch (const std::exception& e) {
        std::cerr << "NITRO std::exception: " << e.what() << "\n";
        return 1;
    } catch (...) {
        std::cerr << "NITRO unknown exception (not derived from "
                     "except::Throwable or std::exception).\n";
        return 1;
    }
}