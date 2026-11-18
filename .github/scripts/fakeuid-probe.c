/*
 * CI probe for oracle-free/23/fakeuid.c.
 * Usage: fakeuid-probe <file> <expected uid>
 * Calls every stat entry point the shim wraps on <file> and prints the uid each
 * one reports. Exits 1 if any differs from <expected uid> or none ran.
 *
 * Exported symbols are looked up with dlsym(RTLD_DEFAULT) so a preloaded shim is
 * what gets called. Names this glibc does not export (stat/lstat/fstat/fstatat
 * and *64 on glibc < 2.33) are skipped there; the header calls below cover them,
 * since the headers route them to the __*xstat* names.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static unsigned expected;
static int failures, checks;

static void report(const char *name, int res, unsigned uid) {
    checks++;
    if (res != 0) {
        printf("FAIL %-14s returned %d\n", name, res);
        failures++;
    } else if (uid != expected) {
        printf("FAIL %-14s uid=%u expected=%u\n", name, uid, expected);
        failures++;
    } else {
        printf("ok   %-14s uid=%u\n", name, uid);
    }
}

/* Returns the symbol to call, or NULL (and prints a skip) if libc lacks it */
static void *sym(void *libc, const char *name) {
    if (!dlsym(libc, name)) {
        printf("skip %-14s not exported by this glibc\n", name);
        return NULL;
    }
    return dlsym(RTLD_DEFAULT, name);
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <file> <expected uid>\n", argv[0]);
        return 2;
    }
    const char *path = argv[1];
    expected = (unsigned) strtoul(argv[2], NULL, 10);
    int fd = open(path, O_RDONLY);
    void *libc = dlopen("libc.so.6", RTLD_NOW | RTLD_NOLOAD);
    if (fd < 0 || !libc) {
        perror("setup");
        return 2;
    }

    struct stat st;
    struct stat64 st64;
    struct statx stx;
    void *f;

    /* Direct calls, by exported symbol name */
#define PATH_CALL(name, buf) \
    if ((f = sym(libc, #name))) { int r = ((int (*)(const char *, __typeof__(buf) *)) f)(path, &buf); report(#name, r, buf.st_uid); }
#define FD_CALL(name, buf) \
    if ((f = sym(libc, #name))) { int r = ((int (*)(int, __typeof__(buf) *)) f)(fd, &buf); report(#name, r, buf.st_uid); }
#define AT_CALL(name, buf) \
    if ((f = sym(libc, #name))) { int r = ((int (*)(int, const char *, __typeof__(buf) *, int)) f)(AT_FDCWD, path, &buf, 0); report(#name, r, buf.st_uid); }
#define XPATH_CALL(name, buf) \
    if ((f = sym(libc, #name))) { int r = ((int (*)(int, const char *, __typeof__(buf) *)) f)(_STAT_VER, path, &buf); report(#name, r, buf.st_uid); }
#define XFD_CALL(name, buf) \
    if ((f = sym(libc, #name))) { int r = ((int (*)(int, int, __typeof__(buf) *)) f)(_STAT_VER, fd, &buf); report(#name, r, buf.st_uid); }
#define XAT_CALL(name, buf) \
    if ((f = sym(libc, #name))) { int r = ((int (*)(int, int, const char *, __typeof__(buf) *, int)) f)(_STAT_VER, AT_FDCWD, path, &buf, 0); report(#name, r, buf.st_uid); }

    PATH_CALL(stat, st)
    PATH_CALL(lstat, st)
    FD_CALL(fstat, st)
    AT_CALL(fstatat, st)
    PATH_CALL(stat64, st64)
    PATH_CALL(lstat64, st64)
    FD_CALL(fstat64, st64)
    AT_CALL(fstatat64, st64)
    XPATH_CALL(__xstat, st)
    XPATH_CALL(__lxstat, st)
    XFD_CALL(__fxstat, st)
    XAT_CALL(__fxstatat, st)
    XPATH_CALL(__xstat64, st64)
    XPATH_CALL(__lxstat64, st64)
    XFD_CALL(__fxstat64, st64)
    XAT_CALL(__fxstatat64, st64)
    if ((f = sym(libc, "statx"))) {
        int r = ((int (*)(int, const char *, int, unsigned, struct statx *)) f)(AT_FDCWD, path, 0, STATX_UID, &stx);
        report("statx", r, stx.stx_uid);
    }

    /* Header calls, as an ordinary program compiled against this glibc makes them.
       Each call is sequenced before its uid is read. */
    int r;
    r = stat(path, &st); report("stat()", r, st.st_uid);
    r = lstat(path, &st); report("lstat()", r, st.st_uid);
    r = fstat(fd, &st); report("fstat()", r, st.st_uid);
    r = fstatat(AT_FDCWD, path, &st, 0); report("fstatat()", r, st.st_uid);
    r = stat64(path, &st64); report("stat64()", r, st64.st_uid);
    r = lstat64(path, &st64); report("lstat64()", r, st64.st_uid);
    r = fstat64(fd, &st64); report("fstat64()", r, st64.st_uid);
    r = fstatat64(AT_FDCWD, path, &st64, 0); report("fstatat64()", r, st64.st_uid);
    r = statx(AT_FDCWD, path, 0, STATX_UID, &stx); report("statx()", r, stx.stx_uid);

    printf("%d/%d checks reported uid %u\n", checks - failures, checks, expected);
    return (failures || checks == 0) ? 1 : 0;
}
