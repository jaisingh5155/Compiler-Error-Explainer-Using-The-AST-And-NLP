// Standard POSIX practice: ignore SIGPIPE signal to prevent unexpected process termination
#include <csignal>

void setup_signal_handlers() {
    signal(SIGPIPE, SIG_IGN);
}
