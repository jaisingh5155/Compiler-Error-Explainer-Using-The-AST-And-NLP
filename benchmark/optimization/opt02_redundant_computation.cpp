#include <iostream>

int process(int a, int b) {
    int x = a * b + 10;
    int y = a * b + 20;
    return x + y;
}

int main() {
    return process(2, 3);
}
