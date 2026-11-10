#define _GNU_SOURCE
#include <dlfcn.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

/*
 * In OpenShift, containers run under arbitrary UIDs (e.g. 1002720000) with GID 0.
 * Oracle Database 23ai strictly validates that the caller's effective UID matches
 * the build-time owner UID of ORACLE_HOME (54321), raising ORA-12753 and
 * terminating with ORA-12547 (TNS:lost contact) during local Bequeath connection
 * if they differ.
 *
 * This shim intercepts stat syscalls across glibc and reports ORACLE_HOME files
 * (owned by 54321) as owned by the current effective UID, satisfying Oracle's
 * security check for any arbitrary runtime UID.
 */

static int (*real_stat)(const char *path, struct stat *buf) = NULL;
static int (*real_lstat)(const char *path, struct stat *buf) = NULL;
static int (*real_fstat)(int fd, struct stat *buf) = NULL;
static int (*real_fstatat)(int dirfd, const char *pathname, struct stat *buf, int flags) = NULL;
static int (*real_xstat)(int ver, const char *path, struct stat *buf) = NULL;
static int (*real_lxstat)(int ver, const char *path, struct stat *buf) = NULL;
static int (*real_fxstat)(int ver, int fd, struct stat *buf) = NULL;
static int (*real_fxstatat)(int ver, int dirfd, const char *pathname, struct stat *buf, int flags) = NULL;

static inline void fix_stat(struct stat *buf) {
    if (buf && buf->st_uid == 54321) {
        buf->st_uid = geteuid();
    }
}

int stat(const char *path, struct stat *buf) {
    if (!real_stat) real_stat = (int (*)(const char *, struct stat *))dlsym(RTLD_NEXT, "stat");
    int res = real_stat(path, buf);
    if (res == 0) fix_stat(buf);
    return res;
}

int lstat(const char *path, struct stat *buf) {
    if (!real_lstat) real_lstat = (int (*)(const char *, struct stat *))dlsym(RTLD_NEXT, "lstat");
    int res = real_lstat(path, buf);
    if (res == 0) fix_stat(buf);
    return res;
}

int fstat(int fd, struct stat *buf) {
    if (!real_fstat) real_fstat = (int (*)(int, struct stat *))dlsym(RTLD_NEXT, "fstat");
    int res = real_fstat(fd, buf);
    if (res == 0) fix_stat(buf);
    return res;
}

int fstatat(int dirfd, const char *pathname, struct stat *buf, int flags) {
    if (!real_fstatat) real_fstatat = (int (*)(int, const char *, struct stat *, int))dlsym(RTLD_NEXT, "fstatat");
    int res = real_fstatat(dirfd, pathname, buf, flags);
    if (res == 0) fix_stat(buf);
    return res;
}

int __xstat(int ver, const char *path, struct stat *buf) {
    if (!real_xstat) real_xstat = (int (*)(int, const char *, struct stat *))dlsym(RTLD_NEXT, "__xstat");
    int res = real_xstat(ver, path, buf);
    if (res == 0) fix_stat(buf);
    return res;
}

int __lxstat(int ver, const char *path, struct stat *buf) {
    if (!real_lxstat) real_lxstat = (int (*)(int, const char *, struct stat *))dlsym(RTLD_NEXT, "__lxstat");
    int res = real_lxstat(ver, path, buf);
    if (res == 0) fix_stat(buf);
    return res;
}

int __fxstat(int ver, int fd, struct stat *buf) {
    if (!real_fxstat) real_fxstat = (int (*)(int, int, struct stat *))dlsym(RTLD_NEXT, "__fxstat");
    int res = real_fxstat(ver, fd, buf);
    if (res == 0) fix_stat(buf);
    return res;
}

int __fxstatat(int ver, int dirfd, const char *pathname, struct stat *buf, int flags) {
    if (!real_fxstatat) real_fxstatat = (int (*)(int, int, const char *, struct stat *, int))dlsym(RTLD_NEXT, "__fxstatat");
    int res = real_fxstatat(ver, dirfd, pathname, buf, flags);
    if (res == 0) fix_stat(buf);
    return res;
}
