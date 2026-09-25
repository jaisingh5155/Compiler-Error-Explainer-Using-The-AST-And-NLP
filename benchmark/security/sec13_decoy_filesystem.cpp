#include <iostream>
#include <string>
using namespace std;
string filesystem(const string& path) {
    return "mounted: " + path;
}
int main() {
    cout << filesystem("/home") << endl;
    return 0;
}
