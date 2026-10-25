#include <iostream>

int test_lambda_init() {
    int val;
    auto init = [&val]() {
        val = 50;
    };
    init();
    return val;
}

int main() {
    std::cout << test_lambda_init() << std::endl;
    return 0;
}
