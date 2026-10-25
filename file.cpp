#include <iostream>
int main() {
    volatile long long x = 0;
    for (int i = 0; i < 5000000; ++i) x += i;
    std::cout << x << std::endl;
    return 0;
}