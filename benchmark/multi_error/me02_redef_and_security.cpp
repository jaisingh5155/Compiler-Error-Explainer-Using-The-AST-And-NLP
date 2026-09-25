#include <iostream>
using namespace std;
int main() {
    int x = 5;
    int x = 10;
    int* p = new int(42);
    delete p;
    delete p;
    return 0;
}
