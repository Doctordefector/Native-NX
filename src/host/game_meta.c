// [Pikmin 4] The game's own name and icon for the window, read from the player's dump: control.nacp and icon.jpg
// beside the ExeFS folder (nx_extract writes them there). Nothing of the game is in the source tree; without the files
// the window is called UltraTears and keeps the exe's icon.
#include "host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_JPEG
#define STBI_NO_STDIO_WARNINGS
#include "../../third_party/stb/stb_image.h"   // stb_image 2.23 (public domain / MIT), from nxnative's third_party

static char g_title[0x201] = "UltraTears";
static char g_icon_path[4200];

// NACP: 16 title entries of 0x300 bytes (name 0x200, publisher 0x100), entry 0 American English, then British English
static void read_nacp(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return;
    unsigned char d[0x600];
    size_t n = fread(d, 1, sizeof d, f);
    fclose(f);
    for (int e = 0; e < 2 && (size_t)(e + 1) * 0x300 <= n; e++)
        if (d[e * 0x300]) { snprintf(g_title, sizeof g_title, "%.*s", 0x200, (const char *)d + e * 0x300); return; }
}

void game_meta_init(const char *exefs) {
    char dir[4096];
    snprintf(dir, sizeof dir, "%s", exefs ? exefs : "");
    size_t l = strlen(dir);
    while (l && (dir[l - 1] == '/' || dir[l - 1] == '\\')) dir[--l] = 0;   // ".../extract/ExeFS/" -> ".../extract"
    while (l && dir[l - 1] != '/' && dir[l - 1] != '\\') l--;
    dir[l] = 0;
    char p[4200];
    snprintf(p, sizeof p, "%scontrol.nacp", dir);
    read_nacp(p);
    snprintf(g_icon_path, sizeof g_icon_path, "%sicon.jpg", dir);
    fprintf(stderr, "[totk] game: %s\n", g_title);
}

const char *game_meta_title(void) { return g_title; }

// icon.jpg (256x256 on the Switch) decoded to 32-bit RGBA, top-down; free() the pixels
int game_meta_icon(unsigned char **px, int *w, int *h) {
    *px = NULL;
    if (!g_icon_path[0]) return 0;
    int n = 0;
    *px = stbi_load(g_icon_path, w, h, &n, 4);
    return *px != NULL;
}
