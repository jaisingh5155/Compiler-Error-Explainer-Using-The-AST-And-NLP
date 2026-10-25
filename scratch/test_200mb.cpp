
#include <iostream>
#include <vector>
#include <cstring>
int main() {
    size_t sz = 200 * 1024 * 1024;
    char* p = new char[sz];
    std::memset(p, 1, sz);
    std::cout << "Allocated and touched " << sz << " bytes\n";
    delete[] p;
    return 0;
}
