#include <iostream>

void test_early_return() {
    int* p = nullptr;
    if (!p) return;
    *p = 5;
}

int main() {
    test_early_return();
    return 0;
}
