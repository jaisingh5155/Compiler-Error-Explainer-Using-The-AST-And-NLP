#include <iostream>

void test_ternary(bool cond) {
    int fallback = 100;
    int* p = nullptr;
    int* q = cond ? p : &fallback;
    if (!cond) {
        std::cout << *q << std::endl;
    }
}

int main() {
    test_ternary(false);
    return 0;
}
