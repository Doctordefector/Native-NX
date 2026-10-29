/* [Pikmin 4] audout:u — the plain PCM audio output service, played through SDL3.
 * TOTK mixes through the audio renderer (audren:u, audio_renderer.c); Pikmin 4's Wwise also opens an AudioOut and
 * feeds it its own mixed PCM. The SDK's nn::audio client runs unchanged; this is the service side.
 * IAudioOutManager  0/2 ListAudioOuts[Auto]  1/3 OpenAudioOut[Auto]({u32 rate, u16 channels, u16 pad}, u64 aruid; pid,
 *                   copy process; in: device name) -> {u32 rate, u32 channels, u32 format (2 = s16), u32 state}, IAudioOut
 * IAudioOut         0 GetAudioOutState  1 Start  2 Stop  3/7 AppendAudioOutBuffer[Auto](u64 tag; in: AudioOutBuffer)
 *                   4 RegisterBufferEvent  5/8 GetReleasedAudioOutBuffers[Auto](out: u64 tags) -> u32
 *                   6 ContainsAudioOutBuffer  9 GetAudioOutBufferCount  10 GetAudioOutPlayedSampleCount
 *                   11 FlushAudioOutBuffers  12 SetAudioOutVolume(f32)  13 GetAudioOutVolume
 * A player thread pushes appended buffers to an SDL stream in order, keeps about one buffer queued, then releases each
 * buffer and signals the buffer event. Without an audio device (headless) it paces by the buffers' play time. */
#include <SDL3/SDL.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "host.h"
#include "ipc.h"

#define R_INVALID 0x199u      /* audio: invalid argument (module 153, description 1) */
#define QMAX 64

typedef struct { uint64_t next, sample_buffer, capacity, data_size, data_offset; } AudioOutBuffer;   /* the game's */
typedef struct { uint64_t tag, addr, size; } Pending;
typedef struct {
    pthread_mutex_t lock; pthread_cond_t cv;
    Pending q[QMAX]; int nq;
    uint64_t released[QMAX]; int nrel;
    uint32_t event; int started, closing, rate, channels;
    uint64_t played;
    float volume;
    SDL_AudioStream *stream;
    pthread_t thread;
} AudioOut;

static IpcBuffer pick(const IpcBuffer *a, unsigned na, const IpcBuffer *b, unsigned nb) {
    IpcBuffer x = na ? a[0] : (IpcBuffer){0}, y = nb ? b[0] : (IpcBuffer){0};
    return x.size ? x : y;
}
static void sleep_ns(uint64_t ns) { struct timespec t = {(time_t)(ns / 1000000000u), (long)(ns % 1000000000u)}; nanosleep(&t, NULL); }

static void *player(void *arg) {
    AudioOut *o = arg;
    pthread_mutex_lock(&o->lock);
    for (;;) {
        while (!o->closing && (!o->started || !o->nq)) pthread_cond_wait(&o->cv, &o->lock);
        if (o->closing) break;
        Pending p = o->q[0];
        pthread_mutex_unlock(&o->lock);
        const void *pcm = ipc_guest(p.addr, p.size);
        uint64_t frames = p.size / (2u * (unsigned)o->channels);
        if (o->stream && pcm) {
            SDL_PutAudioStreamData(o->stream, pcm, (int)p.size);
            while (SDL_GetAudioStreamQueued(o->stream) > (int)p.size && !o->closing) sleep_ns(1000000);
        } else {
            sleep_ns(frames * 1000000000ull / (uint64_t)o->rate);
        }
        pthread_mutex_lock(&o->lock);
        if (o->nq && o->q[0].tag == p.tag) {   /* not flushed meanwhile */
            memmove(o->q, o->q + 1, sizeof *o->q * (size_t)--o->nq);
            if (o->nrel < QMAX) o->released[o->nrel++] = p.tag;
            o->played += frames;
            runtime_event_signal(o->event);
        }
    }
    pthread_mutex_unlock(&o->lock);
    return NULL;
}

static void out_close(void *state) {
    AudioOut *o = state;
    pthread_mutex_lock(&o->lock); o->closing = 1; pthread_cond_broadcast(&o->cv); pthread_mutex_unlock(&o->lock);
    pthread_join(o->thread, NULL);
    if (o->stream) SDL_DestroyAudioStream(o->stream);
    free(o);
}

static void out_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    AudioOut *o = s->state;
    switch (rq->cmd) {
    case 0: { uint32_t st = o->started ? 0 : 1; IPC_OUT(rs, st); return; }   /* AudioOutState: Started 0, Stopped 1 */
    case 1: pthread_mutex_lock(&o->lock); o->started = 1; pthread_cond_broadcast(&o->cv); pthread_mutex_unlock(&o->lock); return;
    case 2: pthread_mutex_lock(&o->lock); o->started = 0; pthread_mutex_unlock(&o->lock); return;
    case 3: case 7: {
        uint64_t tag = IPC_ARG(rq, uint64_t, 0);
        IpcBuffer b = pick(rq->a, rq->na, rq->x, rq->nx);
        const AudioOutBuffer *ab = b.size >= sizeof *ab ? ipc_guest(b.addr, sizeof *ab) : NULL;
        if (!ab || !ab->data_size) { rs->result = R_INVALID; return; }
        pthread_mutex_lock(&o->lock);
        if (o->nq == QMAX) { pthread_mutex_unlock(&o->lock); rs->result = R_INVALID; return; }
        o->q[o->nq++] = (Pending){tag, ab->sample_buffer + ab->data_offset, ab->data_size};
        pthread_cond_broadcast(&o->cv);
        pthread_mutex_unlock(&o->lock);
        return;
    }
    case 4: rs->copy[rs->ncopy++] = runtime_event_readable(o->event); return;
    case 5: case 8: {
        IpcBuffer b = pick(rq->b, rq->nb, rq->c, rq->nc);
        uint64_t *out = b.size ? ipc_guest(b.addr, b.size) : NULL;
        uint32_t n = 0, max = (uint32_t)(b.size / 8);
        pthread_mutex_lock(&o->lock);
        while (out && n < max && n < (uint32_t)o->nrel) { out[n] = o->released[n]; n++; }
        memmove(o->released, o->released + n, sizeof *o->released * (size_t)(o->nrel - (int)n)); o->nrel -= (int)n;
        pthread_mutex_unlock(&o->lock);
        if (out && n < max) out[n] = 0;
        if (b.size && !(rq->nb && rq->b[0].size)) rs->xout[rs->nxout++] = (IpcBuffer){b.addr, b.size, 0};
        IPC_OUT(rs, n);
        return;
    }
    case 6: {
        uint64_t tag = IPC_ARG(rq, uint64_t, 0);
        uint8_t has = 0;
        pthread_mutex_lock(&o->lock);
        for (int i = 0; i < o->nq; i++) if (o->q[i].tag == tag) has = 1;
        pthread_mutex_unlock(&o->lock);
        IPC_OUT(rs, has);
        return;
    }
    case 9: { uint32_t n = (uint32_t)o->nq; IPC_OUT(rs, n); return; }
    case 10: { uint64_t n = o->played; IPC_OUT(rs, n); return; }
    case 11: {
        pthread_mutex_lock(&o->lock);
        for (int i = 0; i < o->nq && o->nrel < QMAX; i++) o->released[o->nrel++] = o->q[i].tag;
        o->nq = 0;
        runtime_event_signal(o->event);
        pthread_mutex_unlock(&o->lock);
        uint8_t ok = 1; IPC_OUT(rs, ok);
        return;
    }
    case 12: o->volume = IPC_ARG(rq, float, 0); if (o->stream) SDL_SetAudioStreamGain(o->stream, o->volume); return;
    case 13: IPC_OUT(rs, o->volume); return;
    default: ipc_unimplemented(s, rq);
    }
}

static void manager_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: case 2: {
        IpcBuffer b = pick(rq->b, rq->nb, rq->c, rq->nc);
        uint32_t n = 0;
        if (b.size >= 0x100) { char *name = ipc_guest(b.addr, 0x100); memset(name, 0, 0x100); strcpy(name, "DeviceOut"); n = 1; }
        if (b.size && !(rq->nb && rq->b[0].size)) rs->xout[rs->nxout++] = (IpcBuffer){b.addr, b.size, 0};
        IPC_OUT(rs, n);
        return;
    }
    case 1: case 3: {
        uint32_t rate = IPC_ARG(rq, uint32_t, 0);
        uint16_t channels = IPC_ARG(rq, uint16_t, 4);
        if (!rate) rate = 48000;
        if (channels != 2 && channels != 6) channels = 2;
        AudioOut *o = calloc(1, sizeof *o);
        if (!o) runtime_fail("audio out allocation");
        pthread_mutex_init(&o->lock, NULL); pthread_cond_init(&o->cv, NULL);
        o->rate = (int)rate; o->channels = channels; o->volume = 1.0f; o->event = runtime_event_new();
        if (SDL_WasInit(SDL_INIT_AUDIO)) {
            SDL_AudioSpec spec = {SDL_AUDIO_S16, channels, (int)rate};
            o->stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, NULL, NULL);
            if (o->stream) SDL_ResumeAudioStreamDevice(o->stream);
            else fprintf(stderr, "[totk-audio] [warning] audio out: no output device (%s): paced without sound\n", SDL_GetError());
        }
        if (pthread_create(&o->thread, NULL, player, o)) runtime_fail("audio out thread");
        fprintf(stderr, "[totk-audio] audio out opened: %u Hz, %u channels, s16 (%s)\n", rate, channels, o->stream ? "SDL" : "no device");
        IpcBuffer nb = pick(rq->b, rq->nb, rq->c, rq->nc);
        if (nb.size >= 0x100) { char *name = ipc_guest(nb.addr, 0x100); memset(name, 0, 0x100); strcpy(name, "DeviceOut"); }
        if (nb.size && !(rq->nb && rq->b[0].size)) rs->xout[rs->nxout++] = (IpcBuffer){nb.addr, nb.size, 0};
        struct { uint32_t rate, channels, format, state; } params = {rate, channels, 2, 1};
        IPC_OUT(rs, params);
        ipc_out_object(s, rs, "IAudioOut", out_handler, o, out_close);
        return;
    }
    default: ipc_unimplemented(s, rq);
    }
}

void runtime_audout_register(void) { runtime_ipc_register("audout:u", manager_handler, NULL, NULL); }
