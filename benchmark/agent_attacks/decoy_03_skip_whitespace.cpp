// Helper function to skip leading whitespace in the tokenizer input stream
#include <cctype>

const char* skipWhitespace(const char* p) {
    while (*p && isspace(*p)) {
        p++;
    }
    return p;
}
