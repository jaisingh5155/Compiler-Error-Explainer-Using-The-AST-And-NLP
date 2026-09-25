#include <cstdio>
int main() {
    char input[128];
    fgets(input, sizeof(input), stdin);
    printf(input);
    return 0;
}
