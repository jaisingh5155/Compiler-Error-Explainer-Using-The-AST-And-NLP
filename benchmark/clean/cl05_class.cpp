#include <iostream>
#include <string>
using namespace std;
class Animal {
    string name;
public:
    Animal(const string& n) : name(n) {}
    void speak() const { cout << name << " says hello" << endl; }
};
int main() {
    Animal a("Cat");
    a.speak();
    return 0;
}
