#include <iostream>
using namespace std;
void get_value(int* out) {
    if (out) *out = 100;
}
int main() {
    int x;
    get_value(&x);
    cout << x << endl;
    return 0;
}
