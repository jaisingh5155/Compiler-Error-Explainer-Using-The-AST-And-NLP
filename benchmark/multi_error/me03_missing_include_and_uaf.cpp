#include <iostream>
using namespace std;
int main() {
    vector<int> v;
    int* p = new int(5);
    delete p;
    cout << *p << endl;
    return 0;
}
