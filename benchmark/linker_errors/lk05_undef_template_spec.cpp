#include <iostream>
using namespace std;
template<typename T>
T getValue();
int main() {
    cout << getValue<int>() << endl;
    return 0;
}
