#include <iostream>

void test_double_pointer() {
    int val = 42;
    int* p = &val;
    int** pp = &p;
    **pp = 100;

    int*& pref = p;
    *pref = 200;
}

int main() {
    test_double_pointer();
    return 0;
}
