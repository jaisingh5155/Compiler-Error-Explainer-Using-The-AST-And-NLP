#include <iostream>
using namespace std;
struct Node { int val; Node* next; };
int main() {
    Node* n = nullptr;
    cout << n->val << endl;
    return 0;
}
