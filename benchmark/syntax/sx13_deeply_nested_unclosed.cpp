#include <iostream>
using namespace std;

int main() {
    for (int i = 0; i < 5; i++) {
        if (i % 2 == 0) {
            while (true) {
                cout << "deeply nested" << endl;
                break;
            }
        // missing closing brace for if block
    }
    return 0;
}
