/* [Pikmin 4] hwopus: the hardware Opus decoder service, served on the host with libopus.
 * TOTK calls the C codec API that opus_codec.c binds by symbol; Pikmin 4's Wwise uses nn::codec::HardwareOpusDecoder,
 * whose methods live in the sdk module and talk to this service over IPC, so the SDK client runs unchanged.
 * Interfaces (SDK 10.x command ids; Switchbrew "Audio services", hwopus):
 *   IHardwareOpusDecoderManager  0 OpenHardwareOpusDecoder({u32 rate, u32 channels}, u32 work size; copy tmem)
 *                                1 GetWorkBufferSize({u32 rate, u32 channels}) -> u32
 *   IHardwareOpusDecoder         0 DecodeInterleavedOld            (A: input, B: PCM s16) -> u32 consumed, u32 samples
 *                                4 DecodeInterleavedWithPerfOld                           -> ... , u64 time (us)
 *                                6 DecodeInterleavedWithPerfAndResetOld (u8 reset)        -> ... , u64 time (us)
 * Each input frame is Nintendo's 8-byte big-endian header {payload size, final range} and the Opus packet; consumed
 * counts the header. The final range is checked as in opus_codec.c (0 = not recorded). */
#include <opus/opus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"
#include "ipc.h"

#define R_INVALID 0x1fcd1u           /* codec: invalid argument (module 111) */
#define R_DECODE_FAILED 0x3fcd1u     /* codec: decode failed */
#define MAX_FRAME_SAMPLES 5760       /* 120 ms at 48 kHz */

typedef struct { OpusDecoder *dec; int rate, channels; } HwDecoder;

static int valid_format(int rate, int channels) {
    return (rate == 48000 || rate == 24000 || rate == 16000 || rate == 12000 || rate == 8000) && (channels == 1 || channels == 2);
}
static uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

static void decoder_close(void *state) {
    HwDecoder *d = state;
    if (d) { opus_decoder_destroy(d->dec); free(d); }
}

static void decoder_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    HwDecoder *d = s->state;
    switch (rq->cmd) {
    case 0: case 4: case 6: {
        if (rq->cmd == 6 && IPC_ARG(rq, uint8_t, 0)) opus_decoder_ctl(d->dec, OPUS_RESET_STATE);
        if (!rq->na || !rq->nb) { rs->result = R_INVALID; return; }
        const uint8_t *in = ipc_guest(rq->a[0].addr, rq->a[0].size);
        int16_t *out = ipc_guest(rq->b[0].addr, rq->b[0].size);
        uint64_t in_size = rq->a[0].size, out_frames = rq->b[0].size / (2u * (unsigned)d->channels);
        if (!in || !out || in_size < 8) { rs->result = R_INVALID; return; }
        uint32_t size = be32(in), range = be32(in + 4);
        if (size > in_size - 8) { rs->result = R_INVALID; return; }
        uint64_t t0 = runtime_now_ns();
        int n = opus_decode(d->dec, in + 8, (opus_int32)size, out, (int)(out_frames < MAX_FRAME_SAMPLES ? out_frames : MAX_FRAME_SAMPLES), 0);
        if (n < 0) { fprintf(stderr, "[totk-audio] hwopus decode failed: %s\n", opus_strerror(n)); rs->result = R_DECODE_FAILED; return; }
        opus_uint32 final = 0;
        opus_decoder_ctl(d->dec, OPUS_GET_FINAL_RANGE(&final));
        if (range && final != range) { fprintf(stderr, "[totk-audio] hwopus final range %#x, header %#x\n", final, range); rs->result = R_DECODE_FAILED; return; }
        struct { uint32_t consumed, samples; uint64_t time_us; } r = {8 + size, (uint32_t)n, (runtime_now_ns() - t0) / 1000};
        ipc_out(rs, &r, rq->cmd == 0 ? 8 : sizeof r);
        return;
    }
    case 1:   /* SetContext: the SDK hands back state it saved; libopus keeps its own */
        return;
    default:
        ipc_unimplemented(s, rq);
    }
}

static void manager_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: {
        int rate = (int)IPC_ARG(rq, uint32_t, 0), channels = (int)IPC_ARG(rq, uint32_t, 4);
        if (!valid_format(rate, channels)) { rs->result = R_INVALID; return; }
        int err = 0;
        HwDecoder *d = calloc(1, sizeof *d);
        if (!d) runtime_fail("hwopus decoder allocation");
        d->dec = opus_decoder_create(rate, channels, &err);
        if (err != OPUS_OK || !d->dec) { free(d); rs->result = R_INVALID; return; }
        d->rate = rate; d->channels = channels;
        ipc_out_object(s, rs, "IHardwareOpusDecoder", decoder_handler, d, decoder_close);
        return;
    }
    case 1: {
        int rate = (int)IPC_ARG(rq, uint32_t, 0), channels = (int)IPC_ARG(rq, uint32_t, 4);
        uint32_t size = valid_format(rate, channels) ? (uint32_t)opus_decoder_get_size(channels) + 0x1000 : 0;
        if (!size) { rs->result = R_INVALID; return; }
        IPC_OUT(rs, size);
        return;
    }
    default:
        ipc_unimplemented(s, rq);
    }
}

void runtime_hwopus_register(void) { runtime_ipc_register("hwopus", manager_handler, NULL, NULL); }
