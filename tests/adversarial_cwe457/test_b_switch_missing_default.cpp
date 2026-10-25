#include <iostream>

int test_switch_missing_default(int mode) {
    int val;
    switch (mode) {
        case 1:
            val = 10;
            break;
        case 2:
            val = 20;
            break;
    }
    return val;
}

int main() {
    std::cout << test_switch_missing_default(3) << std::endl;
    return 0;
}
