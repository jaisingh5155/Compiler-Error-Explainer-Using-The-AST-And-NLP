#include <iostream>
#include <cassert>

void test_assert_guard() {
    int* p = nullptr;
    assert(p != nullptr);
    *p = 42;
}

int main() {
    test_assert_guard();
    return 0;
}
