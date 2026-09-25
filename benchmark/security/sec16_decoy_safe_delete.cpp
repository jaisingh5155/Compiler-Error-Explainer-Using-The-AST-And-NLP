#include <iostream>
using namespace std;
int main() {
    int* p = new int(42);
    cout << *p << endl;
    delete p;
    p = nullptr;
    return 0;
}
