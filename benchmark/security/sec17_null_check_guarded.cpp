#include <iostream>
using namespace std;
int main() {
    int* p = nullptr;
    if (p != nullptr) {
        cout << *p << endl;
    }
    return 0;
}
