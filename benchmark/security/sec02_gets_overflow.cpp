#include <cstdio>
int main() {
    char buf[16];
    printf("Enter name: ");
    gets(buf);
    printf("Hello %s\n", buf);
    return 0;
}
