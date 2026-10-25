#include <iostream>

void test_loop_deref() {
    int* p = nullptr;
    for (int i = 0; i < 5; ++i) {
        *p = i;
    }
}

int main() {
    test_loop_deref();
    return 0;
}
