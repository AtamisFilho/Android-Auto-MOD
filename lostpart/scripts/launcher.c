/* Self-extracting launcher for the Linux build of lostpart.
 *
 * The published binary is a small statically linked ELF with a tar.gz
 * payload appended to it.  At run time the launcher:
 *
 *   1. finds its own path through /proc/self/exe,
 *   2. reads the trailer to learn where the payload starts and how long it
 *      is,
 *   3. extracts the payload into a cache directory with the system tar,
 *      skipping the work when the cache is already populated,
 *   4. execs the bundled interpreter with the bundled application.
 *
 * The trailer sits at the very end of the file:
 *
 *     [payload tar.gz]
 *     [8 bytes] payload offset, little endian
 *     [8 bytes] payload size, little endian
 *     [21 bytes] "LOSTPART_PAYLOAD_V1\n"
 *     [17 bytes] "LOSTPART_END_V1\n"
 *
 * Build it with:
 *
 *     zig cc -target x86_64-linux-musl -static -O2 launcher.c -o launcher
 */

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define PAYLOAD_MAGIC "LOSTPART_PAYLOAD_V1\n"
#define TRAILER_MAGIC "LOSTPART_END_V1\n"
#define PAYLOAD_MAGIC_LEN (sizeof(PAYLOAD_MAGIC) - 1)
#define TRAILER_MAGIC_LEN (sizeof(TRAILER_MAGIC) - 1)
#define TRAILER_SIZE (8 + 8 + PAYLOAD_MAGIC_LEN + TRAILER_MAGIC_LEN)

/* The version is baked in at build time so that the cache directory changes
 * whenever a new binary is published. */
#ifndef LOSTPART_VERSION
#define LOSTPART_VERSION "0.0.0"
#endif

static void fail(const char *what) {
    fprintf(stderr, "lostpart: %s: %s\n", what, strerror(errno));
    exit(1);
}

static void die(const char *message) {
    fprintf(stderr, "lostpart: %s\n", message);
    exit(1);
}

/* Read the trailer that describes the appended payload. */
static int read_trailer(const char *self, uint64_t *offset, uint64_t *size) {
    FILE *f = fopen(self, "rb");
    if (!f) return -1;
    if (fseek(f, -(long)TRAILER_SIZE, SEEK_END) != 0) {
        fclose(f);
        return -1;
    }
    unsigned char trailer[TRAILER_SIZE];
    if (fread(trailer, 1, TRAILER_SIZE, f) != TRAILER_SIZE) {
        fclose(f);
        return -1;
    }
    fclose(f);

    if (memcmp(trailer + 16, PAYLOAD_MAGIC, PAYLOAD_MAGIC_LEN) != 0) return -1;
    if (memcmp(trailer + 16 + PAYLOAD_MAGIC_LEN, TRAILER_MAGIC, TRAILER_MAGIC_LEN) != 0) {
        return -1;
    }
    uint64_t parsed_offset = 0;
    uint64_t parsed_size = 0;
    for (int i = 0; i < 8; i++) {
        parsed_offset |= ((uint64_t)trailer[i]) << (8 * i);
        parsed_size |= ((uint64_t)trailer[8 + i]) << (8 * i);
    }
    *offset = parsed_offset;
    *size = parsed_size;
    return 0;
}

/* Copy the payload out of ourselves into a temporary file. */
static int extract_payload(const char *self, uint64_t offset, uint64_t size,
                           const char *destination) {
    FILE *in = fopen(self, "rb");
    if (!in) return -1;
    if (fseek(in, (long)offset, SEEK_SET) != 0) {
        fclose(in);
        return -1;
    }
    FILE *out = fopen(destination, "wb");
    if (!out) {
        fclose(in);
        return -1;
    }
    char buffer[1 << 16];
    uint64_t remaining = size;
    while (remaining > 0) {
        size_t want = sizeof(buffer);
        if ((uint64_t)want > remaining) want = (size_t)remaining;
        size_t got = fread(buffer, 1, want, in);
        if (got == 0) break;
        if (fwrite(buffer, 1, got, out) != got) {
            fclose(in);
            fclose(out);
            return -1;
        }
        remaining -= got;
    }
    fclose(in);
    if (fclose(out) != 0) return -1;
    return remaining == 0 ? 0 : -1;
}

static int run(char *const argv[]) {
    pid_t pid = fork();
    if (pid < 0) return -1;
    if (pid == 0) {
        execvp(argv[0], argv);
        _exit(127);
    }
    int status = 0;
    if (waitpid(pid, &status, 0) < 0) return -1;
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}

static int make_directory(const char *path) {
    if (mkdir(path, 0755) == 0) return 0;
    if (errno == EEXIST) return 0;
    return -1;
}

static void build_cache_path(char *out, size_t out_size, const char *home) {
    snprintf(out, out_size, "%s/.cache/lostpart/%s", home, LOSTPART_VERSION);
}

int main(int argc, char **argv) {
    char self[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", self, sizeof(self) - 1);
    if (length < 0) fail("readlink /proc/self/exe");
    self[length] = '\0';

    uint64_t payload_offset = 0;
    uint64_t payload_size = 0;
    if (read_trailer(self, &payload_offset, &payload_size) != 0) {
        die("this binary does not carry a payload");
    }

    const char *home = getenv("HOME");
    if (!home || !*home) {
        const char *tmp = getenv("TMPDIR");
        if (!tmp || !*tmp) tmp = "/tmp";
        home = tmp;
    }

    char cache_root[PATH_MAX];
    build_cache_path(cache_root, sizeof(cache_root), home);

    /* The marker file tells us the extraction already succeeded. */
    char marker[PATH_MAX];
    snprintf(marker, sizeof(marker), "%s/.ready", cache_root);

    char interpreter[PATH_MAX];
    char application[PATH_MAX];
    snprintf(interpreter, sizeof(interpreter), "%s/python/bin/python3", cache_root);
    snprintf(application, sizeof(application), "%s/app/lostpart_main.py", cache_root);

    if (access(marker, F_OK) != 0) {
        char parent[PATH_MAX];
        snprintf(parent, sizeof(parent), "%s/.cache/lostpart", home);
        if (make_directory(parent) != 0 && errno != EEXIST) fail("mkdir");
        if (make_directory(cache_root) != 0 && errno != EEXIST) fail("mkdir");

        char payload_path[PATH_MAX];
        snprintf(payload_path, sizeof(payload_path), "%s/payload.tar.gz", cache_root);
        if (extract_payload(self, payload_offset, payload_size, payload_path) != 0) {
            die("could not read the embedded payload");
        }

        /* Prefer the system tar; fall back to the interpreter we carry,
         * which has tarfile in its standard library. */
        char *tar_argv[] = {"tar", "-xzf", payload_path, "-C", cache_root, NULL};
        int status = run(tar_argv);
        if (status != 0) {
            char *python_argv[] = {
                interpreter, "-c",
                "import sys,tarfile;"
                "t=tarfile.open(sys.argv[1],'r:gz');"
                "t.extractall(sys.argv[2]);"
                "t.close()",
                payload_path, cache_root, NULL
            };
            status = run(python_argv);
            if (status != 0) die("could not unpack the embedded payload");
        }
        unlink(payload_path);

        FILE *touch = fopen(marker, "wb");
        if (touch) fclose(touch);
    }

    /* Tell the interpreter exactly where its standard library and the
     * application live, so the binary does not depend on how it was
     * unpacked. */
    char python_home[PATH_MAX];
    char python_path[PATH_MAX];
    snprintf(python_home, sizeof(python_home), "%s/python", cache_root);
    snprintf(python_path, sizeof(python_path), "%s/app", cache_root);
    setenv("PYTHONHOME", python_home, 1);
    setenv("PYTHONPATH", python_path, 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);

    char **child_argv = calloc((size_t)argc + 3, sizeof(char *));
    if (!child_argv) die("out of memory");
    child_argv[0] = interpreter;
    child_argv[1] = application;
    for (int i = 1; i < argc; i++) child_argv[i + 1] = argv[i];
    child_argv[argc + 1] = NULL;

    execv(interpreter, child_argv);
    fprintf(stderr, "lostpart: could not start the bundled interpreter: %s\n",
            strerror(errno));
    return 1;
}
