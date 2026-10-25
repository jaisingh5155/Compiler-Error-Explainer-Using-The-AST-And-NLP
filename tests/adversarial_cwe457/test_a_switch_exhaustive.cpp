#include <iostream>

int test_switch_exhaustive(int mode) {
    int val;
    switch (mode) {
        case 1:
            val = 10;
            break;
        case 2:
            val = 20;
            break;
        default:
            val = 30;
            break;
    }
    return val;
}

int main() {
    std::cout << test_switch_exhaustive(1) << std::endl;
    return 0;
}
