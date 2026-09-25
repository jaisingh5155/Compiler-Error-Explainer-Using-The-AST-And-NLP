#include <iostream>
using namespace std;
int main() {
    int* p = new int(42);
    delete p;
    cout << *p << endl;
    return 0;
}
