#include <iostream>

int test_do_while() {
    int val;
    do {
        val = 42;
    } while (false);
    return val;
}

int test_for_loop() {
    int val;
    for (int i = 0; i < 1; ++i) {
        val = 100;
    }
    return val;
}

int main() {
    std::cout << test_do_while() << " " << test_for_loop() << std::endl;
    return 0;
}
