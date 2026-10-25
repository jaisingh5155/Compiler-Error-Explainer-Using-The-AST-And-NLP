
#include <iostream>
int main() {
    volatile long long sum = 0;
    for (long long i = 0; i < 200000000LL; ++i) {
        sum += i;
    }
    std::cout << sum << "\n";
    return 0;
}
