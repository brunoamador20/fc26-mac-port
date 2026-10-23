/* nn::fs host implementation for the functions main imports. RomFS paths and handles go to the
   verified read-only backend (romfs.c); save, temporary and cache storage are host directories under
   the profile directory. Application save data is created on first start, as the system launcher does
   for titles that declare save data. Writes reach the host file immediately; Commit flushes them.
   Because of that, quitting in the middle of a save (the game writes several files, then commits) would leave a slot half
   written: runtime_fs_save_busy tells the window close to wait until the save is done (runtime/frontend.m). */
#include "autoload.h"
#include "runtime.h"
#include "fs_host.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>

#define R_PATH_NOT_FOUND 0x202u
#define R_ALREADY_EXISTS 0x402u
#define R_NOT_EMPTY 0x1002u
#define R_TARGET_NOT_FOUND 0x7d402u
#define R_INVALID_ARGUMENT 0x2ee202u
#define R_INVALID_PATH 0x2ee602u
#define R_OPEN_MODE 0x307402u
#define R_APPEND_REQUIRED 0x2f5e02u
#include "game_version.h"
#define TOTK_APPLICATION_ID GAME_TITLE_ID
enum { M_FREE, M_SAVE, M_TEMP, M_CACHE };
enum { OPEN_READ = 1, OPEN_WRITE = 2, OPEN_APPEND = 4 };
#define FILE_BASE 0x200000000ULL
#define DIR_BASE 0x300000000ULL
#define NFILES 1024
#define NDIRS 256

typedef struct { int kind; char name[32]; char root[1024]; } Mount;
typedef struct { int fd, mode, save; } File;   /* save: on a save-data mount (counts for runtime_fs_save_busy) */
/* A RomFS directory is a snapshot of its children taken at open (rom != NULL; dir stays NULL). */
struct RomEntry; typedef struct { DIR *dir; char path[1024]; int mode; struct RomEntry *rom; int64_t nrom, pos; } Dir;
static Mount mounts[16];
static File files[NFILES];
static Dir dirs[NDIRS];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static char profile[1024], save_root[1024];
static pthread_once_t once = PTHREAD_ONCE_INIT;

static void need(int c, const char *m) { if (!c) runtime_fail(m); }

/* Save in progress: a save-data file open for writing, or save data changed in the last 3 s and not committed yet (TOTK
   writes a slot's files back to back and then commits; between the files nothing is open for a moment). */
static _Atomic int save_writers, save_dirty;
static _Atomic uint64_t save_changed_ns;
static void save_touched(void) { atomic_store(&save_changed_ns, runtime_now_ns()); atomic_store(&save_dirty, 1); }
int runtime_fs_save_busy(void) {
    if (atomic_load(&save_writers) > 0) return 1;
    return atomic_load(&save_dirty) && runtime_now_ns() - atomic_load(&save_changed_ns) < 3000000000ull;
}
static void make_dir(const char *p) { if (mkdir(p, 0700) && errno != EEXIST) runtime_fail("create profile storage directory"); }
static int remove_tree(const char *path) {
    DIR *d = opendir(path); if (!d) return errno == ENOENT ? 0 : -1;
    struct dirent *e; int ok = 0; char child[2048];
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        snprintf(child, sizeof child, "%s/%s", path, e->d_name);
        ok |= e->d_type == DT_DIR ? remove_tree(child) : unlink(child);
    }
    closedir(d);
    return ok | rmdir(path);
}
static void init(void) {
    const char *dir = getenv("TOTK_PROFILE_DIR"); if (!dir) dir = "user-data";
    need(snprintf(profile, sizeof profile, "%s", dir) < (int)sizeof profile, "profile path");
    uint64_t uid[2]; runtime_account_uid(uid);
    char p[1100]; make_dir(profile);
    snprintf(p, sizeof p, "%s/save", profile); make_dir(p);
    need(snprintf(save_root, sizeof save_root, "%s/save/%016llx%016llx", profile, (unsigned long long)uid[1], (unsigned long long)uid[0]) < (int)sizeof save_root, "save path");
    make_dir(save_root);                                   /* launcher-style EnsureSaveData */
    snprintf(p, sizeof p, "%s/temp", profile); remove_tree(p); make_dir(p);
    snprintf(p, sizeof p, "%s/cache", profile); make_dir(p);
    snprintf(p, sizeof p, "%s/cache/0", profile); make_dir(p);
    fprintf(stderr, "[totk] host save storage: %s\n", save_root);
}
static void ready(void) { pthread_once(&once, init); }

/* ---------- mounts and paths ---------- */
static unsigned mount_add(const char *name, int kind, const char *root) {
    if (!name || !*name || strlen(name) >= 32 || strchr(name, ':') || strchr(name, '/')) return R_INVALID_ARGUMENT;
    pthread_mutex_lock(&lock);
    int slot = -1;
    for (int i = 0; i < 16; i++) { if (mounts[i].kind && !strcmp(mounts[i].name, name)) { pthread_mutex_unlock(&lock); return R_ALREADY_EXISTS; } if (!mounts[i].kind && slot < 0) slot = i; }
    if (slot < 0) runtime_fail("fs mount table full");
    mounts[slot].kind = kind; strcpy(mounts[slot].name, name); snprintf(mounts[slot].root, sizeof mounts[slot].root, "%s", root);
    pthread_mutex_unlock(&lock);
    fprintf(stderr, "[totk] fs mount %s: -> %s\n", name, root);
    return 0;
}
static int component_ok(const char *c, size_t n) { return n && !(n == 1 && c[0] == '.') && !(n == 2 && c[0] == '.' && c[1] == '.'); }
/* "name:/a/b" -> host path; 0 on success; *kind = the mount's kind (M_SAVE ...) when kind is given */
static unsigned host_path_kind(const char *path, char *out, size_t cap, int *kind) {
    if (!path) return R_INVALID_PATH;
    const char *colon = strchr(path, ':');
    if (!colon || colon[1] != '/') return R_INVALID_PATH;
    size_t n = (size_t)(colon - path);
    pthread_mutex_lock(&lock);
    const Mount *m = NULL;
    for (int i = 0; i < 16; i++) if (mounts[i].kind && strlen(mounts[i].name) == n && !strncmp(mounts[i].name, path, n)) m = &mounts[i];
    char root[1024]; if (m) strcpy(root, m->root);
    int k = m ? m->kind : M_FREE;
    pthread_mutex_unlock(&lock);
    if (!m) return R_PATH_NOT_FOUND;
    if (kind) *kind = k;
    const char *rest = colon + 1;
    for (const char *q = rest + 1; *q;) { const char *e = strchr(q, '/'); size_t len = e ? (size_t)(e - q) : strlen(q); if (!e && !len) break; if (!component_ok(q, len) || memchr(q, '\\', len)) return R_INVALID_PATH; q = e ? e + 1 : q + len; }
    if (snprintf(out, cap, "%s%s", root, rest) >= (int)cap) return R_INVALID_PATH;
    size_t L = strlen(out); while (L > strlen(root) && out[L - 1] == '/') out[--L] = 0;
    return 0;
}
static unsigned host_path(const char *path, char *out, size_t cap) { return host_path_kind(path, out, cap, NULL); }
/* A change to save data through a path (create, delete, rename, directories): marks the save as in progress. */
static unsigned save_change_path(const char *path, char *out, size_t cap) {
    int kind = M_FREE; unsigned r = host_path_kind(path, out, cap, &kind);
    if (!r && kind == M_SAVE) save_touched();
    return r;
}
static unsigned errno_result(void) { return errno == ENOENT || errno == ENOTDIR ? R_PATH_NOT_FOUND : errno == EEXIST ? R_ALREADY_EXISTS : errno == ENOTEMPTY ? R_NOT_EMPTY : R_INVALID_ARGUMENT; }

/* ---------- storage mounts ---------- */
static unsigned mount_save(const char *name, const uint64_t *uid) {
    ready(); uint64_t me[2]; runtime_account_uid(me);
    if (!uid || uid[0] != me[0] || uid[1] != me[1]) return R_TARGET_NOT_FOUND;
    return mount_add(name, M_SAVE, save_root);
}
static unsigned char save_exists(uint64_t application, const uint64_t *uid) {
    ready(); uint64_t me[2]; runtime_account_uid(me);
    return application == TOTK_APPLICATION_ID && uid && uid[0] == me[0] && uid[1] == me[1];
}
/* Other titles' save data (e.g. data-link bonuses) is not present on this host. */
static unsigned mount_save_ro(const char *name, uint64_t application, const uint64_t *uid) {
    if (!save_exists(application, uid)) return R_TARGET_NOT_FOUND;
    return mount_add(name, M_SAVE, save_root);
}
static unsigned mount_temp(const char *name) { ready(); char p[1100]; snprintf(p, sizeof p, "%s/temp", profile); return mount_add(name, M_TEMP, p); }
static void cache_dir(int index, char *out, size_t cap) { snprintf(out, cap, "%s/cache/%d", profile, index); }
static unsigned create_cache(int index, int64_t size, int64_t journal) {
    ready(); if (index < 0 || size < 0 || journal < 0) return R_INVALID_ARGUMENT;
    char p[1100]; cache_dir(index, p, sizeof p);
    if (mkdir(p, 0700)) return errno == EEXIST ? R_ALREADY_EXISTS : errno_result();
    return 0;
}
static unsigned delete_cache(int index) { ready(); char p[1100]; cache_dir(index, p, sizeof p); return remove_tree(p) ? R_TARGET_NOT_FOUND : 0; }
static unsigned mount_cache(const char *name, int index) {
    ready(); char p[1100]; cache_dir(index, p, sizeof p); struct stat st;
    if (stat(p, &st) || !S_ISDIR(st.st_mode)) return R_TARGET_NOT_FOUND;
    return mount_add(name, M_CACHE, p);
}
static unsigned mount_cache_storage(const char *name) { return mount_cache(name, 0); }
typedef struct { int32_t index; uint8_t reserved[0x1c]; } CacheStorageInfo;
typedef struct { int list[64]; int count, next; } CacheList;
static unsigned open_cache_list(uint64_t *out) {
    ready(); if (!out) return R_INVALID_ARGUMENT;
    CacheList *l = calloc(1, sizeof *l); need(l != NULL, "cache list allocation");
    char p[1100]; snprintf(p, sizeof p, "%s/cache", profile); DIR *d = opendir(p); struct dirent *e;
    while (d && (e = readdir(d)) && l->count < 64) { char *end; long v = strtol(e->d_name, &end, 10); if (*e->d_name && !*end && v >= 0) l->list[l->count++] = (int)v; }
    if (d) closedir(d);
    *out = (uint64_t)(uintptr_t)l; return 0;
}
static unsigned read_cache_list(int *count, CacheStorageInfo *out, uint64_t h, int max) {
    CacheList *l = (CacheList *)(uintptr_t)h; if (!l || !count || max < 0 || (!out && max)) return R_INVALID_ARGUMENT;
    int n = 0; while (n < max && l->next < l->count) { memset(&out[n], 0, sizeof *out); out[n++].index = l->list[l->next++]; }
    *count = n; return 0;
}
static void close_cache_list(uint64_t h) { free((void *)(uintptr_t)h); }
static void unmount(const char *name) {
    pthread_mutex_lock(&lock);
    for (int i = 0; i < 16; i++) if (mounts[i].kind && !strcmp(mounts[i].name, name)) { mounts[i].kind = M_FREE; pthread_mutex_unlock(&lock); return; }
    pthread_mutex_unlock(&lock);
    if (!runtime_romfs_owns(name)) runtime_fail("unmount of unknown fs mount");
}
/* EnsureSaveData(uid) (met first with an SDK 13.3.2 game): the profile's save folder is made when storage starts; only the local account owns one. */
static unsigned ensure_save(const uint64_t *uid) {
    ready(); uint64_t me[2]; runtime_account_uid(me);
    if (!uid || uid[0] != me[0] || uid[1] != me[1]) runtime_fail("EnsureSaveData for an unknown account");
    return 0;
}
static unsigned commit(const char *name) {
    pthread_mutex_lock(&lock); int found = 0, save = 0;
    for (int i = 0; i < 16; i++) if (mounts[i].kind && !strcmp(mounts[i].name, name)) { found = 1; save = mounts[i].kind == M_SAVE; }
    pthread_mutex_unlock(&lock);
    if (!found) return R_PATH_NOT_FOUND;
    for (int i = 0; i < NFILES; i++) { pthread_mutex_lock(&lock); int fd = files[i].fd; pthread_mutex_unlock(&lock); if (fd > 0) fcntl(fd, F_FULLFSYNC); }
    if (save && !(getenv("TOTK_PROBE_NEGATIVE") && atoi(getenv("TOTK_PROBE_NEGATIVE")) == 23)) atomic_store(&save_dirty, 0);   /* 23: probe-save's negative control */
    return 0;
}
static unsigned char is_mounted(const char *name) {
    if (!name) return 0;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < 16; i++) {
        if (mounts[i].kind && !strcmp(mounts[i].name, name)) {
            pthread_mutex_unlock(&lock);
            return 1;
        }
    }
    pthread_mutex_unlock(&lock);
    return runtime_romfs_is_mounted(name) ? 1 : 0;
}

/* Save data sizes for FC 26 proven from control.nacp (initial 62 MiB / 16 MiB journal, max 962 MiB / 32 MiB journal) */
#define SAVE_DATA_SIZE_INIT 65011712LL
#define SAVE_JOURNAL_SIZE_INIT 16777216LL
#define SAVE_DATA_SIZE_MAX 1008730112LL
#define SAVE_JOURNAL_SIZE_MAX 33554432LL

static int64_t current_save_data_size = SAVE_DATA_SIZE_INIT;
static int64_t current_save_journal_size = SAVE_JOURNAL_SIZE_INIT;

static unsigned get_save_data_size_max(int64_t *out_data, int64_t *out_journal) {
    if (!out_data || !out_journal) return R_INVALID_ARGUMENT;
    *out_data = SAVE_DATA_SIZE_MAX;
    *out_journal = SAVE_JOURNAL_SIZE_MAX;
    return 0;
}

static unsigned get_save_data_size(int64_t *out_data, int64_t *out_journal, const uint64_t *uid) {
    ready(); uint64_t me[2]; runtime_account_uid(me);
    if (!out_data || !out_journal || !uid) return R_INVALID_ARGUMENT;
    if (uid[0] != me[0] || uid[1] != me[1]) return R_TARGET_NOT_FOUND;
    pthread_mutex_lock(&lock);
    *out_data = current_save_data_size;
    *out_journal = current_save_journal_size;
    pthread_mutex_unlock(&lock);
    return 0;
}

static unsigned extend_save_data(const uint64_t *uid, int64_t data_size, int64_t journal_size) {
    ready(); uint64_t me[2]; runtime_account_uid(me);
    if (!uid || uid[0] != me[0] || uid[1] != me[1]) return R_TARGET_NOT_FOUND;
    if (data_size < 0 || journal_size < 0 || data_size > SAVE_DATA_SIZE_MAX || journal_size > SAVE_JOURNAL_SIZE_MAX) return R_INVALID_ARGUMENT;
    pthread_mutex_lock(&lock);
    if (data_size > current_save_data_size) current_save_data_size = data_size;
    if (journal_size > current_save_journal_size) current_save_journal_size = journal_size;
    pthread_mutex_unlock(&lock);
    return 0;
}

/* Cache storage sizes for FC 26 from control.nacp (data 962 MiB, journal 32 MiB, index max 0)
   TODO(mac): verify dynamic cache quota if game requests extra cache storage at runtime */
#define CACHE_STORAGE_SIZE 1008730112LL
#define CACHE_STORAGE_JOURNAL_SIZE 33554432LL
#define CACHE_STORAGE_MAX_INDEX 0
#define CACHE_STORAGE_MAX_SIZE (CACHE_STORAGE_SIZE + CACHE_STORAGE_JOURNAL_SIZE)

static unsigned get_cache_storage_max(int *out_max_index, int64_t *out_max_size) {
    if (!out_max_index || !out_max_size) return R_INVALID_ARGUMENT;
    /* TODO(mac): cache storage limits from control.nacp */
    *out_max_index = CACHE_STORAGE_MAX_INDEX;
    *out_max_size = CACHE_STORAGE_MAX_SIZE;
    return 0;
}

static unsigned get_cache_storage_size(int64_t *out_data, int64_t *out_journal, int index) {
    if (!out_data || !out_journal) return R_INVALID_ARGUMENT;
    *out_data = 0;
    *out_journal = 0;
    if (index < 0 || index > CACHE_STORAGE_MAX_INDEX) return R_TARGET_NOT_FOUND;
    /* TODO(mac): cache storage size from control.nacp */
    *out_data = CACHE_STORAGE_SIZE;
    *out_journal = CACHE_STORAGE_JOURNAL_SIZE;
    return 0;
}

/* Add-On Content (DLC): base game has no DLC (nn::aoc count 0); real nn::fs not-found results */
static unsigned mount_aoc(const char *name, int target_index, void *cache_buffer, size_t cache_buffer_size) {
    (void)cache_buffer; (void)cache_buffer_size; (void)target_index;
    if (!name || !*name || strlen(name) >= 32 || strchr(name, ':') || strchr(name, '/')) return R_INVALID_ARGUMENT;
    return R_TARGET_NOT_FOUND;
}

static unsigned query_mount_aoc_cache_size(size_t *out, int target_index) {
    if (!out) return R_INVALID_ARGUMENT;
    *out = 0;
    (void)target_index;
    return R_TARGET_NOT_FOUND;
}

/* ---------- files ---------- */
static File *file_of(uint64_t h, int *fd, int *mode) {
    if (h < FILE_BASE || h >= FILE_BASE + NFILES) return NULL;
    pthread_mutex_lock(&lock); File *f = &files[h - FILE_BASE]; int v = f->fd; if (fd) *fd = f->fd; if (mode) *mode = f->mode; pthread_mutex_unlock(&lock);
    return v > 0 ? f : NULL;
}
void runtime_fs_log(const char *what, const char *path);
static unsigned open_file(uint64_t *out, const char *path, int mode) {
    if (path && !runtime_romfs_owns(path)) runtime_fs_log(mode & 2 ? "write" : "read", path);
    if (runtime_romfs_owns(path)) return runtime_romfs_open(out, path, mode);
    if (!out || !(mode & (OPEN_READ | OPEN_WRITE)) || (mode & ~7)) return R_INVALID_ARGUMENT;
    char p[1100]; int kind = M_FREE; unsigned r = host_path_kind(path, p, sizeof p, &kind); if (r) return r;
    struct stat st; if (stat(p, &st)) return R_PATH_NOT_FOUND; if (!S_ISREG(st.st_mode)) return R_PATH_NOT_FOUND;
    int save_writer = kind == M_SAVE && (mode & OPEN_WRITE);
    int fd = open(p, (mode & OPEN_WRITE ? (mode & OPEN_READ ? O_RDWR : O_WRONLY) : O_RDONLY) | O_NOFOLLOW);
    if (fd < 0) return errno_result();
    runtime_autoload_save_file_opened(path);   /* TOTK_AUTOLOAD: a slot's caption.sav starts the presses, its progress.sav ends them */
    pthread_mutex_lock(&lock);
    for (int i = 0; i < NFILES; i++) if (files[i].fd <= 0) {
        files[i] = (File){fd, mode, save_writer}; *out = FILE_BASE + (uint64_t)i; pthread_mutex_unlock(&lock);
        if (save_writer) { atomic_fetch_add(&save_writers, 1); save_touched(); }
        return 0;
    }
    pthread_mutex_unlock(&lock); runtime_fail("host file handle table full");
}
static unsigned read_file(uint64_t *out, uint64_t h, int64_t offset, void *buffer, uint64_t size) {
    if (runtime_romfs_handle(h)) return runtime_romfs_read(out, h, offset, buffer, size);
    int fd, mode; if (!out || offset < 0 || (!buffer && size) || !file_of(h, &fd, &mode)) return R_INVALID_ARGUMENT;
    if (!(mode & OPEN_READ)) return R_OPEN_MODE;
    dm_guest_write_prepare(buffer, (size_t)size);
    uint64_t done = 0;
    while (done < size) { ssize_t n = pread(fd, (uint8_t *)buffer + done, (size_t)(size - done), offset + (off_t)done); if (n < 0) runtime_fail("host save read failure"); if (!n) break; done += (uint64_t)n; }
    *out = done; return 0;
}
static unsigned read_options(uint64_t *out, uint64_t h, int64_t off, void *buf, uint64_t size, const void *options) { (void)options; return read_file(out, h, off, buf, size); }
static unsigned read_exact(uint64_t h, int64_t off, void *buf, uint64_t size) { uint64_t n = 0; unsigned r = read_file(&n, h, off, buf, size); return r ? r : n == size ? 0 : R_INVALID_ARGUMENT; }
static unsigned write_file(uint64_t h, int64_t offset, const void *buffer, uint64_t size, const int32_t *option) {
    int fd, mode; File *f = offset < 0 || (!buffer && size) ? NULL : file_of(h, &fd, &mode); if (!f) return R_INVALID_ARGUMENT;
    if (!(mode & OPEN_WRITE)) return R_OPEN_MODE;
    struct stat st; if (fstat(fd, &st)) runtime_fail("host save stat");
    if ((uint64_t)offset + size > (uint64_t)st.st_size && !(mode & OPEN_APPEND)) return R_APPEND_REQUIRED;
    uint64_t done = 0;
    if (f->save) {
        save_touched();
        static int delay_ms = -1; if (delay_ms < 0) { const char *e = getenv("TOTK_SAVE_WRITE_DELAY_MS"); delay_ms = e ? atoi(e) : 0; }
        if (delay_ms > 0) usleep((useconds_t)delay_ms * 1000);   /* tests only: slow saves down so a window close lands in the middle of one */
    }
    while (done < size) { ssize_t n = pwrite(fd, (const uint8_t *)buffer + done, (size_t)(size - done), offset + (off_t)done); if (n <= 0) runtime_fail("host save write failure"); done += (uint64_t)n; }
    if (option && (*option & 1)) fcntl(fd, F_FULLFSYNC);
    return 0;
}
static unsigned file_size(int64_t *out, uint64_t h) {
    if (runtime_romfs_handle(h)) return runtime_romfs_size(out, h);
    int fd; struct stat st; if (!out || !file_of(h, &fd, NULL) || fstat(fd, &st)) return R_INVALID_ARGUMENT;
    *out = st.st_size; return 0;
}
static unsigned set_file_size(uint64_t h, int64_t size) {
    int fd, mode; if (size < 0 || !file_of(h, &fd, &mode)) return R_INVALID_ARGUMENT;
    if (!(mode & OPEN_WRITE)) return R_OPEN_MODE;
    if (files[h - FILE_BASE].save) save_touched();
    return ftruncate(fd, size) ? errno_result() : 0;
}
static unsigned flush_file(uint64_t h) { int fd; if (!file_of(h, &fd, NULL)) return R_INVALID_ARGUMENT; fcntl(fd, F_FULLFSYNC); return 0; }
static void close_file(uint64_t h) {
    if (runtime_romfs_handle(h)) { runtime_romfs_close(h); return; }
    if (!file_of(h, NULL, NULL)) runtime_fail("close invalid file handle");
    pthread_mutex_lock(&lock); int fd = files[h - FILE_BASE].fd, save = files[h - FILE_BASE].save; files[h - FILE_BASE].fd = 0; pthread_mutex_unlock(&lock);
    close(fd);
    if (save) { save_touched(); atomic_fetch_sub(&save_writers, 1); }
}
static unsigned create_file(const char *path, int64_t size) {
    char p[1100]; unsigned r = save_change_path(path, p, sizeof p); if (r) return r; if (size < 0) return R_INVALID_ARGUMENT;
    int fd = open(p, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600); if (fd < 0) return errno_result();
    int bad = ftruncate(fd, size); close(fd); return bad ? errno_result() : 0;
}
static unsigned delete_file(const char *path) { char p[1100]; unsigned r = save_change_path(path, p, sizeof p); if (r) return r; return unlink(p) ? errno_result() : 0; }
static unsigned rename_file(const char *from, const char *to) {
    char a[1100], b[1100]; unsigned r = save_change_path(from, a, sizeof a); if (!r) r = host_path(to, b, sizeof b); if (r) return r;
    struct stat st; if (!stat(b, &st)) return R_ALREADY_EXISTS;
    return rename(a, b) ? errno_result() : 0;
}
static unsigned entry_type(int *out, const char *path) {
    if (runtime_romfs_owns(path)) return runtime_romfs_entry_type(out, path);
    char p[1100]; unsigned r = host_path(path, p, sizeof p); if (r) return r; struct stat st;
    if (!out) return R_INVALID_ARGUMENT; if (stat(p, &st)) return R_PATH_NOT_FOUND;
    *out = S_ISDIR(st.st_mode) ? 0 : 1; return 0;
}

/* ---------- directories ---------- */
typedef struct { char name[769]; uint8_t pad0[3]; int8_t type; uint8_t pad1[3]; int64_t size; } DirectoryEntry;
_Static_assert(sizeof(DirectoryEntry) == 0x310, "nn::fs::DirectoryEntry");
static unsigned create_directory(const char *path) { char p[1100]; unsigned r = save_change_path(path, p, sizeof p); if (r) return r; return mkdir(p, 0700) ? errno_result() : 0; }
static unsigned delete_directory(const char *path) {
    if (!path) return R_INVALID_PATH;
    const char *colon = strchr(path, ':');
    if (!colon || !colon[1] || !strcmp(colon, ":/")) return R_INVALID_PATH;
    char p[1100]; unsigned r = save_change_path(path, p, sizeof p); if (r) return r;
    struct stat st; if (stat(p, &st)) return R_PATH_NOT_FOUND;
    if (!S_ISDIR(st.st_mode)) return R_PATH_NOT_FOUND;
    if (rmdir(p)) return errno == ENOTEMPTY || errno == EEXIST ? R_NOT_EMPTY : errno_result();
    return 0;
}
static unsigned delete_recursive(const char *path) { char p[1100]; unsigned r = save_change_path(path, p, sizeof p); if (r) return r; struct stat st; if (stat(p, &st)) return R_PATH_NOT_FOUND; return remove_tree(p) ? R_INVALID_ARGUMENT : 0; }
static unsigned rename_directory(const char *from, const char *to) {
    if (!from || !to) return R_INVALID_PATH;
    const char *c1 = strchr(from, ':');
    const char *c2 = strchr(to, ':');
    if (!c1 || !c2 || (c1 - from) != (c2 - to) || strncmp(from, to, (size_t)(c1 - from)) != 0) return R_INVALID_ARGUMENT;
    char a[1100], b[1100];
    unsigned r = save_change_path(from, a, sizeof a);
    if (!r) r = host_path(to, b, sizeof b);
    if (r) return r;
    struct stat st;
    if (stat(a, &st)) return R_PATH_NOT_FOUND;
    if (!S_ISDIR(st.st_mode)) return R_PATH_NOT_FOUND;
    if (!stat(b, &st)) return R_ALREADY_EXISTS;
    return rename(a, b) ? errno_result() : 0;
}
static unsigned get_free_space_size(int64_t *out, const char *path) {
    if (!out) return R_INVALID_ARGUMENT;
    *out = 0;
    if (!path) return R_INVALID_PATH;
    char p[1100];
    char temp_path[1100];
    const char *use_path = path;
    const char *colon = strchr(path, ':');
    if (colon && colon[1] == '\0') {
        snprintf(temp_path, sizeof temp_path, "%s/", path);
        use_path = temp_path;
        colon = strchr(use_path, ':');
    }
    unsigned r = host_path(use_path, p, sizeof p);
    if (r) return r;
    struct statvfs st;
    if (statvfs(p, &st)) {
        pthread_mutex_lock(&lock);
        char root[1024] = {0};
        size_t n = colon ? (size_t)(colon - use_path) : 0;
        for (int i = 0; i < 16; i++) {
            if (mounts[i].kind && strlen(mounts[i].name) == n && !strncmp(mounts[i].name, use_path, n)) {
                strcpy(root, mounts[i].root);
                break;
            }
        }
        pthread_mutex_unlock(&lock);
        if (!*root || statvfs(root, &st)) return errno_result();
    }
    uint64_t bsize = st.f_frsize ? st.f_frsize : st.f_bsize;
    *out = (int64_t)(st.f_bavail * bsize);
    return 0;
}
struct RomEntry { char name[769]; int is_dir; int64_t size; };
typedef struct { struct RomEntry *list; int64_t n, cap; } RomList;
static void rom_add(void *ctx, const char *name, int is_dir, int64_t size) {
    RomList *l = ctx;
    if (l->n == l->cap) { l->cap = l->cap ? l->cap * 2 : 64; l->list = realloc(l->list, (size_t)l->cap * sizeof *l->list); need(l->list != NULL, "RomFS directory listing"); }
    struct RomEntry *e = &l->list[l->n++]; snprintf(e->name, sizeof e->name, "%s", name); e->is_dir = is_dir; e->size = size;
}
static unsigned open_rom_directory(uint64_t *out, const char *path, int mode) {
    if (!out || mode < 1 || mode > 3) return R_INVALID_ARGUMENT;
    RomList l = {0}; unsigned r = runtime_romfs_list(path, mode, rom_add, &l);
    if (r) { fprintf(stderr, "[totk] RomFS directory %s: result %#x\n", path, r); free(l.list); return r; }
    fprintf(stderr, "[totk] RomFS directory %s: %lld entries\n", path, (long long)l.n);
    pthread_mutex_lock(&lock);
    for (int i = 0; i < NDIRS; i++) if (!dirs[i].dir && !dirs[i].rom) {
        dirs[i] = (Dir){.mode = mode, .rom = l.list ? l.list : calloc(1, sizeof *l.list), .nrom = l.n};
        snprintf(dirs[i].path, sizeof dirs[i].path, "%s", path); *out = DIR_BASE + (uint64_t)i; pthread_mutex_unlock(&lock); return 0;
    }
    pthread_mutex_unlock(&lock); runtime_fail("host directory handle table full");
}
static unsigned open_directory(uint64_t *out, const char *path, int mode) {
    if (getenv("TOTK_FS_LOG")) fprintf(stderr, "[totk-fs] OpenDirectory %s mode %d\n", path ? path : "(null)", mode);
    if (runtime_romfs_owns(path)) return open_rom_directory(out, path, mode);
    char p[1100]; unsigned r = host_path(path, p, sizeof p); if (r) return r; if (!out || mode < 1 || mode > 3) return R_INVALID_ARGUMENT;
    DIR *d = opendir(p); if (!d) return errno_result();
    pthread_mutex_lock(&lock);
    for (int i = 0; i < NDIRS; i++) if (!dirs[i].dir && !dirs[i].rom) { dirs[i].dir = d; dirs[i].mode = mode; strcpy(dirs[i].path, p); *out = DIR_BASE + (uint64_t)i; pthread_mutex_unlock(&lock); return 0; }
    pthread_mutex_unlock(&lock); runtime_fail("host directory handle table full");
}
static unsigned read_directory(int64_t *count, DirectoryEntry *out, uint64_t h, int64_t max) {
    if (h < DIR_BASE || h >= DIR_BASE + NDIRS || !count || max < 0 || (!out && max)) return R_INVALID_ARGUMENT;
    Dir *d = &dirs[h - DIR_BASE]; if (!d->dir && !d->rom) return R_INVALID_ARGUMENT;
    int64_t n = 0; struct dirent *e;
    if (d->rom) {
        for (; n < max && d->pos < d->nrom; n++, d->pos++) {
            const struct RomEntry *r = &d->rom[d->pos];
            memset(&out[n], 0, sizeof *out); strcpy(out[n].name, r->name); out[n].type = r->is_dir ? 0 : 1; out[n].size = r->size;
        }
        *count = n; return 0;
    }
    while (n < max && (e = readdir(d->dir))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..") || strlen(e->d_name) > 768) continue;
        char child[2048]; snprintf(child, sizeof child, "%s/%s", d->path, e->d_name); struct stat st; if (stat(child, &st)) continue;
        int is_dir = S_ISDIR(st.st_mode); if (!(d->mode & (is_dir ? 1 : 2))) continue;
        memset(&out[n], 0, sizeof *out); strcpy(out[n].name, e->d_name); out[n].type = is_dir ? 0 : 1; out[n].size = is_dir ? 0 : st.st_size; n++;
    }
    *count = n; return 0;
}
static unsigned directory_entry_count(int64_t *out, uint64_t h) {
    if (!out) return R_INVALID_ARGUMENT;
    *out = 0;
    if (h < DIR_BASE || h >= DIR_BASE + NDIRS) return R_INVALID_ARGUMENT;
    pthread_mutex_lock(&lock);
    Dir *d = &dirs[h - DIR_BASE];
    if (!d->dir && !d->rom) { pthread_mutex_unlock(&lock); return R_INVALID_ARGUMENT; }
    if (d->rom) {
        *out = d->nrom;
        pthread_mutex_unlock(&lock);
        return 0;
    }
    char path[1024];
    int mode = d->mode;
    strcpy(path, d->path);
    pthread_mutex_unlock(&lock);

    DIR *dp = opendir(path);
    if (!dp) return errno_result();
    int64_t count = 0;
    struct dirent *e;
    while ((e = readdir(dp))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..") || strlen(e->d_name) > 768) continue;
        char child[2048]; snprintf(child, sizeof child, "%s/%s", path, e->d_name); struct stat st; if (stat(child, &st)) continue;
        int is_dir = S_ISDIR(st.st_mode); if (!(mode & (is_dir ? 1 : 2))) continue;
        count++;
    }
    closedir(dp);
    *out = count;
    return 0;
}
static void close_directory(uint64_t h) {
    if (h < DIR_BASE || h >= DIR_BASE + NDIRS || (!dirs[h - DIR_BASE].dir && !dirs[h - DIR_BASE].rom)) runtime_fail("close invalid directory handle");
    pthread_mutex_lock(&lock); Dir *d = &dirs[h - DIR_BASE];
    if (d->rom) { free(d->rom); d->rom = NULL; } else { closedir(d->dir); d->dir = NULL; }
    pthread_mutex_unlock(&lock);
}
/* The fs priority only orders I/O inside the system fs process; host I/O is unordered. */
static void set_priority(int priority) { (void)priority; }

/* make probe-save: the "save in progress" state the window close waits on, through the fs entry points the game uses
   (a fresh profile in build/probe-save-profile; no game). */
void runtime_save_probe(void) {
    const char *dir = "build/probe-save-profile";   /* a fresh profile each run (a failed run leaves it for a look) */
    remove_tree(dir); setenv("TOTK_PROFILE_DIR", dir, 1);
    unsigned checks = 0; uint64_t uid[2]; runtime_account_uid(uid); uint64_t h = 0;
#define CHECK(c, what) do { checks++; if (!(c)) { fprintf(stderr, "save probe: %s\n", what); runtime_fail("save probe failed"); } } while (0)
    CHECK(mount_save("save", uid) == 0 && mount_temp("temp") == 0, "mount save and temporary storage");
    CHECK(!runtime_fs_save_busy(), "idle at start");
    CHECK(create_file("save:/a.sav", 16) == 0 && runtime_fs_save_busy(), "creating a save file starts a save");
    CHECK(commit("save") == 0 && !runtime_fs_save_busy(), "commit ends it");
    CHECK(open_file(&h, "save:/a.sav", OPEN_WRITE) == 0 && runtime_fs_save_busy(), "a save file open for writing");
    static const char data[16] = "progress";
    CHECK(write_file(h, 0, data, sizeof data, NULL) == 0 && runtime_fs_save_busy(), "writing");
    atomic_store(&save_changed_ns, runtime_now_ns() - 10000000000ull);
    CHECK(runtime_fs_save_busy(), "a file open for writing is busy however long ago it was written");
    close_file(h);
    CHECK(runtime_fs_save_busy(), "closed but not committed yet (the next file of the save follows)");
    CHECK(commit("save") == 0 && !runtime_fs_save_busy(), "committed");
    CHECK(open_file(&h, "save:/a.sav", OPEN_READ) == 0 && !runtime_fs_save_busy(), "reading is not saving");
    close_file(h);
    CHECK(create_file("save:/b.sav", 4) == 0 && runtime_fs_save_busy(), "second change");
    atomic_store(&save_changed_ns, runtime_now_ns() - 4000000000ull);
    CHECK(!runtime_fs_save_busy(), "uncommitted changes older than 3 s are not a save in progress");
    CHECK(create_file("temp:/t.bin", 4) == 0 && !runtime_fs_save_busy(), "temporary storage does not count");
    CHECK(rename_file("save:/b.sav", "save:/c.sav") == 0 && runtime_fs_save_busy(), "renaming save data");
    CHECK(commit("save") == 0 && !runtime_fs_save_busy() && delete_file("save:/c.sav") == 0 && runtime_fs_save_busy() && commit("save") == 0, "delete and commit");
#undef CHECK
    remove_tree(dir);
    printf("{\"status\":\"pass\",\"probe\":\"probe-save\",\"checks\":%u,\"scope\":\"save-in-progress state (runtime_fs_save_busy) through open / write / close / create / rename / delete / commit on a save mount; reads and temporary storage do not count; stale uncommitted changes do not hold a close\"}\n", checks);
}

/* ---------- libc file operations overrides ---------- */
struct guest_stat {
    uint64_t st_dev;
    uint64_t st_ino;
    uint32_t st_mode;
    uint32_t st_nlink;
    uint32_t st_uid;
    uint32_t st_gid;
    uint64_t st_rdev;
    uint64_t __pad;
    int64_t  st_size;
    int32_t  st_blksize;
    int32_t  __pad2;
    int64_t  st_blocks;
    int64_t  st_atime_sec;
    int64_t  st_atime_nsec;
    int64_t  st_mtime_sec;
    int64_t  st_mtime_nsec;
    int64_t  st_ctime_sec;
    int64_t  st_ctime_nsec;
    uint32_t unused[2];
};
_Static_assert(sizeof(struct guest_stat) == 128, "guest_stat size");
_Static_assert(offsetof(struct guest_stat, st_mode) == 16, "guest_stat st_mode offset");
_Static_assert(offsetof(struct guest_stat, st_size) == 48, "guest_stat st_size offset");

#define GUEST_FD_BASE 0x10000
#define GUEST_MAX_FD  256

typedef struct {
    int in_use;
    int is_rom;
    uint64_t rom_handle;
    int64_t rom_offset;
    int64_t rom_size;
    int host_fd;
    int is_save;
} GuestFdEntry;

static GuestFdEntry s_guest_fds[GUEST_MAX_FD];
static pthread_mutex_t s_guest_fd_lock = PTHREAD_MUTEX_INITIALIZER;

/* The game's errno: the sdk's __errno_location (sdk+0x556a40 -> sdk+0x59d1c0) is `mrs x8, tpidrro_el0; add x0, x8, #0x1d8`,
   and the rewriter turns the guest's tpidrro_el0 into thread slot KTLR (runtime_keys[2], the ThreadLocalRegion that
   loader.c gives each guest thread). The host's own tpidrro_el0 is Darwin's TSD and must not be written. */
static void guest_set_errno(int err) {
    errno = err;
    uint8_t *tlr = pthread_getspecific(runtime_keys[2]);
    if (tlr) memcpy(tlr + 0x1d8, &err, sizeof err);
}

/* Descriptors below GUEST_FD_BASE are not ours. 0/1/2 are the host's stdio (read/write/fstat/lseek go there; close
   leaves the runtime's stdio open); any other one belongs to the sdk's own libc and goes to its original function,
   or fails with EBADF when the sdk does not export it. Never the host's: a guest close(N) must not close a runtime fd. */
static void *sdk_libc(const char *name) {
    void *fn = runtime_symbol(name);
    if (!fn) guest_set_errno(EBADF);
    return fn;
}

static int alloc_guest_fd(int is_rom, uint64_t rom_handle, int64_t rom_size, int host_fd, int is_save) {
    pthread_mutex_lock(&s_guest_fd_lock);
    for (int i = 0; i < GUEST_MAX_FD; i++) {
        if (!s_guest_fds[i].in_use) {
            s_guest_fds[i].in_use = 1;
            s_guest_fds[i].is_rom = is_rom;
            s_guest_fds[i].rom_handle = rom_handle;
            s_guest_fds[i].rom_offset = 0;
            s_guest_fds[i].rom_size = rom_size;
            s_guest_fds[i].host_fd = host_fd;
            s_guest_fds[i].is_save = is_save;
            pthread_mutex_unlock(&s_guest_fd_lock);
            return GUEST_FD_BASE + i;
        }
    }
    pthread_mutex_unlock(&s_guest_fd_lock);
    guest_set_errno(EMFILE);
    return -1;
}

static GuestFdEntry *get_guest_fd(int fd) {
    if (fd < GUEST_FD_BASE || fd >= GUEST_FD_BASE + GUEST_MAX_FD) return NULL;
    GuestFdEntry *e = &s_guest_fds[fd - GUEST_FD_BASE];
    return e->in_use ? e : NULL;
}

#define GUEST_O_RDONLY    00
#define GUEST_O_WRONLY    01
#define GUEST_O_RDWR      02
#define GUEST_O_CREAT   0100
#define GUEST_O_EXCL    0200
#define GUEST_O_TRUNC  01000
#define GUEST_O_APPEND 02000

static int convert_guest_open_flags_to_host(int guest_flags) {
    int host_flags = 0;
    int acc = guest_flags & 3;
    if (acc == GUEST_O_RDONLY) host_flags |= O_RDONLY;
    else if (acc == GUEST_O_WRONLY) host_flags |= O_WRONLY;
    else if (acc == GUEST_O_RDWR) host_flags |= O_RDWR;

    if (guest_flags & GUEST_O_CREAT) host_flags |= O_CREAT;
    if (guest_flags & GUEST_O_EXCL) host_flags |= O_EXCL;
    if (guest_flags & GUEST_O_TRUNC) host_flags |= O_TRUNC;
    if (guest_flags & GUEST_O_APPEND) host_flags |= O_APPEND;
    host_flags |= O_CLOEXEC;
    return host_flags;
}

static void fill_guest_stat_from_host(struct guest_stat *st, const struct stat *hst) {
    memset(st, 0, sizeof(*st));
    st->st_dev = (uint64_t)hst->st_dev;
    st->st_ino = (uint64_t)hst->st_ino;
    st->st_mode = (uint32_t)hst->st_mode;
    st->st_nlink = (uint32_t)hst->st_nlink;
    st->st_uid = (uint32_t)hst->st_uid;
    st->st_gid = (uint32_t)hst->st_gid;
    st->st_rdev = (uint64_t)hst->st_rdev;
    st->st_size = (int64_t)hst->st_size;
    st->st_blksize = (int32_t)hst->st_blksize;
    st->st_blocks = (int64_t)hst->st_blocks;
    st->st_atime_sec = (int64_t)hst->st_atimespec.tv_sec;
    st->st_atime_nsec = (int64_t)hst->st_atimespec.tv_nsec;
    st->st_mtime_sec = (int64_t)hst->st_mtimespec.tv_sec;
    st->st_mtime_nsec = (int64_t)hst->st_mtimespec.tv_nsec;
    st->st_ctime_sec = (int64_t)hst->st_ctimespec.tv_sec;
    st->st_ctime_nsec = (int64_t)hst->st_ctimespec.tv_nsec;
}

static int host_libc_open(const char *path, int flags, ...) {
    if (!path) { guest_set_errno(EINVAL); return -1; }
    ready();

    if (runtime_romfs_owns(path)) {
        int acc = flags & 3;
        if (acc != GUEST_O_RDONLY || (flags & (GUEST_O_WRONLY | GUEST_O_RDWR | GUEST_O_CREAT | GUEST_O_TRUNC | GUEST_O_APPEND))) {
            guest_set_errno(EROFS);
            return -1;
        }
        uint64_t h = 0;
        unsigned r = runtime_romfs_open(&h, path, 1);
        if (r != 0) {
            guest_set_errno(ENOENT);
            return -1;
        }
        int64_t size = 0;
        runtime_romfs_size(&size, h);
        return alloc_guest_fd(1, h, size, -1, 0);
    }

    char host_p[1100];
    int kind = M_FREE;
    if (host_path_kind(path, host_p, sizeof host_p, &kind) == 0) {
        runtime_fs_log((flags & 3) != GUEST_O_RDONLY ? "libc-write" : "libc-read", path);
        mode_t mode = 0;
        if (flags & GUEST_O_CREAT) {
            va_list ap;
            va_start(ap, flags);
            mode = (mode_t)va_arg(ap, int);
            va_end(ap);
        }
        int hflags = convert_guest_open_flags_to_host(flags);
        int fd = open(host_p, hflags, mode);
        if (fd < 0) {
            guest_set_errno(errno);
            return -1;
        }
        int is_save = (kind == M_SAVE);
        if (is_save && ((flags & 3) != GUEST_O_RDONLY)) save_touched();
        return alloc_guest_fd(0, 0, 0, fd, is_save);
    }

    guest_set_errno(ENOENT);
    return -1;
}

static ssize_t host_libc_read(int fd, void *buf, size_t count) {
    if (fd < GUEST_FD_BASE) {
        if (fd > 2) { ssize_t (*fn)(int, void *, size_t) = sdk_libc("read"); return fn ? fn(fd, buf, count) : -1; }
        if (fd < 0) { guest_set_errno(EBADF); return -1; }
        dm_guest_write_prepare(buf, count);
        ssize_t ret = read(fd, buf, count);
        if (ret < 0) guest_set_errno(errno);
        return ret;
    }
    pthread_mutex_lock(&s_guest_fd_lock);
    GuestFdEntry *e = get_guest_fd(fd);
    if (!e) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EBADF);
        return -1;
    }
    if (e->is_rom) {
        if (!buf && count > 0) {
            pthread_mutex_unlock(&s_guest_fd_lock);
            guest_set_errno(EINVAL);
            return -1;
        }
        if (count == 0 || e->rom_offset >= e->rom_size) {
            pthread_mutex_unlock(&s_guest_fd_lock);
            return 0;
        }
        uint64_t to_read = count;
        if (e->rom_offset + (int64_t)to_read > e->rom_size)
            to_read = (uint64_t)(e->rom_size - e->rom_offset);
        uint64_t n_done = 0;
        uint64_t cur_off = (uint64_t)e->rom_offset;
        uint64_t h = e->rom_handle;
        pthread_mutex_unlock(&s_guest_fd_lock);

        dm_guest_write_prepare(buf, to_read);
        unsigned r = runtime_romfs_read(&n_done, h, (int64_t)cur_off, buf, to_read);
        if (r != 0) {
            guest_set_errno(EIO);
            return -1;
        }

        pthread_mutex_lock(&s_guest_fd_lock);
        e = get_guest_fd(fd);
        if (e && e->is_rom && e->rom_handle == h) {
            e->rom_offset += (int64_t)n_done;
        }
        pthread_mutex_unlock(&s_guest_fd_lock);
        return (ssize_t)n_done;
    } else {
        int hfd = e->host_fd;
        pthread_mutex_unlock(&s_guest_fd_lock);
        dm_guest_write_prepare(buf, count);
        ssize_t ret = read(hfd, buf, count);
        if (ret < 0) guest_set_errno(errno);
        return ret;
    }
}

static ssize_t host_libc_write(int fd, const void *buf, size_t count) {
    if (fd < GUEST_FD_BASE) {
        if (fd > 2) { ssize_t (*fn)(int, const void *, size_t) = sdk_libc("write"); return fn ? fn(fd, buf, count) : -1; }
        if (fd < 0) { guest_set_errno(EBADF); return -1; }
        ssize_t ret = write(fd, buf, count);
        if (ret < 0) guest_set_errno(errno);
        return ret;
    }
    pthread_mutex_lock(&s_guest_fd_lock);
    GuestFdEntry *e = get_guest_fd(fd);
    if (!e) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EBADF);
        return -1;
    }
    if (e->is_rom) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EROFS);
        return -1;
    }
    int hfd = e->host_fd;
    int is_save = e->is_save;
    pthread_mutex_unlock(&s_guest_fd_lock);

    ssize_t ret = write(hfd, buf, count);
    if (ret < 0) {
        guest_set_errno(errno);
        return -1;
    }
    if (is_save) save_touched();
    return ret;
}

static off_t host_libc_lseek(int fd, off_t offset, int whence) {
    if (fd < GUEST_FD_BASE) {
        if (fd > 2) { off_t (*fn)(int, off_t, int) = sdk_libc("lseek"); return fn ? fn(fd, offset, whence) : (off_t)-1; }
        if (fd < 0) { guest_set_errno(EBADF); return (off_t)-1; }
        off_t ret = lseek(fd, offset, whence);
        if (ret == (off_t)-1) guest_set_errno(errno);
        return ret;
    }
    pthread_mutex_lock(&s_guest_fd_lock);
    GuestFdEntry *e = get_guest_fd(fd);
    if (!e) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EBADF);
        return (off_t)-1;
    }
    if (e->is_rom) {
        int64_t base = 0;
        switch (whence) {
        case SEEK_SET: base = 0; break;
        case SEEK_CUR: base = e->rom_offset; break;
        case SEEK_END: base = e->rom_size; break;
        default:
            pthread_mutex_unlock(&s_guest_fd_lock);
            guest_set_errno(EINVAL);
            return (off_t)-1;
        }
        int64_t new_off = base + offset;
        if (new_off < 0) {
            pthread_mutex_unlock(&s_guest_fd_lock);
            guest_set_errno(EINVAL);
            return (off_t)-1;
        }
        e->rom_offset = new_off;
        pthread_mutex_unlock(&s_guest_fd_lock);
        return (off_t)new_off;
    } else {
        int hfd = e->host_fd;
        pthread_mutex_unlock(&s_guest_fd_lock);
        off_t ret = lseek(hfd, offset, whence);
        if (ret == (off_t)-1) guest_set_errno(errno);
        return ret;
    }
}

static int host_libc_close(int fd) {
    if (fd < GUEST_FD_BASE) {
        if (fd > 2) { int (*fn)(int) = sdk_libc("close"); return fn ? fn(fd) : -1; }
        if (fd < 0) { guest_set_errno(EBADF); return -1; }
        fprintf(stderr, "[totk-fs] guest close(%d): the runtime's stdio stays open\n", fd);
        return 0;
    }
    pthread_mutex_lock(&s_guest_fd_lock);
    GuestFdEntry *e = get_guest_fd(fd);
    if (!e) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EBADF);
        return -1;
    }
    int is_rom = e->is_rom;
    uint64_t h = e->rom_handle;
    int hfd = e->host_fd;
    int is_save = e->is_save;
    e->in_use = 0;
    pthread_mutex_unlock(&s_guest_fd_lock);

    if (is_rom) {
        runtime_romfs_close(h);
        return 0;
    } else {
        int ret = close(hfd);
        if (ret < 0) guest_set_errno(errno);
        if (is_save) save_touched();
        return ret;
    }
}

static int host_libc_fstat(int fd, struct guest_stat *st) {
    if (!st) { guest_set_errno(EFAULT); return -1; }
    if (fd < GUEST_FD_BASE && fd > 2) { int (*fn)(int, struct guest_stat *) = sdk_libc("fstat"); return fn ? fn(fd, st) : -1; }
    dm_guest_write_prepare(st, sizeof(*st));
    if (fd < GUEST_FD_BASE) {
        if (fd < 0) { guest_set_errno(EBADF); return -1; }
        struct stat hst;
        if (fstat(fd, &hst) != 0) {
            guest_set_errno(errno);
            return -1;
        }
        fill_guest_stat_from_host(st, &hst);
        return 0;
    }
    pthread_mutex_lock(&s_guest_fd_lock);
    GuestFdEntry *e = get_guest_fd(fd);
    if (!e) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EBADF);
        return -1;
    }
    if (e->is_rom) {
        int64_t size = e->rom_size;
        pthread_mutex_unlock(&s_guest_fd_lock);
        memset(st, 0, sizeof(*st));
        st->st_mode = 0100444; /* S_IFREG | 0444 */
        st->st_nlink = 1;
        st->st_size = size;
        st->st_blksize = 4096;
        st->st_blocks = (size + 511) / 512;
        return 0;
    } else {
        int hfd = e->host_fd;
        pthread_mutex_unlock(&s_guest_fd_lock);
        struct stat hst;
        if (fstat(hfd, &hst) != 0) {
            guest_set_errno(errno);
            return -1;
        }
        fill_guest_stat_from_host(st, &hst);
        return 0;
    }
}

static int host_libc_stat(const char *path, struct guest_stat *st) {
    if (!path || !st) { guest_set_errno(EINVAL); return -1; }
    dm_guest_write_prepare(st, sizeof(*st));
    ready();
    if (runtime_romfs_owns(path)) {
        int type = -1;
        unsigned r = runtime_romfs_entry_type(&type, path);
        if (r != 0) {
            guest_set_errno(ENOENT);
            return -1;
        }
        if (type == 1) {
            uint64_t h = 0;
            if (runtime_romfs_open(&h, path, 1) != 0) {
                guest_set_errno(ENOENT);
                return -1;
            }
            int64_t size = 0;
            runtime_romfs_size(&size, h);
            runtime_romfs_close(h);
            memset(st, 0, sizeof(*st));
            st->st_mode = 0100444;
            st->st_nlink = 1;
            st->st_size = size;
            st->st_blksize = 4096;
            st->st_blocks = (size + 511) / 512;
            return 0;
        } else {
            memset(st, 0, sizeof(*st));
            st->st_mode = 0040555;
            st->st_nlink = 2;
            st->st_size = 0;
            st->st_blksize = 4096;
            return 0;
        }
    }
    char host_p[1100];
    int kind = M_FREE;
    if (host_path_kind(path, host_p, sizeof host_p, &kind) == 0) {
        struct stat hst;
        if (stat(host_p, &hst) != 0) {
            guest_set_errno(errno);
            return -1;
        }
        fill_guest_stat_from_host(st, &hst);
        return 0;
    }
    guest_set_errno(ENOENT);
    return -1;
}

static int host_libc_ftruncate(int fd, off_t length) {
    if (fd < GUEST_FD_BASE) {
        if (fd > 2) { int (*fn)(int, off_t) = sdk_libc("ftruncate"); return fn ? fn(fd, length) : -1; }
        guest_set_errno(EBADF);   /* stdio or negative: never truncate the host's */
        return -1;
    }
    pthread_mutex_lock(&s_guest_fd_lock);
    GuestFdEntry *e = get_guest_fd(fd);
    if (!e) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EBADF);
        return -1;
    }
    if (e->is_rom) {
        pthread_mutex_unlock(&s_guest_fd_lock);
        guest_set_errno(EROFS);
        return -1;
    }
    int hfd = e->host_fd;
    int is_save = e->is_save;
    pthread_mutex_unlock(&s_guest_fd_lock);
    int r = ftruncate(hfd, length);
    if (r < 0) guest_set_errno(errno);
    if (is_save) save_touched();
    return r;
}

static int host_libc_unlink(const char *path) {
    if (!path) { guest_set_errno(EINVAL); return -1; }
    if (runtime_romfs_owns(path)) { guest_set_errno(EROFS); return -1; }
    char p[1100];
    if (save_change_path(path, p, sizeof p) == 0) {
        int r = unlink(p);
        if (r < 0) guest_set_errno(errno);
        return r;
    }
    guest_set_errno(ENOENT);
    return -1;
}

static int host_libc_mkdir(const char *path, mode_t mode) {
    if (!path) { guest_set_errno(EINVAL); return -1; }
    if (runtime_romfs_owns(path)) { guest_set_errno(EROFS); return -1; }
    char p[1100];
    if (save_change_path(path, p, sizeof p) == 0) {
        int r = mkdir(p, mode);
        if (r < 0) guest_set_errno(errno);
        return r;
    }
    guest_set_errno(ENOENT);
    return -1;
}

static int host_libc_rmdir(const char *path) {
    if (!path) { guest_set_errno(EINVAL); return -1; }
    if (runtime_romfs_owns(path)) { guest_set_errno(EROFS); return -1; }
    char p[1100];
    if (save_change_path(path, p, sizeof p) == 0) {
        int r = rmdir(p);
        if (r < 0) guest_set_errno(errno);
        return r;
    }
    guest_set_errno(ENOENT);
    return -1;
}

void *runtime_fs_host_override(const char *name) {
    static const struct { const char *name; void *fn; } map[] = {
        {"open", host_libc_open}, {"fstat", host_libc_fstat}, {"read", host_libc_read},
        {"lseek", host_libc_lseek}, {"close", host_libc_close}, {"stat", host_libc_stat},
        {"write", host_libc_write}, {"ftruncate", host_libc_ftruncate}, {"unlink", host_libc_unlink},
        {"mkdir", host_libc_mkdir}, {"rmdir", host_libc_rmdir},
        {"_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci", open_file}, {"_ZN2nn2fs11GetFileSizeEPlNS0_10FileHandleE", file_size},
        {"_ZN2nn2fs9CloseFileENS0_10FileHandleE", close_file}, {"_ZN2nn2fs12GetEntryTypeEPNS0_18DirectoryEntryTypeEPKc", entry_type},
        {"_ZN2nn2fs8ReadFileEPmNS0_10FileHandleElPvm", read_file}, {"_ZN2nn2fs8ReadFileEPmNS0_10FileHandleElPvmRKNS0_10ReadOptionE", read_options},
        {"_ZN2nn2fs8ReadFileENS0_10FileHandleElPvm", read_exact},
        {"_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE", write_file},
        {"_ZN2nn2fs11SetFileSizeENS0_10FileHandleEl", set_file_size}, {"_ZN2nn2fs9FlushFileENS0_10FileHandleE", flush_file},
        {"_ZN2nn2fs10CreateFileEPKcl", create_file}, {"_ZN2nn2fs10DeleteFileEPKc", delete_file}, {"_ZN2nn2fs10RenameFileEPKcS2_", rename_file},
        {"_ZN2nn2fs15CreateDirectoryEPKc", create_directory}, {"_ZN2nn2fs15DeleteDirectoryEPKc", delete_directory},
        {"_ZN2nn2fs26DeleteDirectoryRecursivelyEPKc", delete_recursive}, {"_ZN2nn2fs15RenameDirectoryEPKcS2_", rename_directory},
        {"_ZN2nn2fs16GetFreeSpaceSizeEPlPKc", get_free_space_size},
        {"_ZN2nn2fs13OpenDirectoryEPNS0_15DirectoryHandleEPKci", open_directory},
        {"_ZN2nn2fs13ReadDirectoryEPlPNS0_14DirectoryEntryENS0_15DirectoryHandleEl", read_directory},
        {"_ZN2nn2fs22GetDirectoryEntryCountEPlNS0_15DirectoryHandleE", directory_entry_count},
        {"_ZN2nn2fs14CloseDirectoryENS0_15DirectoryHandleE", close_directory},
        {"_ZN2nn2fs13MountSaveDataEPKcRKNS_7account3UidE", mount_save},
        {"_ZN2nn2fs21MountSaveDataReadOnlyEPKcNS_13ApplicationIdERKNS_7account3UidE", mount_save_ro},
        {"_ZN2nn2fs18IsSaveDataExistingENS_13ApplicationIdERKNS_7account3UidE", save_exists},
        {"_ZN2nn2fs9IsMountedEPKc", is_mounted},
        {"_ZN2nn2fs15GetSaveDataSizeEPlS1_RKNS_7account3UidE", get_save_data_size},
        {"_ZN2nn2fs18GetSaveDataSizeMaxEPlS1_", get_save_data_size_max},
        {"_ZN2nn2fs14ExtendSaveDataERKNS_7account3UidEll", extend_save_data},
        {"_ZN2nn2fs21MountTemporaryStorageEPKc", mount_temp}, {"_ZN2nn2fs7UnmountEPKc", unmount}, {"_ZN2nn2fs6CommitEPKc", commit},
        {"_ZN2nn2fs14CommitSaveDataEPKc", commit}, {"_ZN2nn2fs14EnsureSaveDataERKNS_7account3UidE", ensure_save},
        {"_ZN2nn2fs18CreateCacheStorageEill", create_cache}, {"_ZN2nn2fs18DeleteCacheStorageEi", delete_cache},
        {"_ZN2nn2fs17MountCacheStorageEPKc", mount_cache_storage},
        {"_ZN2nn2fs17MountCacheStorageEPKci", mount_cache},
        {"_ZN2nn2fs18GetCacheStorageMaxEPiPl", get_cache_storage_max},
        {"_ZN2nn2fs19GetCacheStorageSizeEPlS1_i", get_cache_storage_size},
        {"_ZN2nn2fs20OpenCacheStorageListEPNS0_22CacheStorageListHandleE", open_cache_list},
        {"_ZN2nn2fs20ReadCacheStorageListEPiPNS0_16CacheStorageInfoENS0_22CacheStorageListHandleEi", read_cache_list},
        {"_ZN2nn2fs21CloseCacheStorageListENS0_22CacheStorageListHandleE", close_cache_list},
        {"_ZN2nn2fs17MountAddOnContentEPKciPvm", mount_aoc},
        {"_ZN2nn2fs31QueryMountAddOnContentCacheSizeEPmi", query_mount_aoc_cache_size},
        {"_ZN2nn2fs26SetPriorityOnCurrentThreadENS0_8PriorityE", set_priority},
    };
    for (size_t i = 0; i < sizeof map / sizeof *map; i++) if (!strcmp(name, map[i].name)) return map[i].fn;
    return NULL;
}
