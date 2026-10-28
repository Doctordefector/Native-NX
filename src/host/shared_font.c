/* nn::pl shared fonts: the player's system BFTTF files (extracted from their firmware by
 * MacNativeGames tools/extract_shared_fonts.py as <type>-<name>.bfttf) laid out back to back as in the pl shared memory.
 * After MacNativeGames games/totk/runtime/shared_font.c @b75be8c (MIT): GetSharedFontAddress points 8 bytes past each
 * file start (after the BFTTF header), as the SDK adds the service-provided offset to the shared memory base; the size
 * is the decoded font size. Changes: the directory comes from TOTK_SHARED_FONTS (default data/fonts),
 * and files are checked by their BFTTF header instead of SHA-256 rows of one firmware version. */
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"
#include "../runtime/hle.h"

#define SHARED_FONT_COUNT 6
static const char *const names[SHARED_FONT_COUNT] = {
    "0-standard", "1-chinese-simplified", "2-chinese-simplified-extension", "3-chinese-traditional", "4-korean",
    "5-nintendo-extension",
};
static uint8_t *region;
static uint64_t offsets[SHARED_FONT_COUNT], font_bytes[SHARED_FONT_COUNT];
static pthread_once_t once = PTHREAD_ONCE_INIT;

static void need(int c, const char *m) { if (!c) runtime_fail(m); }
static uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

static void load(void) {
    const char *dir = getenv("TOTK_SHARED_FONTS");
    if (!dir) dir = "data/fonts";
    FILE *f[SHARED_FONT_COUNT];
    uint64_t sizes[SHARED_FONT_COUNT], total = 0;
    for (int i = 0; i < SHARED_FONT_COUNT; i++) {
        char path[4096];
        need(snprintf(path, sizeof path, "%s/%s.bfttf", dir, names[i]) < (int)sizeof path, "shared font path");
        f[i] = fopen(path, "rb");
        if (!f[i]) { fprintf(stderr, "[totk] %s missing (TOTK_SHARED_FONTS)\n", path); runtime_fail("open shared font"); }
        fseek(f[i], 0, SEEK_END);
        sizes[i] = (uint64_t)ftell(f[i]);
        fseek(f[i], 0, SEEK_SET);
        need(sizes[i] > 8 && sizes[i] < (64u << 20), "shared font size");
        total += sizes[i];
    }
    region = malloc(total);
    need(region != NULL, "shared font memory");
    uint64_t at = 0;
    for (int i = 0; i < SHARED_FONT_COUNT; i++) {
        need(fread(region + at, 1, sizes[i], f[i]) == sizes[i], "shared font read");
        fclose(f[i]);
        // BFTTF header: magic and size, each XORed with the same key; the magic decodes to 0x18029a7f.
        uint32_t key = be32(region + at) ^ 0x18029a7fu, n = be32(region + at + 4) ^ key;
        need(n == sizes[i] - 8, "shared font BFTTF header");
        offsets[i] = at + 8;
        font_bytes[i] = n;
        at += sizes[i];
    }
    fprintf(stderr, "[totk] shared fonts loaded: %d fonts, %llu bytes\n", SHARED_FONT_COUNT, (unsigned long long)total);
}
static int valid(int type) {
    if (type < 0 || type >= SHARED_FONT_COUNT) runtime_fail("invalid shared font type");
    pthread_once(&once, load);
    return type;
}
static int load_state(int type) { valid(type); return 1; }   /* SharedFontLoadState_Loaded */
static const void *address(int type) { return region + offsets[valid(type)]; }
static size_t size(int type) { return (size_t)font_bytes[valid(type)]; }

HLE_NATIVE("_ZN2nn2pl22GetSharedFontLoadStateENS0_14SharedFontTypeE", load_state, 'w')
HLE_NATIVE("_ZN2nn2pl20GetSharedFontAddressENS0_14SharedFontTypeE", address, 'x')
HLE_NATIVE("_ZN2nn2pl17GetSharedFontSizeENS0_14SharedFontTypeE", size, 'x')
