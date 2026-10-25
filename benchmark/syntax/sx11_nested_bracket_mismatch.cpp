#include <iostream>
using namespace std;

void outer() {
    auto inner = []() {
        cout << "nested lambda" << endl;
    };
    if (true) {
        cout << "inside block" << endl;
    // Missing closing brace for if block
}

int main() {
    outer();
    return 0;
}
