#include <cstring>
#include <cstdio>
int main() {
    char src[256] = "a very long string that could overflow the dest buffer";
    char dest[8];
    strcpy(dest, src);
    printf("%s\n", dest);
    return 0;
}
