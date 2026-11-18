#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
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
 * This shim wraps every glibc stat entry point and reports files owned by 54321
 * as owned by the current effective UID, satisfying Oracle's security check for
 * any arbitrary runtime UID. It changes st_uid/stx_uid only; group ownership is
 * handled by the Dockerfile (chgrp -R 0).
 *
 * Entry points, by glibc version:
 *   - glibc < 2.33 (oraclelinux:8, glibc 2.28): programs call the versioned
 *     __xstat/__lxstat/__fxstat/__fxstatat and their *64 twins. Large-file
 *     builds, such as $ORACLE_HOME/bin/oracle, import the *64 names.
 *   - glibc >= 2.33: programs call stat/lstat/fstat/fstatat and *64 directly.
 *   - statx (glibc >= 2.28): used by coreutils 8.30 stat(1), among others.
 * Symbols this glibc does not export resolve to NULL and fail with ENOSYS.
 * Raw syscall(2) or inline syscalls bypass LD_PRELOAD and cannot be wrapped.
 */

#define ORACLE_UID 54321

#define FIX_UID(buf) \
    do { if ((buf)->st_uid == ORACLE_UID) (buf)->st_uid = geteuid(); } while (0)

/* Resolve the next definition of NAME once; fail with ENOSYS if there is none */
#define REAL(name) \
    static __typeof__(&name) real_##name; \
    if (!real_##name) real_##name = (__typeof__(&name)) dlsym(RTLD_NEXT, #name); \
    if (!real_##name) { errno = ENOSYS; return -1; }

#define WRAP(name, buf, params, args) \
    int name params { \
        REAL(name) \
        int res = real_##name args; \
        if (res == 0) FIX_UID(buf); \
        return res; \
    }

WRAP(stat, buf, (const char *path, struct stat *buf), (path, buf))
WRAP(lstat, buf, (const char *path, struct stat *buf), (path, buf))
WRAP(fstat, buf, (int fd, struct stat *buf), (fd, buf))
WRAP(fstatat, buf, (int dirfd, const char *path, struct stat *buf, int flags), (dirfd, path, buf, flags))
WRAP(stat64, buf, (const char *path, struct stat64 *buf), (path, buf))
WRAP(lstat64, buf, (const char *path, struct stat64 *buf), (path, buf))
WRAP(fstat64, buf, (int fd, struct stat64 *buf), (fd, buf))
WRAP(fstatat64, buf, (int dirfd, const char *path, struct stat64 *buf, int flags), (dirfd, path, buf, flags))

WRAP(__xstat, buf, (int ver, const char *path, struct stat *buf), (ver, path, buf))
WRAP(__lxstat, buf, (int ver, const char *path, struct stat *buf), (ver, path, buf))
WRAP(__fxstat, buf, (int ver, int fd, struct stat *buf), (ver, fd, buf))
WRAP(__fxstatat, buf, (int ver, int dirfd, const char *path, struct stat *buf, int flags), (ver, dirfd, path, buf, flags))
WRAP(__xstat64, buf, (int ver, const char *path, struct stat64 *buf), (ver, path, buf))
WRAP(__lxstat64, buf, (int ver, const char *path, struct stat64 *buf), (ver, path, buf))
WRAP(__fxstat64, buf, (int ver, int fd, struct stat64 *buf), (ver, fd, buf))
WRAP(__fxstatat64, buf, (int ver, int dirfd, const char *path, struct stat64 *buf, int flags), (ver, dirfd, path, buf, flags))

int statx(int dirfd, const char *path, int flags, unsigned int mask, struct statx *buf) {
    REAL(statx)
    int res = real_statx(dirfd, path, flags, mask, buf);
    if (res == 0 && (buf->stx_mask & STATX_UID) && buf->stx_uid == ORACLE_UID) buf->stx_uid = geteuid();
    return res;
}
