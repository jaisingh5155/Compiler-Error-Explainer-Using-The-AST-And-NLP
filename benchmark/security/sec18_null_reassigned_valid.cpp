#include <iostream>
using namespace std;
int main() {
    int* p = nullptr;
    int x = 42;
    p = &x;
    cout << *p << endl;
    return 0;
}
