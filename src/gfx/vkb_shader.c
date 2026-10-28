// Shaders of the NVN replayer (milestone 3.3 step 4): the game's Maxwell shaders, translated to SPIR-V by Ryujinx's
// translator (MacNativeGames' totk_xlate), become Vulkan shader objects (VK_EXT_shader_object): no pipelines to build
// at draw time, every other state is dynamic.
//  - A shader is identified as MacNativeGames does: SHA-256 of its control section (0x880 bytes) and its code (length
//    at control+0x704); the stage is at control+0x714 (0 vertex, 1 fragment, 5 compute).
//  - [temporary] The translation is the default variant from the translator comparison (work/shaders/v143/ryujinx: every
//    texture 2D-typed by its own reflection, attributes and outputs float). The runtime translation service with
//    variants per bound state (MacNativeGames' totk_shader_rt) replaces it before the open world.
//  - Descriptors: one universal layout. Each stage owns 76 bindings of set 0 (vertex 0-75, fragment 76-151, geometry 152-227; compute its
//    own layout): +0 Ryujinx support buffer, +1..17 constant buffers c0-c16, +18..33 storage buffers, +34..57 combined
//    textures, +58..61 images. The translator numbers bindings densely per shader; they are rewritten in the SPIR-V
//    when it is loaded, so any vertex shader combines with any fragment shader under one pipeline layout.
#include <windows.h>
#include <bcrypt.h>   // after windows.h (its types)
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "compat/gfx_compat.h"
#include "host/hle.h"
#include "vkb.h"
#include "vkb_shader.h"
#include "vkb_spv.h"

#define VLOG(...) LOG("[vk] " __VA_ARGS__)

static VkDescriptorSetLayout g_layout[2];   // 0 graphics, 1 compute
static VkPipelineLayout g_playout[2];

static void make_layouts(void) {
    for (int compute = 0; compute < 2; compute++) {
        VkDescriptorSetLayoutBinding b[VKB_GFX_STAGES * VKB_STAGE_BINDINGS];
        VkDescriptorBindingFlags fl[VKB_GFX_STAGES * VKB_STAGE_BINDINGS];
        uint32_t n = 0;
        for (int st = 0; st < (compute ? 1 : VKB_GFX_STAGES); st++) {
            VkShaderStageFlags sf = compute ? VK_SHADER_STAGE_COMPUTE_BIT : st == 2 ? VK_SHADER_STAGE_GEOMETRY_BIT : st ? VK_SHADER_STAGE_FRAGMENT_BIT : VK_SHADER_STAGE_VERTEX_BIT;
            uint32_t base = (uint32_t)st * VKB_STAGE_BINDINGS;
            struct { uint32_t off, count; VkDescriptorType type; } r[] = {
                {VKB_B_SUPPORT, 1, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER}, {VKB_B_CBUF, VKB_NCBUF, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER},
                {VKB_B_SBUF, VKB_NSBUF, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, {VKB_B_TEX, VKB_NTEX, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER},
                {VKB_B_IMG, VKB_NIMG, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE}, {VKB_B_TBUF, VKB_NTBUF, VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER},
                {VKB_B_STBUF, VKB_NSTBUF, VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER}};
            for (unsigned k = 0; k < sizeof r / sizeof *r; k++)
                for (uint32_t i = 0; i < r[k].count; i++) {
                    b[n] = (VkDescriptorSetLayoutBinding){base + r[k].off + i, r[k].type, 1, sf, NULL};
                    fl[n++] = VK_DESCRIPTOR_BINDING_PARTIALLY_BOUND_BIT;   // only what the shaders use is written
                }
        }
        VkDescriptorSetLayoutBindingFlagsCreateInfo fi = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_BINDING_FLAGS_CREATE_INFO,
                                                          .bindingCount = n, .pBindingFlags = fl};
        VkDescriptorSetLayoutCreateInfo ci = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, &fi, .bindingCount = n, .pBindings = b};
        if (vkb_db_on()) { ci.pNext = NULL; ci.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_DESCRIPTOR_BUFFER_BIT_EXT; }   // vkb_desc.c
        if (!vk_check(vk.vkCreateDescriptorSetLayout(vkc.device, &ci, NULL, &g_layout[compute]), "descriptor set layout")) die("layout");
        VkPipelineLayoutCreateInfo pi = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &g_layout[compute]};
        if (!vk_check(vk.vkCreatePipelineLayout(vkc.device, &pi, NULL, &g_playout[compute]), "pipeline layout")) die("layout");
    }
    if (vkb_db_on()) vkb_db_layouts(g_layout);
}
VkDescriptorSetLayout vkb_set_layout(int compute) { if (!g_layout[0]) make_layouts(); return g_layout[compute]; }
VkPipelineLayout vkb_pipeline_layout(int compute) { if (!g_layout[0]) make_layouts(); return g_playout[compute]; }

// ---------------- the reflection (<key>.res.json): a small reader for its fixed shape ----------------
static const char *json_array(const char *j, const char *name) {   // just after the '[' of "name": [
    char pat[64];
    snprintf(pat, sizeof pat, "\"%s\"", name);
    const char *p = strstr(j, pat);
    if (!p) return NULL;
    p = strchr(p + strlen(pat), '[');
    return p ? p + 1 : NULL;
}
// next {...} object of an array: its bounds; NULL at the closing ']'
static const char *json_next(const char *p, const char **end) {
    while (*p && *p != '{' && *p != ']') p++;
    if (*p != '{') return NULL;
    int depth = 0;
    for (const char *q = p; *q; q++) {
        if (*q == '{') depth++;
        else if (*q == '}' && !--depth) { *end = q + 1; return p; }
    }
    return NULL;
}
static long json_int(const char *obj, const char *end, const char *key, long dflt) {
    char pat[64];
    snprintf(pat, sizeof pat, "\"%s\":", key);
    const char *p = strstr(obj, pat);
    if (!p || p >= end) return dflt;
    p += strlen(pat);
    while (*p == ' ') p++;
    if (!strncmp(p, "true", 4)) return 1;
    if (!strncmp(p, "false", 5)) return 0;
    return strtol(p, NULL, 10);
}
static long json_top_int(const char *j, const char *key, long dflt) { return json_int(j, j + strlen(j), key, dflt); }

static char *read_file(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)len + 1);
    if (b && fread(b, 1, (size_t)len, f) != (size_t)len) { free(b); b = NULL; }
    if (b) b[len] = 0;
    fclose(f);
    if (n) *n = (size_t)len;
    return b;
}

// ---------------- shaders by key ----------------
typedef struct shentry { char key[65]; int c1_set, prewarmed; vkb_shader sh; struct shentry *next; } shentry;   // prewarmed: made ahead (prewarm_thread)
static shentry *g_tab[4096];
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static uint64_t g_loaded, g_missing;

static BCRYPT_ALG_HANDLE g_sha;   // opened once (opening it per hash cost more than the hash)
static void sha_open(void) { if (BCryptOpenAlgorithmProvider(&g_sha, BCRYPT_SHA256_ALGORITHM, NULL, 0)) die("SHA-256 provider"); }
static void sha256_hex(const void *a, size_t na, const void *b, size_t nb, char out[65]) {
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    pthread_once(&once, sha_open);
    BCRYPT_ALG_HANDLE alg = g_sha;
    BCRYPT_HASH_HANDLE h;
    uint8_t md[32];
    if (BCryptCreateHash(alg, &h, NULL, 0, NULL, 0, 0)) die("SHA-256 provider");
    BCryptHashData(h, (PUCHAR)a, (ULONG)na, 0);
    BCryptHashData(h, (PUCHAR)b, (ULONG)nb, 0);
    BCryptFinishHash(h, md, sizeof md, 0);
    BCryptDestroyHash(h);
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < 32; i++) { out[2 * i] = hex[md[i] >> 4]; out[2 * i + 1] = hex[md[i] & 15]; }
    out[64] = 0;
}

static const char *cache_dir(void) {
    static const char *d;
    if (!d) { d = getenv("TOTK_SHADER_DIR"); if (!d) d = "data/shaders/ryujinx"; }
    return d;
}

// The translator declares gl_PerVertex with ClipDistance[8] and CullDistance[1]: 9 > maxCombinedClipAndCullDistances (8)
// on NVIDIA, though no shader writes the cull distance. The CullDistance member (the block's last) is dropped: its
// OpTypeStruct operand, OpMemberName and OpMemberDecorate. Returns the new word count.
static size_t drop_cull_distance(uint32_t *w, size_t n) {
    uint32_t st = 0, mem = 0;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16;
        if (!wc || i + wc > n) return n;
        if (op == 72 && wc == 5 && w[i + 3] == 11 && w[i + 4] == 4) { st = w[i + 1]; mem = w[i + 2]; }   // BuiltIn CullDistance
        i += wc;
    }
    if (!st) return n;
    size_t o = 5;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16;
        int drop = (op == 72 || op == 6) && wc >= 3 && w[i + 1] == st && w[i + 2] == mem;   // OpMemberDecorate / OpMemberName
        if (op == 30 && w[i + 1] == st && wc - 2 == mem + 1) {   // OpTypeStruct: the member is the last operand
            memmove(&w[o], &w[i], (wc - 1) * 4);
            w[o] = ((wc - 1) << 16) | 30;
            o += wc - 1;
        } else if (!drop) {
            memmove(&w[o], &w[i], wc * 4);
            o += wc;
        }
        i += wc;
    }
    return o;
}

/* [Pikmin 4] Ryujinx declares a buffer texture as a sampled image of Dim Buffer, which Vulkan does not allow (a uniform
   texel buffer is an image of Dim Buffer, Sampled 1, without a sampler). Rewrites, in place: the UniformConstant
   pointer to that sampled image points to the image; loads of it give the image; OpImage of such a load becomes
   OpCopyObject; the sampled image type is dropped; capability SampledBuffer is added if missing (one word pair: the
   caller leaves room for 2 words). Returns the new word count. */
static size_t texel_buffers(uint32_t *w, size_t n) {
    enum { MAXT = 16 };
    uint32_t si[MAXT], img[MAXT], nsi = 0, loads[64], nl = 0;
    int has_cap = 0;
    size_t cap_at = 0;
    uint32_t buf_img[MAXT], nbi = 0;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16;
        if (!wc || i + wc > n) return n;
        if (op == 17) { if (w[i + 1] == 46) has_cap = 1; if (!cap_at) cap_at = i; }   // OpCapability SampledBuffer
        if (op == 25 && wc >= 9 && w[i + 3] == 5 && nbi < MAXT) buf_img[nbi++] = w[i + 1];   // OpTypeImage Dim Buffer
        if (op == 27 && wc == 3 && nsi < MAXT)                                               // OpTypeSampledImage
            for (uint32_t k = 0; k < nbi; k++) if (w[i + 2] == buf_img[k]) { si[nsi] = w[i + 1]; img[nsi++] = buf_img[k]; }
        i += wc;
    }
    int need47 = 0, has47 = 0;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16;
        if (!wc) break;
        if (op == 17 && w[i + 1] == 47) has47 = 1;
        if (op == 25 && wc >= 9 && w[i + 3] == 5 && w[i + 7] == 2) need47 = 1;   // OpTypeImage Dim Buffer, Sampled 2 (storage)
        i += wc;
    }
    if (need47 && !has47 && cap_at) {   // capability ImageBuffer
        memmove(&w[cap_at + 2], &w[cap_at], (n - cap_at) * 4);
        w[cap_at] = (2u << 16) | 17; w[cap_at + 1] = 47;
        n += 2;
    }
    // storage images without a format (Ryujinx leaves Unknown when the shader does not say): reads and writes need
    // StorageImageReadWithoutFormat (55) / StorageImageWriteWithoutFormat (56) - the validation layer's spirv-val error
    int unknown = 0, has55 = 0, has56 = 0;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16;
        if (!wc) break;
        if (op == 17 && w[i + 1] == 55) has55 = 1;
        if (op == 17 && w[i + 1] == 56) has56 = 1;
        if (op == 25 && wc >= 9 && w[i + 7] == 2 && w[i + 8] == 0) unknown = 1;   // OpTypeImage Sampled 2, Format Unknown
        i += wc;
    }
    for (int k = 0; unknown && cap_at && k < 2; k++) {
        if (k ? has56 : has55) continue;
        memmove(&w[cap_at + 2], &w[cap_at], (n - cap_at) * 4);
        w[cap_at] = (2u << 16) | 17; w[cap_at + 1] = k ? 56 : 55;
        n += 2;
    }
    if (!nsi) return n;
    size_t o = 5;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16, drop = 0;
        if (op == 27 && wc == 3) for (uint32_t k = 0; k < nsi; k++) drop |= w[i + 1] == si[k];
        if (op == 32 && wc == 4) for (uint32_t k = 0; k < nsi; k++) if (w[i + 3] == si[k]) w[i + 3] = img[k];   // OpTypePointer
        if (op == 61 && wc >= 4) for (uint32_t k = 0; k < nsi; k++)                                             // OpLoad
            if (w[i + 1] == si[k]) { w[i + 1] = img[k]; if (nl < 64) loads[nl++] = w[i + 2]; }
        if (op == 100 && wc == 4) for (uint32_t k = 0; k < nl; k++)                                             // OpImage
            if (w[i + 3] == loads[k]) w[i] = (4u << 16) | 83;                                                   // -> OpCopyObject
        if (!drop) { memmove(&w[o], &w[i], wc * 4); o += wc; }
        i += wc;
    }
    if (!has_cap && cap_at) {
        memmove(&w[cap_at + 2], &w[cap_at], (o - cap_at) * 4);
        w[cap_at] = (2u << 16) | 17; w[cap_at + 1] = 46;
        o += 2;
    }
    return o;
}

/* [Pikmin 4] spirv-val: "Vector access is out of bounds" - Ryujinx, translating a captured shader with the default bind
   state, takes an unknown texture as 2D and reads component 2 (the depth) of the 2-component OpImageQuerySize[Lod]
   result. The hardware's size query gives 0 there: the read becomes OpCopyObject of the integer constant 0, and the
   instruction keeps its length (one OpNop word). Returns how many reads were rewritten. */
static int fix_size_reads(uint32_t *w, size_t n) {
    enum { MAXQ = 256, MAXV = 64 };
    uint32_t vec[MAXV], vlen[MAXV], nv = 0, q[MAXQ], qlen[MAXQ], nq = 0, zero_t[8], zero_id[8], nz = 0;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16;
        if (!wc || i + wc > n) return 0;
        if (op == 23 && wc == 4 && nv < MAXV) { vec[nv] = w[i + 1]; vlen[nv++] = w[i + 3]; }                    // OpTypeVector
        if (op == 43 && wc == 4 && w[i + 3] == 0 && nz < 8) { zero_t[nz] = w[i + 1]; zero_id[nz++] = w[i + 2]; }   // OpConstant 0
        if ((op == 103 || op == 104) && wc >= 4 && nq < MAXQ)                                                      // OpImageQuerySize[Lod]
            for (uint32_t k = 0; k < nv; k++) if (vec[k] == w[i + 1]) { q[nq] = w[i + 2]; qlen[nq++] = vlen[k]; }
        i += wc;
    }
    int fixed = 0;
    for (size_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, wc = w[i] >> 16;
        if (op == 81 && wc == 5)   // OpCompositeExtract %type %result %composite index
            for (uint32_t k = 0; k < nq; k++)
                if (w[i + 3] == q[k] && w[i + 4] >= qlen[k])
                    for (uint32_t z = 0; z < nz; z++)
                        if (zero_t[z] == w[i + 1]) {
                            w[i] = (4u << 16) | 83; w[i + 3] = zero_id[z]; w[i + 4] = (1u << 16) | 0;   // OpCopyObject; OpNop
                            fixed++;
                            break;
                        }
        i += wc;
    }
    return fixed;
}

static VkResult create_object(VkShaderStageFlagBits stage, const uint32_t *spv, size_t bytes, VkShaderEXT *obj) {
    VkDescriptorSetLayout layout = vkb_set_layout(stage == VK_SHADER_STAGE_COMPUTE_BIT);
    VkShaderCreateInfoEXT ci = {VK_STRUCTURE_TYPE_SHADER_CREATE_INFO_EXT, .stage = stage,
        .nextStage = stage == VK_SHADER_STAGE_VERTEX_BIT ? VK_SHADER_STAGE_FRAGMENT_BIT | VK_SHADER_STAGE_GEOMETRY_BIT
                   : stage == VK_SHADER_STAGE_GEOMETRY_BIT ? VK_SHADER_STAGE_FRAGMENT_BIT : 0,
        .codeType = VK_SHADER_CODE_TYPE_SPIRV_EXT, .codeSize = bytes, .pCode = spv, .pName = "main",
        .setLayoutCount = 1, .pSetLayouts = &layout};
    return vk.vkCreateShadersEXT(vkc.device, 1, &ci, NULL, obj);
}

// A vertex shader for integer attributes at the locations in intmask (signed where sintmask has the bit): those
// inputs read the raw bits (vkb_spv.c). Made on first use and kept; 0 masks give the shader itself.
// [temporary] made during play (a compile on first use); the variant list and building ahead of time - phase 5.
VkShaderEXT vkb_shader_variant(const vkb_shader *cs, uint32_t intmask, uint32_t sintmask) {
    vkb_shader *s = (vkb_shader *)cs;
    intmask &= s->in_mask;
    sintmask &= intmask;
    if (!intmask || !s->spv) return s->obj;
    pthread_mutex_lock(&g_mu);
    for (int i = 0; i < s->nvariants; i++)
        if (s->variants[i].intmask == intmask && s->variants[i].sintmask == sintmask) { pthread_mutex_unlock(&g_mu); return s->variants[i].obj; }
    pthread_mutex_unlock(&g_mu);
    uint32_t *out = NULL;
    size_t nw = 0;
    VkShaderEXT obj = VK_NULL_HANDLE;
    if (vkb_spv_int_inputs(s->spv, s->nspv_words, intmask, sintmask, &out, &nw)) {
        if (getenv("TOTK_SPV_DUMP")) {   // development: the variant's SPIR-V for spirv-val / spirv-dis
            char path[256];
            snprintf(path, sizeof path, "%s/%.16s-i%x-s%x.spv", getenv("TOTK_SPV_DUMP"), s->key ? s->key : "x", intmask, sintmask);
            FILE *f = fopen(path, "wb");
            if (f) { fwrite(out, 4, nw, f); fclose(f); }
        }
        if (create_object(VK_SHADER_STAGE_VERTEX_BIT, out, nw * 4, &obj) != VK_SUCCESS) obj = VK_NULL_HANDLE;
        free(out);
    }
    if (!obj) {
        static int said;
        if (said++ < 8) VLOG("[temporary] shader %.12s: no variant for integer inputs %#x: the float reading stays", s->key ? s->key : "?", intmask);
        obj = s->obj;
    } else {
        static int made;
        if (made++ < 16) VLOG("shader %.12s: variant for integer inputs %#x (signed %#x)", s->key ? s->key : "?", intmask, sintmask);
    }
    pthread_mutex_lock(&g_mu);
    if (s->nvariants < VKB_VARIANTS) s->variants[s->nvariants++] = (vkb_variant){intmask, sintmask, obj};
    pthread_mutex_unlock(&g_mu);
    return obj;
}

// Reads the reflection, rewrites the SPIR-V bindings into the universal layout, creates the shader object.
static int load(vkb_shader *s, const char *key, int nvn_stage) {
    char path[1024];
    snprintf(path, sizeof path, "%s/%s.res.json", cache_dir(), key);
    char *j = read_file(path, NULL);
    snprintf(path, sizeof path, "%s/%s.spv", cache_dir(), key);
    size_t nspv = 0;
    uint32_t *spv = (uint32_t *)read_file(path, &nspv);
    if (!j || !spv || nspv < 20 || (nspv & 3) || spv[0] != 0x07230203) { free(j); free(spv); return 0; }
    s->stage = nvn_stage;
    uint32_t base = vkb_stage_base(nvn_stage);
    uint32_t remap[256];   // translator binding -> universal binding (UINT32_MAX: unknown)
    for (int i = 0; i < 256; i++) remap[i] = UINT32_MAX;
    remap[0] = base + VKB_B_SUPPORT;
    const char *p, *e;
    // constant buffers: slot = NVN constant buffer index
    if ((p = json_array(j, "cbufs")))
        for (; (p = json_next(p, &e)); p = e) {
            long b = json_int(p, e, "binding", -1), slot = json_int(p, e, "slot", -1);
            if (b < 0 || b > 255 || slot < 0 || slot >= VKB_NCBUF) continue;
            remap[b] = base + VKB_B_CBUF + (uint32_t)slot;
            s->cbuf_mask |= 1u << slot;
        }
    // storage buffers: the address comes from the NVN driver bank c0, 16 bytes per slot: the stage's storage buffer
    // table (vertex 0x110, fragment 0x510, compute 0x310) or, for compute, its uniform buffer table (0x210): TOTK's
    // compute shaders also use uniform buffers as storage (MacNativeGames' "ubo_ptr")
    int sb_base = nvn_stage == 0 ? 0x110 : nvn_stage == 1 ? 0x510 : 0x310;
    if ((p = json_array(j, "sbufs")))
        for (; (p = json_next(p, &e)); p = e) {
            long b = json_int(p, e, "binding", -1), off = json_int(p, e, "cb_offset", -1) * 4;
            if (b < 0 || b > 255 || s->nsbuf >= VKB_NSBUF) { s->unsupported = 1; continue; }
            long cb = json_int(p, e, "cb_slot", 0);
            int write = (json_int(p, e, "flags", 0) & 1) != 0;   // Ryujinx BufferUsageFlags.Write
            if (write) s->stores = 1;
            int slot = -1, kind = VKB_SB_TABLE;
            if (cb == 0 && off >= sb_base && off < sb_base + 0x100 && !(off & 15)) slot = (int)(off - sb_base) / 16;
            else if (cb == 0 && nvn_stage == 5 && off >= 0x210 && off < 0x310 && !(off & 15)) { slot = (int)(off - 0x210) / 16; kind = VKB_SB_UBO; }
            else if (cb >= 3 && cb <= 16 && off >= 0 && off < 0x10000) { slot = (int)cb - 3; kind = VKB_SB_UBO_PTR; }
            if (slot < 0 || slot >= VKB_NSBUF) {
                static int said; if (said++ < 8) VLOG("shader %s: storage buffer address from c%ld+%#lx: unknown source", key, cb, off);
                slot = 0xFF;
            }
            remap[b] = base + VKB_B_SBUF + (uint32_t)s->nsbuf;
            s->sbuf[s->nsbuf].slot = (uint8_t)slot;
            s->sbuf[s->nsbuf].kind = (uint8_t)kind;
            s->sbuf[s->nsbuf].write = (uint8_t)write;
            s->sbuf[s->nsbuf++].off = (uint16_t)(kind == VKB_SB_UBO_PTR ? off : 0);
        }
    // textures: the handle is a word offset into the NVN driver bank c2 - combined textures at 0x20 (8 bytes per slot),
    // separate textures at 0x168 (MacNativeGames' totk_xlate Service.cs)
    if ((p = json_array(j, "textures")))
        for (; (p = json_next(p, &e)); p = e) {
            /* [Pikmin 4] Ryujinx packs the handle: word offset 0 in bits 0-13, word offset 1 in bits 14-27, type in 28+
               (1: separate sampler handle, the texture and the sampler each from its own offset, in either order) */
            long b = json_int(p, e, "binding", -1), raw = json_int(p, e, "handle", -1), type = json_int(p, e, "type", 3);
            long h = (raw & 0x3fff) * 4, h1 = ((raw >> 14) & 0x3fff) * 4, kind = raw >> 28;
            if (kind == 1 && h >= 0x568) { long x = h; h = h1; h1 = x; }
            if (b < 0 || b > 255 || s->ntex >= VKB_NTEX || h < 0x20 || raw < 0 || (kind == 1 && (h < 0x168 || h >= 0x568 || h1 < 0x568)) || kind > 1) {
                static int said; if (said++ < 8) VLOG("shader %s: texture handle %#lx not understood", key, raw);
                s->unsupported = 1; continue;
            }
            int tb = type == 2;   // [Pikmin 4] TextureBuffer: a uniform texel buffer
            if (tb && s->ntbuf >= VKB_NTBUF) { s->unsupported = 1; continue; }
            vkb_tex_ref *t = tb ? &s->tbuf[s->ntbuf] : &s->tex[s->ntex];
            t->separate = h >= 0x168;
            t->slot = (uint8_t)((h - (t->separate ? 0x168 : 0x20)) / 8);
            t->sslot = kind == 1 ? (uint8_t)((h1 - 0x568) / 8) : 0;
            t->type = (uint16_t)type;
            if (tb) { remap[b] = base + VKB_B_TBUF + (uint32_t)s->ntbuf++; continue; }
            remap[b] = base + VKB_B_TEX + (uint32_t)s->ntex++;
        }
    if ((p = json_array(j, "images")))
        for (; (p = json_next(p, &e)); p = e) {
            long b = json_int(p, e, "binding", -1), h = json_int(p, e, "handle", -1) * 4, type = json_int(p, e, "type", 3);
            int sb = type == 2;   // [Pikmin 4] ImageBuffer: a storage texel buffer
            if (b < 0 || b > 255 || (sb ? s->nstbuf >= VKB_NSTBUF : s->nimg >= VKB_NIMG) || h < 0x120) { s->unsupported = 1; continue; }
            s->stores = 1;   // [temporary] images are taken as written (the reflection has no read-only mark)
            if (sb) {
                s->stbuf[s->nstbuf] = (vkb_tex_ref){(uint8_t)((h - 0x120) / 8), 0, (uint16_t)type};
                remap[b] = base + VKB_B_STBUF + (uint32_t)s->nstbuf++;
                continue;
            }
            s->img[s->nimg] = (vkb_tex_ref){(uint8_t)((h - 0x120) / 8), 0, (uint16_t)type};
            remap[b] = base + VKB_B_IMG + (uint32_t)s->nimg++;
        }
    s->frag_outputs = (uint32_t)json_top_int(j, "frag_out_map", 0);
    free(j);
    // rewrite Binding decorations (OpDecorate %id Binding n: opcode 71, decoration 33)
    if (s->ntbuf || s->nstbuf || s->nimg) {   // [Pikmin 4] room for the capabilities texel_buffers may add
        uint32_t *g = realloc(spv, nspv + 32);
        if (!g) die("shader memory");
        spv = g;
    }
    size_t nw = drop_cull_distance(spv, nspv / 4);
    if (s->ntbuf || s->nstbuf || s->nimg) nw = texel_buffers(spv, nw);
    if (fix_size_reads(spv, nw)) { static int said; if (said++ < 8) VLOG("shader %s: size query components past its vector read as 0", key); }
    nspv = nw * 4;
    for (size_t i = 5; i < nw;) {
        uint32_t op = spv[i] & 0xffff, wc = spv[i] >> 16;
        if (!wc || i + wc > nw) break;
        if (op == 71 && wc == 4 && spv[i + 2] == 33) {
            uint32_t old = spv[i + 3];
            if (old > 255 || remap[old] == UINT32_MAX) {
                VLOG("shader %s: binding %u not in its reflection", key, old);
                s->unsupported = 1;
            } else spv[i + 3] = remap[old];
        }
        i += wc;
    }
    VkShaderStageFlagBits stage = nvn_stage == 0 ? VK_SHADER_STAGE_VERTEX_BIT : nvn_stage == 1 ? VK_SHADER_STAGE_FRAGMENT_BIT
                                : nvn_stage == 2 ? VK_SHADER_STAGE_GEOMETRY_BIT : VK_SHADER_STAGE_COMPUTE_BIT;
    if (getenv("TOTK_SPV_DUMP")) {   // [Pikmin 4] development: every module as loaded (bindings and fixes applied), for spirv-val
        char dp[1024];
        snprintf(dp, sizeof dp, "%s/%.16s.spv", getenv("TOTK_SPV_DUMP"), key);
        FILE *f = fopen(dp, "wb");
        if (f) { fwrite(spv, 1, nspv, f); fclose(f); }
    }
    VkResult r = create_object(stage, spv, nspv, &s->obj);
    if (r == VK_SUCCESS) {   // input / output locations: vertex variants; fragment inputs no vertex shader writes (audit)
        s->in_mask = vkb_spv_input_mask(spv, nspv / 4);
        s->out_mask = vkb_spv_output_mask(spv, nspv / 4);
        uint32_t reads = vkb_spv_sbuf_reads(spv, nspv / 4, base + VKB_B_SBUF, s->nsbuf);
        for (int i = 0; i < s->nsbuf; i++) s->sbuf[i].read = (uint8_t)(reads >> i & 1);
    }
    if (stage == VK_SHADER_STAGE_VERTEX_BIT && r == VK_SUCCESS) {   // kept for attribute variants (vkb_shader_variant)
        s->spv = spv;
        s->nspv_words = nspv / 4;
    } else free(spv);
    if (r != VK_SUCCESS) { VLOG("shader %s: vkCreateShadersEXT %d", key, (int)r); return 0; }
    if (getenv("TOTK_VK_VALIDATION")) VLOG("shader %.12s = VkShaderEXT %#llx", key, (unsigned long long)(uintptr_t)s->obj);   // names validation messages
    s->vk_stage = stage;
    return 1;
}

// ---- shaders made ahead: creating a shader object compiles it in the driver, ~17% of the recording thread on the way
// into the world, where new shaders arrive in bursts (submissions held up to 2.3 s, Great Sky Island, 2026-10-24).
// Every shader loaded is listed (<cache>/used.txt: key and NVN stage, appended); at the first shader lookup of a run,
// PREWARM_THREADS low-priority threads create the listed ones that are not loaded yet. The first run fills the list;
// later runs find those shaders made (as SavageWind's pipeline list). The constants c1 come from the game's program
// at the first real lookup (c1_set).
enum { PREWARM_THREADS = 2 };
static uint64_t g_prewarm_made, g_prewarm_hits;
uint64_t vkb_shader_load_ns;   // shaders made when first drawn with (long submission log, backend_vk.c)
static char *g_list;   // used.txt, read once
static size_t g_list_n;
static _Atomic size_t g_list_at;
static void list_add(const char *key, int stage) {   // g_mu held
    char path[1024];
    snprintf(path, sizeof path, "%s/used.txt", cache_dir());
    FILE *f = fopen(path, "ab");
    if (!f) return;
    fprintf(f, "%s %d\n", key, stage);
    fclose(f);
}
static void *prewarm_thread(void *unused) {
    (void)unused;
    pthread_setname_np("totk-shader-prewarm");
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
    for (;;) {
        size_t at = atomic_fetch_add(&g_list_at, 67);   // one line: 64 hex digits, space, stage, newline (67 bytes)
        if (at + 67 > g_list_n) break;
        const char *l = g_list + at;
        if (l[64] != ' ' || l[66] != '\n') continue;
        char key[65];
        memcpy(key, l, 64); key[64] = 0;
        int stage = l[65] - '0';
        uint32_t h = (uint32_t)strtoul(key + 56, NULL, 16) & 4095;
        pthread_mutex_lock(&g_mu);
        shentry *e = g_tab[h];
        while (e && strcmp(e->key, key)) e = e->next;
        pthread_mutex_unlock(&g_mu);
        if (e) continue;
        shentry *n = calloc(1, sizeof *n);
        if (!n) die("shader entry");
        memcpy(n->key, key, sizeof key);
        n->sh.key = n->key;
        if (!load(&n->sh, key, stage)) { free(n); continue; }
        n->prewarmed = 1;
        pthread_mutex_lock(&g_mu);
        e = g_tab[h];
        while (e && strcmp(e->key, key)) e = e->next;
        if (!e) { n->next = g_tab[h]; g_tab[h] = n; g_prewarm_made++; g_loaded++; }
        pthread_mutex_unlock(&g_mu);
        if (e) { vk.vkDestroyShaderEXT(vkc.device, n->sh.obj, NULL); free(n->sh.spv); free(n); }   // loaded meanwhile
    }
    static _Atomic int left = PREWARM_THREADS;
    if (atomic_fetch_sub(&left, 1) == 1) VLOG("shaders made ahead from the list: %llu", (unsigned long long)g_prewarm_made);
    return NULL;
}
static void prewarm_start(void) {
    const char *e = getenv("TOTK_SHADER_PREWARM");   // =0: shaders are made only when first drawn with (A/B)
    if (e && *e == '0') return;
    char path[1024];
    snprintf(path, sizeof path, "%s/used.txt", cache_dir());
    size_t n = 0;
    if (!(g_list = read_file(path, &n))) return;
    g_list_n = n;
    VLOG("shader list: %zu shaders to make ahead", n / 67);
    for (int i = 0; i < PREWARM_THREADS; i++) {
        pthread_t t;
        if (pthread_create(&t, NULL, prewarm_thread, NULL) == 0) pthread_detach(t);
    }
}

/* [Pikmin 4] TOTK_SHADER_CAPTURE=<dir>: a shader with no translation is written as <dir>/raw/<key>.ctl (the 0x880-byte
   control section) + <key>.bin (the code as the game hands it over) and listed in <dir>/captured.tsv, the same files
   tools/export_shaders.py makes from TOTK's RomFS. A game whose shaders are not findable at build time (Unreal's are
   in its pak) gets them by playing; nxrecomp/shaders_from_capture.py translates them. Called with g_mu held. */
static void capture_shader(const char *key, uint32_t stage, const uint8_t *control, const void *code, uint32_t length) {
    static int on = -1; static char dir[1024];
    if (on < 0) { const char *e = getenv("TOTK_SHADER_CAPTURE"); on = e && *e; if (on) snprintf(dir, sizeof dir, "%s", e); }
    if (!on) return;
    char path[1200];
    snprintf(path, sizeof path, "%s/raw", dir);
    CreateDirectoryA(dir, NULL); CreateDirectoryA(path, NULL);
    {   // [Pikmin 4] the game's depth mode, for the translation (shaders_from_capture.py: depth_minus_w only for near=-w)
        int totk_depth_near_minus_w(void);
        snprintf(path, sizeof path, "%s/depth_mode.txt", dir);
        FILE *m = fopen(path, "w");
        if (m) { fputs(totk_depth_near_minus_w() ? "minus_w\n" : "zero\n", m); fclose(m); }
    }
    snprintf(path, sizeof path, "%s/raw/%s.ctl", dir, key);
    FILE *f = fopen(path, "wb");
    if (!f) { VLOG("shader capture: cannot write %s", path); on = 0; return; }
    fwrite(control, 1, 0x880, f); fclose(f);
    snprintf(path, sizeof path, "%s/raw/%s.bin", dir, key);
    if ((f = fopen(path, "wb"))) { fwrite(code, 1, length, f); fclose(f); }
    snprintf(path, sizeof path, "%s/captured.tsv", dir);
    if ((f = fopen(path, "a"))) { fprintf(f, "%s\t%u\n", key, stage); fclose(f); }
    static unsigned n; if (++n % 100 == 1) VLOG("shader capture: %u shaders written to %s", n, dir);
}

const vkb_shader *vkb_shader_get(const NVNshaderData *sd) {
    const uint8_t *control = sd->control;
    static _Atomic int said_null, said_bad;   /* [Pikmin 4] why a stage has no shader (these paths capture nothing) */
    if (!control || !sd->data) { if (atomic_fetch_add(&said_null, 1) < 4) VLOG("shader: stage without control or data (control %p data %#llx)", (const void *)control, (unsigned long long)sd->data); return NULL; }
    uint32_t length, stage;
    memcpy(&length, control + 0x704, 4);
    memcpy(&stage, control + 0x714, 4);
    if (!length || length > (16u << 20) || (stage != 0 && stage != 1 && stage != 2 && stage != 5)) {   // [Pikmin 4] 2: geometry (Unreal's volume-texture passes)
        if (atomic_fetch_add(&said_bad, 1) < 8) VLOG("shader: unsupported stage %u or length %u", stage, length);
        return NULL;
    }
    char key[65];
    sha256_hex(control, 0x880, (const void *)(uintptr_t)sd->data, length, key);
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    pthread_once(&once, prewarm_start);
    uint32_t h = (uint32_t)strtoul(key + 56, NULL, 16) & 4095;
    pthread_mutex_lock(&g_mu);
    shentry *e = g_tab[h];
    while (e && strcmp(e->key, key)) e = e->next;
    if (!e) {
        e = calloc(1, sizeof *e);
        if (!e) die("shader entry");
        memcpy(e->key, key, sizeof key);
        e->sh.key = e->key;
        uint64_t t0 = runtime_now_ns();
        int ok = load(&e->sh, key, (int)stage);
        vkb_shader_load_ns += runtime_now_ns() - t0;
        if (ok) {
            g_loaded++;
            list_add(key, (int)stage);
        }
        else {
            e->sh.obj = VK_NULL_HANDLE;
            if (g_missing++ < 16) VLOG("shader %s (stage %u): no translation in %s", key, stage, cache_dir());
            capture_shader(key, stage, control, (const void *)(uintptr_t)sd->data, length);
        }
        e->next = g_tab[h];
        g_tab[h] = e;
    }
    if (e->sh.obj && !e->c1_set) {   // loaded now or ahead (prewarm): the constants come with the game's program
        e->c1_set = 1;
        if (e->prewarmed) g_prewarm_hits++;
        uint32_t c1off;
        memcpy(&c1off, control + 0x700, 4);   // the shader's constants: the code's tail (c1)
        if (c1off < length) {   // copied: the program's memory may be freed and reused while the key stays cached
            uint8_t *c = malloc(length - c1off);
            if (!c) die("shader constants");
            memcpy(c, (const uint8_t *)(uintptr_t)sd->data + c1off, length - c1off);
            e->sh.c1 = c;
            e->sh.c1_size = length - c1off;
        }
    }
    pthread_mutex_unlock(&g_mu);
    return e->sh.obj ? &e->sh : NULL;
}

void vkb_shader_stats(uint64_t *loaded, uint64_t *missing) { *loaded = g_loaded; *missing = g_missing; }
