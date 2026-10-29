/* Offline local user identity: one persistent user, validated handles.
 * Ported from MacNativeGames games/totk/runtime/account.c @b75be8c (MIT). Changes: guest-register binding through
 * HLE_NATIVE; Windows file locking is not needed (the game slot guarantees one game process); the lock-guard
 * diagnostics are dropped. */
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "host.h"
#include "../runtime/hle.h"

typedef struct { uint64_t lo, hi; } Uid;
typedef struct { Uid uid; uint64_t token; } UserHandle;
static Uid local;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static uint64_t tokens[64], next_token = 1;

const char *runtime_profile_dir(void) {
    const char *dir = getenv("TOTK_PROFILE_DIR");
    return dir ? dir : "userdata";
}

static void initialize(void) {
    pthread_mutex_lock(&lock);
    if (local.lo || local.hi) { pthread_mutex_unlock(&lock); return; }
    const char *dir = runtime_profile_dir();
    if (mkdir(dir, 0700) && errno != EEXIST) runtime_fail("create local account directory");
    char path[4096];
    if (snprintf(path, sizeof path, "%s/account.uid", dir) >= (int)sizeof path) runtime_fail("local account path length");
    int fd = open(path, O_RDWR | O_CREAT | O_BINARY, 0600);
    if (fd < 0) runtime_fail("open local account identity");
    struct stat st;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode)) runtime_fail("invalid local account identity file");
    if (st.st_size == 0) {
        do { local.lo = ((uint64_t)arc4random() << 32) | arc4random(); local.hi = ((uint64_t)arc4random() << 32) | arc4random(); } while (!local.lo && !local.hi);
        if (write(fd, &local, sizeof local) != sizeof local || fsync(fd)) runtime_fail("persist local account identity");
    } else if (st.st_size != sizeof local || pread(fd, &local, sizeof local, 0) != sizeof local || (!local.lo && !local.hi)) {
        runtime_fail("corrupt local account identity");
    }
    close(fd);
    pthread_mutex_unlock(&lock);
    fprintf(stderr, "[totk] persistent local account initialized\n");
}
static bool same(const Uid *uid) { return uid && uid->lo == local.lo && uid->hi == local.hi; }
static bool valid(const UserHandle *h) {
    if (!h || !same(&h->uid)) return false;
    for (unsigned i = 0; i < 64; i++) if (tokens[i] && tokens[i] == h->token) return true;
    return false;
}
static unsigned preselected(UserHandle *out) {
    if (!out) runtime_fail("account null user handle");
    initialize();
    pthread_mutex_lock(&lock);
    for (unsigned i = 0; i < 64; i++)
        if (!tokens[i]) { tokens[i] = next_token++; *out = (UserHandle){local, tokens[i]}; pthread_mutex_unlock(&lock); return 1; }
    pthread_mutex_unlock(&lock);
    return 0;
}
static uint32_t user_id(Uid *out, const UserHandle *h) {
    pthread_mutex_lock(&lock);
    bool ok = out && valid(h);
    if (ok) *out = local;
    pthread_mutex_unlock(&lock);
    return ok ? 0 : 0x7c67;
}
static void close_user(const UserHandle *h) {
    pthread_mutex_lock(&lock);
    if (!valid(h)) runtime_fail("invalid local account handle close");
    for (unsigned i = 0; i < 64; i++) if (tokens[i] == h->token) { tokens[i] = 0; break; }
    pthread_mutex_unlock(&lock);
}
static uint32_t existence(unsigned char *out, const Uid *uid) {
    if (!out || !uid) return 0x7c67;
    initialize();
    *out = same(uid);
    return 0;
}
static uint32_t nickname(char *out, const Uid *uid) {
    initialize();
    if (!out || !same(uid)) return 0x7c67;
    memset(out, 0, 33);
    memcpy(out, "Local", 5);
    return 0;
}
void runtime_account_uid(uint64_t out[2]) { initialize(); out[0] = local.lo; out[1] = local.hi; }
/* [Pikmin 4] Push/PopOpenUsers carry the open user over a program restart (Unreal calls them at boot): hand back
   the handles still open; with none, open the local user (as the launcher's preselection would). Network service
   accounts are never available offline. */
static void push_open_users(void) {}
static uint32_t pop_open_users(int *count, UserHandle *out, int max) {
    if (!count || max < 0 || (!out && max)) return 0x7c67;
    initialize();
    int n = 0;
    pthread_mutex_lock(&lock);
    for (unsigned i = 0; i < 64 && n < max; i++) if (tokens[i]) out[n++] = (UserHandle){local, tokens[i]};
    pthread_mutex_unlock(&lock);
    if (!n && max && preselected(&out[0])) n = 1;
    *count = n;
    return 0;
}
static uint32_t nsa_available(unsigned char *out, const UserHandle *h) { (void)h; if (!out) return 0x7c67; *out = 0; return 0; }
#define R_NSA_UNAVAILABLE 0x34e7c   /* account module 124: network service account unavailable */
static uint32_t nsa_ensure(const UserHandle *h) { (void)h; return R_NSA_UNAVAILABLE; }
static void nintendo_info_ctor(void *self) { if (self) memset(self, 0, 0x100); }
static uint32_t nintendo_info_load(void *info, const UserHandle *h, void *buf, uint64_t size) {
    (void)info; (void)h; (void)buf; (void)size;
    return R_NSA_UNAVAILABLE;
}
HLE_NATIVE("_ZN2nn7account13PushOpenUsersEv", push_open_users, 'v')
HLE_NATIVE("_ZN2nn7account12PopOpenUsersEPiPNS0_10UserHandleEi", pop_open_users, 'w')
HLE_NATIVE("_ZN2nn7account32IsNetworkServiceAccountAvailableEPbRKNS0_10UserHandleE", nsa_available, 'w')
HLE_NATIVE("_ZN2nn7account36EnsureNetworkServiceAccountAvailableERKNS0_10UserHandleE", nsa_ensure, 'w')
HLE_NATIVE("_ZN2nn7account25CachedNintendoAccountInfoC1Ev", nintendo_info_ctor, 'v')
HLE_NATIVE("_ZN2nn7account29LoadCachedNintendoAccountInfoEPNS0_25CachedNintendoAccountInfoERKNS0_10UserHandleEPvm",
           nintendo_info_load, 'w')

HLE_NATIVE("_ZN2nn7account10InitializeEv", initialize, 'v')
HLE_NATIVE("_ZN2nn7account22TryOpenPreselectedUserEPNS0_10UserHandleE", preselected, 'b')
HLE_NATIVE("_ZN2nn7account9CloseUserERKNS0_10UserHandleE", close_user, 'v')
HLE_NATIVE("_ZN2nn7account9GetUserIdEPNS0_3UidERKNS0_10UserHandleE", user_id, 'w')
HLE_NATIVE("_ZN2nn7account16GetUserExistenceEPbRKNS0_3UidE", existence, 'w')
HLE_NATIVE("_ZN2nn7account11GetNicknameEPNS0_8NicknameERKNS0_3UidE", nickname, 'w')
