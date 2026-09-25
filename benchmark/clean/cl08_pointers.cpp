#include <iostream>
using namespace std;
int main() {
    int x = 42;
    int* p = &x;
    int& r = x;
    cout << *p << " " << r << endl;
    return 0;
}
