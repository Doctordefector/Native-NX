/* lm: the system log manager. TOTK 1.4.3's SDK opens it unconditionally in nninitInitializeSdkModule
 * (nn::lm::Initialize -> CreateLogServiceByHipc). Command ids follow the public service description (libnx / Switchbrew:
 * lm OpenLogger = 0; ILogger Log = 0, SetDestination = 1). Log packets are accepted and dropped unless
 * TOTK_LM_LOG is set, which counts them. */
#include <stdio.h>
#include <stdlib.h>

#include "host.h"
#include "ipc.h"

static unsigned long g_packets;

static void logger(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: {   /* Log(buffer) */
        if (!getenv("TOTK_LM_LOG")) return;
        ++g_packets;
        /* [Pikmin 4] print the text: a 24-byte header (payload size at +0x14), then chunks {u8 key, ULEB128 size, data};
           key 2 = text log (Atmosphere's LogDataChunkKey) */
        IpcBuffer b = rq->nx ? rq->x[0] : rq->na ? rq->a[0] : (IpcBuffer){0};
        const uint8_t *d = b.size >= 24 ? ipc_guest(b.addr, b.size) : NULL;
        if (!d) return;
        uint32_t payload = (uint32_t)d[0x14] | (uint32_t)d[0x15] << 8 | (uint32_t)d[0x16] << 16 | (uint32_t)d[0x17] << 24;
        size_t end = 24 + (payload < b.size - 24 ? payload : b.size - 24), i = 24;
        while (i < end) {
            uint8_t key = d[i++];
            uint64_t len = 0; int sh = 0;
            while (i < end) { uint8_t c = d[i++]; len |= (uint64_t)(c & 0x7f) << sh; sh += 7; if (!(c & 0x80)) break; }
            if (len > end - i) break;
            if (key == 2 && len) fprintf(stderr, "[totk-lm] %.*s%s", (int)len, (const char *)d + i, d[i + len - 1] == '\n' ? "" : "\n");
            i += len;
        }
        return;
    }
    case 1:   /* SetDestination(u32) */
        return;
    default: ipc_unimplemented(s, rq);
    }
}

static void lm(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0:   /* OpenLogger(pid) -> ILogger */
        ipc_out_object(s, rs, "lm:ILogger", logger, NULL, NULL);
        return;
    default: ipc_unimplemented(s, rq);
    }
}

void runtime_audio_register(void);  // audio_renderer.c
void runtime_hwopus_register(void);  // hwopus_service.c [Pikmin 4]
void runtime_audout_register(void);  // audout_service.c [Pikmin 4]
void host_services_register(void) {
    runtime_ipc_register("lm", lm, NULL, NULL);
    runtime_audio_register();
    runtime_hwopus_register();
    runtime_audout_register();
}
