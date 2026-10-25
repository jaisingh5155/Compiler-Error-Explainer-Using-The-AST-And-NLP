#include <iostream>

int compute(int x) {
    int result = x * 2;
    return result;
    std::cout << "Unreachable output" << std::endl;
    result += 10;
}

int main() {
    return compute(5);
}
