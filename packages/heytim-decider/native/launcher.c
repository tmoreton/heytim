/* A signed native launcher for the app's relocatable standalone CPython runtime. */
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX], python[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0 || realpath(executable, resolved) == NULL) {
        fputs("Cannot resolve the Decider launcher path.\n", stderr);
        return 1;
    }
    char *end = strrchr(resolved, '/');
    if (end == NULL) return 1;
    *end = '\0';
    end = strrchr(resolved, '/');
    if (end == NULL) return 1;
    *end = '\0';
    int length = snprintf(python, sizeof(python),
        "%s/../../Resources/HeyTimDeciderRuntime/bin/python3.12", resolved);
    if (length < 0 || (size_t)length >= sizeof(python)) {
        fputs("Decider runtime path is too long.\n", stderr);
        return 1;
    }
    char **arguments = calloc((size_t)argc + 5, sizeof(char *));
    if (arguments == NULL) return 1;
    arguments[0] = python;
    arguments[1] = "-I"; /* Ignore ambient Python paths and user site packages. */
    arguments[2] = "-B"; /* Keep the signed bundle read-only. */
    arguments[3] = "-m";
    arguments[4] = "heytim_decider";
    for (int i = 1; i < argc; i++) arguments[i + 4] = argv[i];
    execv(python, arguments);
    perror("Cannot start the bundled Decider runtime");
    free(arguments);
    return 1;
}
