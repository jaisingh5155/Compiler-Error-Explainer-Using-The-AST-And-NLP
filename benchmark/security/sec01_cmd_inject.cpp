#include <cstdlib>
#include <iostream>
using namespace std;
int main() {
    char input[128];
    cout << "Enter filename: ";
    cin >> input;
    char cmd[256];
    sprintf(cmd, "cat %s", input);
    system(cmd);
    return 0;
}
