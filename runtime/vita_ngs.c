#include "vita_ngs.h"
#ifdef VX_ENABLE_AUDIODEC
#include "vita_audiodec.h"
#endif

#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Firmware 3.60 user-mode ABI. Host objects use opaque tokens; the locked
   parameter blocks live in the guest-provided rack allocation. */
enum {
    NGS_PARAM = 0x804a0002u, NGS_ALIGN = 0x804a0003u, NGS_UNSUPPORTED = 0x804a0004u,
    NGS_DEPENDENCY = 0x804a0005u, NGS_CAPACITY = 0x804a0006u, NGS_MODULE = 0x804a0007u,
    NGS_LOCKED = 0x804a0008u, NGS_RANGE = 0x804a0009u, NGS_DEFINITION = 0x804a000au,
    NGS_SYSTEM = 0x804a000bu, NGS_HANDLE = 0x804a000cu, NGS_SIZE = 0x804a000du,
    NGS_PATCH = 0x804a000eu, NGS_INTERFACE = 0x804a000fu, NGS_STATE = 0x804a0010u,
    NGS_MEMORY = 0x804a0011u, NGS_DECODE = 0x804a0012u, NGS_BUFFER = 0x804a0013u,
    NGS_MAX_SYSTEMS = 8, NGS_MAX_RACKS = 64, NGS_MAX_VOICES = 256, NGS_MAX_PATCHES = 2048,
    NGS_MAX_GRAIN = 512, NGS_MAX_EVENTS = NGS_MAX_VOICES * 3,
    NGS_PCM = 1, NGS_AT9, NGS_MIXER, NGS_MASTER, NGS_PAUSER, NGS_DEF_BASE = 0x77001000,
    NGS_PLAYER_MODULE = 0x5ce6, NGS_AT9_MODULE = 0x5caa,
    NGS_PCM_PARAM_BYTES = 84, NGS_AT9_PARAM_BYTES = 96,
    NGS_PAUSER_MODULE = 0x5ce5, NGS_PAUSER_ID = 0x01015ce5, NGS_PAUSER_BYTES = 16,
    NGS_ACTIVE = 1, NGS_PAUSED = 0x20, NGS_KEYOFF = 0x40
};

typedef struct {
    uint8_t *data;
    size_t size;
    uint32_t base;
} guest_memory;
typedef struct {
    uint32_t handle, address, size, max_racks, max_voices, grain, owner, locks, flags;
    float *mix;
} ngs_system;
typedef struct ngs_rack ngs_rack;
typedef struct {
    uint32_t handle, address, initialized, state, bypass, locked, updates;
    uint32_t pause_in, pause_out;
    float pause_gain;
    uint32_t finish, finish_user, module_callback, module_user;
    uint32_t sample_bytes, total_bytes, samples, total_samples, offset;
    int buffer, loops, lead;
    double fraction;
    ngs_rack *rack;
    uint8_t params[NGS_AT9_PARAM_BYTES];
#ifdef VX_ENABLE_AUDIODEC
    struct {
        vx_atrac9 *decoder;
        uint32_t config, channels, packet_bytes, packet_frames, cursor, end;
        int16_t pcm[2048];
    } at9;
#endif
    int16_t rendered[NGS_MAX_GRAIN * 2];
} ngs_voice;
struct ngs_rack {
    uint32_t handle, address, size, kind, channels, inputs, outputs, slots, count, user;
    ngs_system *system;
    ngs_voice *voices;
};
typedef struct {
    uint32_t handle, output, slot, input;
    ngs_voice *source, *destination;
    float gains[2][2];
} ngs_patch;
typedef struct {
    uint32_t owner;
    vx_ngs_event event;
} ngs_queued_event;
typedef struct {
    uint32_t address, bytes;
    int16_t loops, next;
} player_buffer;

static _Thread_local ngs_system systems[NGS_MAX_SYSTEMS];
static _Thread_local ngs_rack racks[NGS_MAX_RACKS];
static _Thread_local ngs_patch patches[NGS_MAX_PATCHES];
static _Thread_local ngs_queued_event events[NGS_MAX_EVENTS];
static _Thread_local uint32_t event_count, serial;

extern int vn_guest_write_allowed(const uint8_t *, size_t) __attribute__((weak_import));
extern void vx_guest_memory_written(void);

static uint8_t *span(guest_memory memory, uint32_t address, size_t bytes) {
    if (!address || address < memory.base) return NULL;
    uint32_t offset = address - memory.base;
    if (offset > memory.size || bytes > memory.size - offset || address + (uint64_t)bytes > UINT64_C(0x100000000))
        return NULL;
    return memory.data + offset;
}

static uint8_t *output(guest_memory memory, uint32_t address, size_t bytes) {
    uint8_t *ptr = span(memory, address, bytes);
    return ptr && (!vn_guest_write_allowed || vn_guest_write_allowed(ptr, bytes)) ? ptr : NULL;
}

static void copy_out(void *dest, const void *source, size_t size) {
    vx_guest_memory_written();
    memcpy(dest, source, size);
}

static uint32_t word(const void *source) {
    uint32_t value;
    memcpy(&value, source, sizeof value);
    return value;
}

static float f32(const void *source) {
    float value;
    memcpy(&value, source, sizeof value);
    return value;
}

static uint32_t handle(void) {
    if (++serial == 0x0fffffffu) return 0;
    return 0x60000000u | serial;
}

static ngs_system *system_for(uint32_t token) {
    if (token) for (size_t i = 0; i < NGS_MAX_SYSTEMS; i++)
        if (systems[i].handle == token) return &systems[i];
    return NULL;
}

static ngs_rack *rack_for(uint32_t token) {
    if (token) for (size_t i = 0; i < NGS_MAX_RACKS; i++)
        if (racks[i].handle == token) return &racks[i];
    return NULL;
}

static ngs_voice *voice_for(uint32_t token) {
    if (token) for (size_t i = 0; i < NGS_MAX_RACKS; i++)
        for (uint32_t j = 0; j < racks[i].count; j++)
            if (racks[i].voices[j].handle == token) return &racks[i].voices[j];
    return NULL;
}

static ngs_patch *patch_for(uint32_t token) {
    if (token) for (size_t i = 0; i < NGS_MAX_PATCHES; i++)
        if (patches[i].handle == token) return &patches[i];
    return NULL;
}

static int overlaps(uint32_t address, uint32_t bytes, uint32_t other, uint32_t length) {
    return (uint64_t)address + bytes > other && (uint64_t)other + length > address;
}

static int storage_available(uint32_t address, uint32_t bytes) {
    for (size_t i = 0; i < NGS_MAX_SYSTEMS; i++)
        if (systems[i].handle && overlaps(address, bytes, systems[i].address, systems[i].size)) return 0;
    for (size_t i = 0; i < NGS_MAX_RACKS; i++)
        if (racks[i].handle && overlaps(address, bytes, racks[i].address, racks[i].size)) return 0;
    return 1;
}

static uint32_t system_size(const uint8_t *params) {
    if (!params) return 0;
    uint32_t racks_limit = word(params), voices = word(params+4), grain = word(params+8);
    if (!racks_limit || racks_limit > NGS_MAX_RACKS || !voices || voices > NGS_MAX_VOICES ||
        !grain || grain > NGS_MAX_GRAIN || (grain & 63) || word(params+12) != 48000 ||
        (int32_t)word(params+16) < 0) return 0;
    return 64;
}

static uint32_t rack_size(const uint8_t *desc, const ngs_system *system) {
    if (!desc) return 0;
    uint32_t kind = word(desc) - NGS_DEF_BASE, count = word(desc+4), channels = word(desc+8);
    uint32_t inputs = word(desc+12), slots = word(desc+16);
    if (kind < NGS_PCM || kind > NGS_PAUSER || !count || count > system->max_voices ||
        !channels || channels > 2 || inputs > NGS_MAX_PATCHES || slots > NGS_MAX_PATCHES ||
        ((kind == NGS_MASTER || kind == NGS_MIXER || kind == NGS_PAUSER) && !inputs)) return 0;
    return 64 + count * (kind == NGS_AT9 ? 112 : 96);
}

static void unpatch(ngs_voice *voice) {
    for (size_t i = 0; i < NGS_MAX_PATCHES; i++)
        if (patches[i].source == voice || patches[i].destination == voice) patches[i] = (ngs_patch){0};
}

static void release_rack(ngs_rack *rack) {
    for (uint32_t i = 0; i < rack->count; i++) {
        unpatch(&rack->voices[i]);
#ifdef VX_ENABLE_AUDIODEC
        vx_atrac9_destroy(rack->voices[i].at9.decoder);
#endif
    }
    free(rack->voices);
    *rack = (ngs_rack){0};
}

void vx_ngs_shutdown(void) {
    for (size_t i = 0; i < NGS_MAX_RACKS; i++) if (racks[i].handle) release_rack(&racks[i]);
    for (size_t i = 0; i < NGS_MAX_SYSTEMS; i++) {
        free(systems[i].mix);
        systems[i] = (ngs_system){0};
    }
    event_count = 0;
}

int vx_ngs_pop_event(uint32_t owner, vx_ngs_event *event) {
    for (uint32_t i = 0; i < event_count; i++) if (events[i].owner == owner) {
        *event = events[i].event;
        event_count--;
        memmove(events+i, events+i+1, (event_count-i)*sizeof *events);
        return 1;
    }
    return 0;
}

static int emit(uint32_t owner, uint32_t entry, uint32_t voice, uint32_t rack,
                uint32_t module, uint32_t reason, uint32_t detail, uint32_t address, uint32_t data) {
    if (!entry) return 1;
    if (!owner || event_count == NGS_MAX_EVENTS) return 0;
    events[event_count++] = (ngs_queued_event){owner, {entry, {voice, rack, module, reason, detail, address, data}}};
    return 1;
}

static player_buffer buffer_for(const ngs_voice *voice) {
    player_buffer buffer;
    memcpy(&buffer, voice->params + 8 + 12 * voice->buffer, sizeof buffer);
    return buffer;
}

static size_t player_params_size(const ngs_voice *voice) {
    return voice->rack->kind == NGS_AT9 ? NGS_AT9_PARAM_BYTES :
           voice->rack->kind == NGS_PCM ? NGS_PCM_PARAM_BYTES : 0;
}

static uint32_t player_module(const ngs_voice *voice) {
    return voice->rack->kind == NGS_AT9 ? NGS_AT9_MODULE : NGS_PLAYER_MODULE;
}

static void defaults(ngs_voice *voice) {
    memset(voice->params, 0, sizeof voice->params);
    voice->pause_in = voice->pause_out = 0;
    voice->pause_gain = 1;
    uint32_t bytes = (uint32_t)player_params_size(voice);
    if (!bytes) return;
    int at9 = voice->rack->kind == NGS_AT9;
    unsigned rate_offset = at9 ? 72 : 56;
    unsigned channel_offset = at9 ? 88 : 76;
    unsigned buffer_stride = at9 ? 16 : 12;
    float rate = 48000, scalar = 1;
    memcpy(voice->params+4, &bytes, 4);
    memcpy(voice->params+rate_offset, &rate, 4);
    memcpy(voice->params+rate_offset+4, &scalar, 4);
    voice->params[channel_offset] = voice->rack->channels;
    voice->params[channel_offset+2] = 1;
    for (unsigned i = 0; i < 4; i++) memset(voice->params+18+buffer_stride*i, 0xff, 2);
#ifdef VX_ENABLE_AUDIODEC
    vx_atrac9_destroy(voice->at9.decoder);
    memset(&voice->at9, 0, sizeof voice->at9);
#endif
}

static uint32_t validate_player(const uint8_t *params) {
    float rate = f32(params+56), scalar = f32(params+60);
    if (params[79] != 0) return NGS_UNSUPPORTED;
    if (params[76] < 1 || params[76] > 2 || params[81] > 3 ||
        (int32_t)word(params+64) < 0 || (int32_t)word(params+68) < 0 || (int32_t)word(params+72) < 0 ||
        !isfinite(rate) || rate < 1 || rate > 192000 || !isfinite(scalar) || scalar <= 0 || scalar > 8)
        return NGS_RANGE;
    for (size_t i = 0; i < 4; i++) {
        player_buffer buffer;
        memcpy(&buffer, params+8+i*12, sizeof buffer);
        if (buffer.bytes > INT32_MAX || buffer.loops < -1 || buffer.next < -1 || buffer.next > 3 ||
            buffer.bytes % (params[76]*2)) return NGS_RANGE;
    }
    return 0;
}

static uint32_t pcm_finish(ngs_voice *voice, uint32_t owner) {
    voice->state = 0;
    uint32_t v = voice->handle, r = voice->rack->handle;
    if (!emit(owner, voice->module_callback, v, r, player_module(voice), 0, 0, 0, voice->module_user) ||
        !emit(owner, voice->finish, v, r, 0, 0, 0, 0, voice->finish_user)) return NGS_CAPACITY;
    return 0;
}

static uint32_t pcm_render(ngs_voice *voice, float *dest, uint32_t grain, guest_memory memory, uint32_t owner) {
    if (voice->state & NGS_KEYOFF) return pcm_finish(voice, owner);
    uint32_t input_channels = voice->params[76], frame_bytes = input_channels * 2;
    uint32_t limit = word(voice->params+68);
    double step = (double)f32(voice->params+56) * f32(voice->params+60) / 48000;
    for (uint32_t frame = 0; frame < grain; frame++) {
        if (voice->lead) {
            voice->lead--;
            continue;
        }
        if (limit && voice->samples >= limit) return pcm_finish(voice, owner);
        player_buffer buffer = buffer_for(voice);
        for (unsigned crossed = 0; voice->offset >= buffer.bytes; crossed++) {
            if (crossed == 4 || !buffer.address || !buffer.bytes) return pcm_finish(voice, owner);
            if (buffer.loops == -1 || voice->loops < buffer.loops) {
                if (buffer.loops != -1) voice->loops++;
                voice->offset -= buffer.bytes;
                if (!emit(owner, voice->module_callback, voice->handle, voice->rack->handle,
                          NGS_PLAYER_MODULE, 2, voice->buffer, buffer.address, voice->module_user))
                    return NGS_CAPACITY;
            } else if (buffer.next >= 0) {
                voice->offset -= buffer.bytes;
                voice->buffer = buffer.next;
                voice->loops = 0;
                buffer = buffer_for(voice);
                if (!emit(owner, voice->module_callback, voice->handle, voice->rack->handle,
                          NGS_PLAYER_MODULE, 1, voice->buffer, buffer.address, voice->module_user))
                    return NGS_CAPACITY;
            } else return pcm_finish(voice, owner);
        }
        if (buffer.address > UINT32_MAX-voice->offset || buffer.bytes-voice->offset < frame_bytes)
            return NGS_BUFFER;
        const uint8_t *sample = span(memory, buffer.address + voice->offset, frame_bytes);
        if (!sample) return NGS_BUFFER;
        for (uint32_t ch = 0; ch < voice->rack->channels; ch++) {
            int16_t value;
            uint32_t index = input_channels == 1 ? 0 : voice->params[77+ch];
            if (index < input_channels) {
                memcpy(&value, sample+2*index, 2);
                dest[frame*2+ch] += (float)value / 32768;
            }
        }
        voice->samples++;
        voice->total_samples++;
        voice->fraction += step;
        uint32_t advance = (uint32_t)voice->fraction;
        voice->fraction -= advance;
        voice->offset += frame_bytes * advance;
        voice->sample_bytes += frame_bytes * advance;
        voice->total_bytes += frame_bytes * advance;
    }
    return 0;
}

#ifdef VX_ENABLE_AUDIODEC
/* Four 16-byte compressed-buffer records precede the rate, trim, channel map
   and packed config fields of the 96-byte NGS ATRAC9 parameter block. */
static player_buffer at9_buffer(const ngs_voice *voice) {
    player_buffer value;
    memcpy(&value, voice->params + 8 + 16 * voice->buffer, sizeof value);
    return value;
}

static uint32_t validate_at9(const uint8_t *p) {
    float frequency = f32(p+72), scalar = f32(p+76);
    if (!isfinite(frequency) || frequency < 1 || frequency > 192000 ||
        !isfinite(scalar) || scalar <= 0 || scalar > 8 ||
        word(p+80) > INT32_MAX || word(p+84) > INT32_MAX ||
        p[88] < 1 || p[88] > 2 || p[89] > 1 || p[90] > 1 ||
        (p[92] && p[92] != 0xfe))
        return NGS_RANGE;
    for (unsigned i = 0; i < 4; i++) {
        player_buffer buffer;
        memcpy(&buffer, p+8+16*i, sizeof buffer);
        if (buffer.bytes > INT32_MAX || buffer.loops < -1 ||
            buffer.next < -1 || buffer.next > 3) return NGS_RANGE;
    }
    return 0;
}

static uint32_t at9_advance_buffer(ngs_voice *voice, player_buffer *buffer, uint32_t owner) {
    unsigned reason, detail;
    if (buffer->loops == -1 || voice->loops < buffer->loops) {
        if (buffer->loops != -1) voice->loops++;
        reason = 4;
        detail = (uint32_t)voice->loops;
    } else {
        if (buffer->next < 0) {
            voice->buffer = -1;
            return pcm_finish(voice, owner);
        }
        reason = 1;
        detail = (uint32_t)voice->buffer;
        voice->buffer = buffer->next;
        voice->loops = 0;
        *buffer = at9_buffer(voice);
    }
    voice->offset = 0;
    if (!buffer->address || !buffer->bytes) {
        voice->buffer = -1;
        return pcm_finish(voice, owner);
    }
    return emit(owner, voice->module_callback, voice->handle, voice->rack->handle,
                NGS_AT9_MODULE, reason, detail, buffer->address, voice->module_user) ? 0 : NGS_CAPACITY;
}

static uint32_t at9_load_packet(ngs_voice *voice, guest_memory memory, uint32_t owner) {
    uint8_t packet[8192];
    const uint32_t bytes = voice->at9.packet_bytes;
    if (!bytes || bytes > sizeof packet) return NGS_DECODE;
    uint32_t filled = 0, initial_offset = voice->offset;
    int initial_buffer = voice->buffer;
    player_buffer buffer = at9_buffer(voice);
    for (unsigned fragments = 0; filled < bytes; fragments++) {
        if (!buffer.address || !buffer.bytes) return pcm_finish(voice, owner);
        if (fragments > 4) return NGS_BUFFER;
        if (voice->offset >= buffer.bytes) {
            uint32_t status = at9_advance_buffer(voice, &buffer, owner);
            if (status || !voice->state) return status;
            if (!filled) {
                initial_offset = voice->offset;
                initial_buffer = voice->buffer;
            } else {
                initial_buffer = -1;
            }
        }
        uint32_t take = buffer.bytes - voice->offset;
        if (take > bytes - filled) take = bytes - filled;
        if (buffer.address > UINT32_MAX - voice->offset) return NGS_BUFFER;
        const uint8_t *input = span(memory, buffer.address + voice->offset, take);
        if (!input) return NGS_BUFFER;
        memcpy(packet+filled, input, take);
        filled += take;
        voice->offset += take;
    }
    int elements = vx_atrac9_decode(voice->at9.decoder, packet, bytes, voice->at9.pcm,
                                   sizeof voice->at9.pcm / sizeof *voice->at9.pcm);
    if (elements <= 0 || elements % voice->at9.channels) {
        emit(owner, voice->module_callback, voice->handle, voice->rack->handle,
             NGS_AT9_MODULE, 3, initial_offset, buffer.address, voice->module_user);
        return NGS_DECODE;
    }
    voice->sample_bytes += bytes;
    voice->total_bytes += bytes;
    voice->at9.cursor = 0;
    voice->at9.end = (uint32_t)elements / voice->at9.channels;
    if (initial_buffer == voice->buffer) {
        uint16_t trim[2];
        memcpy(trim, voice->params+20+16*voice->buffer, sizeof trim);
        uint32_t before = (initial_offset / bytes) * voice->at9.packet_frames;
        uint32_t after = ((buffer.bytes - voice->offset) / bytes) * voice->at9.packet_frames;
        if (trim[0] > before) {
            uint32_t skip = trim[0]-before;
            voice->at9.cursor = skip > voice->at9.end ? voice->at9.end : skip;
        }
        if (trim[1] > after) {
            uint32_t skip = trim[1]-after;
            voice->at9.end -= skip > voice->at9.end ? voice->at9.end : skip;
        }
    }
    return 0;
}

static uint32_t at9_render(ngs_voice *voice, float *dest, uint32_t grain,
                           guest_memory memory, uint32_t owner) {
    if (voice->state & NGS_KEYOFF) return pcm_finish(voice, owner);
    uint32_t config = word(voice->params+92);
    if (!voice->at9.decoder || config != voice->at9.config) {
        vx_atrac9_destroy(voice->at9.decoder);
        voice->at9.config = config;
        voice->at9.cursor = voice->at9.end = 0;
        voice->at9.decoder = vx_atrac9_create(voice->params+92, &voice->at9.channels, NULL,
                                             &voice->at9.packet_bytes, &voice->at9.packet_frames);
        if (!voice->at9.decoder) return NGS_DECODE;
    }
    if (voice->at9.channels != voice->params[88]) return NGS_RANGE;
    double step = (double)f32(voice->params+72) * f32(voice->params+76) / 48000;
    uint32_t limit = word(voice->params+84);
    for (uint32_t frame = 0; frame < grain; frame++) {
        if (voice->lead) {
            voice->lead--;
            continue;
        }
        if (limit && voice->samples >= limit) return pcm_finish(voice, owner);
        for (unsigned skipped = 0; voice->at9.cursor >= voice->at9.end; skipped++) {
            if (skipped == 2048) return NGS_RANGE;
            uint32_t previous_end = voice->at9.end;
            uint32_t remainder = voice->at9.cursor - previous_end;
            uint32_t result = at9_load_packet(voice, memory, owner);
            if (result || !voice->state) return result;
            voice->at9.cursor += remainder;
        }
        for (unsigned ch = 0; ch < voice->rack->channels; ch++) {
            unsigned input = voice->at9.channels == 1 ? 0 : voice->params[89+ch];
            dest[frame*2+ch] += (float)voice->at9.pcm[voice->at9.cursor * voice->at9.channels + input] / 32768;
        }
        voice->samples++;
        voice->total_samples++;
        voice->fraction += step;
        uint32_t advance = (uint32_t)voice->fraction;
        voice->fraction -= advance;
        voice->at9.cursor += advance;
    }
    return 0;
}
#endif

static uint32_t pauser_index(const ngs_voice *voice) {
    if (voice->rack->kind == NGS_AT9) return 3;
    if (voice->rack->kind == NGS_PAUSER) return 1;
    return UINT32_MAX;
}

static void pauser_render(ngs_voice *voice, float *audio, uint32_t grain) {
    uint32_t module = pauser_index(voice);
    if (module == UINT32_MAX || (voice->bypass & (1u << module))) return;
    int paused = (voice->state & NGS_PAUSED) != 0;
    uint32_t duration = paused ? voice->pause_out : voice->pause_in;
    float delta = duration ? 1.f / (float)duration : 1.f;
    for (uint32_t frame = 0; frame < grain; frame++) {
        float target = paused ? 0.f : 1.f;
        voice->pause_gain = paused ? fmaxf(target,voice->pause_gain-delta)
                                   : fminf(target,voice->pause_gain+delta);
        audio[frame*2] *= voice->pause_gain;
        audio[frame*2+1] *= voice->pause_gain;
    }
}

static size_t graph(ngs_system *system, ngs_voice *list[NGS_MAX_VOICES]) {
    size_t count = 0;
    for (size_t i = 0; i < NGS_MAX_RACKS; i++) if (racks[i].system == system)
        for (uint32_t j = 0; j < racks[i].count; j++) list[count++] = &racks[i].voices[j];
    return count;
}

static int voice_index(ngs_voice *const *list, size_t count, ngs_voice *voice) {
    for (size_t i = 0; i < count; i++) if (list[i] == voice) return (int)i;
    return -1;
}

static uint32_t update(ngs_system *system, guest_memory memory, uint32_t owner) {
    ngs_voice *list[NGS_MAX_VOICES];
    uint32_t indegree[NGS_MAX_VOICES] = {0};
    int source[NGS_MAX_PATCHES], dest[NGS_MAX_PATCHES];
    uint16_t queue[NGS_MAX_VOICES];
    size_t begin = 0, end = 0, count = graph(system, list);
    uint32_t grain = system->grain;
    size_t samples = grain * 2;
    memset(system->mix, 0, count * samples * sizeof(float));
    for (size_t i = 0; i < NGS_MAX_PATCHES; i++) {
        source[i] = dest[i] = -1;
        if (patches[i].handle && patches[i].source->rack->system == system) {
            source[i] = voice_index(list, count, patches[i].source);
            dest[i] = voice_index(list, count, patches[i].destination);
            indegree[dest[i]]++;
        }
    }
    for (size_t i = 0; i < count; i++) if (!indegree[i]) queue[end++] = (uint16_t)i;
    uint32_t result = 0;
    while (begin < end) {
        int index = queue[begin++];
        ngs_voice *voice = list[index];
        float *audio = system->mix + index*samples;
        int fading = voice->rack->kind == NGS_AT9 && voice->pause_out &&
                     voice->pause_gain > 0 && !(voice->bypass & (1u << 3));
        if ((voice->state & NGS_ACTIVE) && (!(voice->state & NGS_PAUSED) || fading)) {
            voice->updates++;
            if (voice->rack->kind == NGS_PCM && !voice->bypass) {
                uint32_t status = pcm_render(voice, audio, grain, memory, owner);
                if (status && !result) result = status;
            }
#ifdef VX_ENABLE_AUDIODEC
            if (voice->rack->kind == NGS_AT9 && !(voice->bypass & 1u)) {
                uint32_t status = at9_render(voice, audio, grain, memory, owner);
                if (status && !result) result = status;
            }
#endif
        } else if (player_params_size(voice) || (voice->state & NGS_PAUSED && voice->rack->kind != NGS_PAUSER)) {
            memset(audio, 0, samples*sizeof *audio);
        }
        pauser_render(voice, audio, grain);
        if (voice->rack->kind == NGS_MASTER) {
            for (size_t j = 0; j < samples; j++) {
                float sample = fminf(32767, fmaxf(-32768, audio[j]*32768));
                voice->rendered[j] = (int16_t)lrintf(sample);
            }
        }
        for (size_t i = 0; i < NGS_MAX_PATCHES; i++) if (source[i] == index) {
            ngs_patch *patch = &patches[i];
            float *target = system->mix + dest[i]*samples;
            for (uint32_t frame = 0; frame < grain; frame++)
                for (uint32_t out = 0; out < voice->rack->channels; out++)
                    for (uint32_t in = 0; in < patch->destination->rack->channels; in++)
                        target[frame*2+in] += audio[frame*2+out] * patch->gains[out][in];
            if (!--indegree[dest[i]]) queue[end++] = (uint16_t)dest[i];
        }
    }
    return begin == count ? result : NGS_DEPENDENCY;
}

static ngs_patch *find_slot(ngs_voice *voice, uint32_t out, uint32_t slot) {
    for (size_t i = 0; i < NGS_MAX_PATCHES; i++)
        if (patches[i].source == voice && patches[i].output == out && patches[i].slot == slot) return &patches[i];
    return NULL;
}

static int reaches(ngs_voice *origin, ngs_voice *target) {
    ngs_voice *pending[NGS_MAX_VOICES] = {origin};
    size_t count = 1;
    for (size_t i = 0; i < count; i++) {
        if (pending[i] == target) return 1;
        for (size_t j = 0; j < NGS_MAX_PATCHES; j++) if (patches[j].source == pending[i]) {
            ngs_voice *next = patches[j].destination;
            if (voice_index(pending,count,next) == -1) pending[count++] = next;
        }
    }
    return 0;
}

static uint32_t create_system(uint32_t address, uint32_t capacity, uint32_t params_address,
                              uint32_t result_address, guest_memory memory) {
    const uint8_t *params = span(memory, params_address, 20);
    uint8_t *dest = output(memory, result_address, 4);
    uint32_t needed = system_size(params);
    if (!needed || !dest || !address) return NGS_PARAM;
    if (address & 15) return NGS_ALIGN;
    if (capacity < needed || !output(memory, address, capacity) || !storage_available(address, capacity) ||
        overlaps(address, capacity, result_address, 4)) return NGS_BUFFER;
    for (size_t i = 0; i < NGS_MAX_SYSTEMS; i++) if (!systems[i].handle) {
        uint32_t v = word(params+4), grain = word(params+8), token = handle();
        float *mix = calloc(v * grain * 2, sizeof *mix);
        if (!mix || !token) {
            free(mix);
            return NGS_MEMORY;
        }
        systems[i] = (ngs_system){.handle=token,.address=address,.size=capacity,.max_racks=word(params),
                                 .max_voices=v,.grain=grain,.flags=1,.mix=mix};
        copy_out(dest, &token, 4);
        return 0;
    }
    return NGS_CAPACITY;
}

static uint32_t create_rack(ngs_system *system, const uint8_t *info, const uint8_t *desc,
                            uint32_t result_address, guest_memory memory) {
    uint8_t *dest = output(memory, result_address, 4);
    uint32_t needed = rack_size(desc,system);
    if (!needed || !dest || !info) return NGS_PARAM;
    uint32_t address = word(info), capacity = word(info+4);
    if (address & 15) return NGS_ALIGN;
    if (capacity < needed || !output(memory,address,capacity) || !storage_available(address,capacity) ||
        overlaps(address,capacity,result_address,4)) return NGS_BUFFER;
    size_t count = 0, used = 0;
    ngs_rack *rack = NULL;
    for (size_t i = 0; i < NGS_MAX_RACKS; i++) {
        if (racks[i].system == system) {
            count++;
            used += racks[i].count;
        } else if (!racks[i].handle && !rack) rack = &racks[i];
    }
    uint32_t voices = word(desc+4), type = word(desc) - NGS_DEF_BASE;
    if (!rack || count == system->max_racks || used + voices > system->max_voices) return NGS_CAPACITY;
#ifndef VX_ENABLE_AUDIODEC
    if (type == NGS_AT9) return NGS_UNSUPPORTED;
#endif
    ngs_voice *entries = calloc(voices, sizeof *entries);
    uint32_t token = handle();
    if (!entries || !token) {
        free(entries);
        return NGS_MEMORY;
    }
    *rack = (ngs_rack){token,address,capacity,type,word(desc+8),word(desc+12),
                      type == NGS_MASTER ? 0 : (type == NGS_MIXER || type == NGS_PAUSER) ? 1 : 2,
                      word(desc+16),voices,word(desc+20),system,entries};
    for (uint32_t i = 0; i < voices; i++) {
        entries[i] = (ngs_voice){.handle=handle(),.address=address+64+i*(type == NGS_AT9 ? 112 : 96),.initialized=1,.rack=rack};
        if (!entries[i].handle) {
            release_rack(rack);
            return NGS_MEMORY;
        }
        defaults(&entries[i]);
    }
    copy_out(dest,&token,4);
    return 0;
}

static uint32_t patch_create(const uint8_t *desc, uint8_t *result) {
    if (!desc || !result) return NGS_PARAM;
    ngs_voice *from = voice_for(word(desc)), *to = voice_for(word(desc+12));
    uint32_t out = word(desc+4), slot = word(desc+8), in = word(desc+16);
    if (!from || !to) return NGS_HANDLE;
    if (from->rack->system != to->rack->system) return NGS_SYSTEM;
    if (out >= from->rack->outputs || in != 0 || !to->rack->inputs ||
        (slot != UINT32_MAX && slot >= from->rack->slots)) return NGS_PARAM;
    if (reaches(to,from)) return NGS_DEPENDENCY;
    ngs_patch *free_slot = NULL;
    unsigned on_input = 0;
    for (size_t i = 0; i < NGS_MAX_PATCHES; i++) {
        if (patches[i].destination == to) on_input++;
        if (!patches[i].handle && !free_slot) free_slot = &patches[i];
    }
    if (!free_slot || on_input >= to->rack->inputs) return NGS_PATCH;
    if (slot == UINT32_MAX) {
        for (slot = 0; slot < from->rack->slots && find_slot(from,out,slot); slot++) {}
        if (slot >= from->rack->slots) return NGS_PATCH;
    } else if (find_slot(from,out,slot)) return NGS_PATCH;
    uint32_t token = handle();
    if (!token) return NGS_CAPACITY;
    *free_slot = (ngs_patch){.handle=token,.output=out,.slot=slot,.input=in,.source=from,.destination=to};
    copy_out(result,&token,4);
    return 0;
}

static uint32_t patch_info(ngs_patch *patch, uint32_t properties, uint32_t delivery, guest_memory memory) {
    if (!patch) return NGS_HANDLE;
    uint8_t *props = output(memory,properties,24), *route = output(memory,delivery,20);
    if ((!properties && !delivery) || (properties && !props) || (delivery && !route)) return NGS_PARAM;
    if (props) {
        uint32_t channels[] = {patch->source->rack->channels, patch->destination->rack->channels};
        copy_out(props,channels,sizeof channels);
        copy_out(props+8,patch->gains,sizeof patch->gains);
    }
    if (route) {
        uint32_t words[] = {patch->source->handle,patch->output,patch->slot,patch->destination->handle,patch->input};
        copy_out(route,words,sizeof words);
    }
    return 0;
}

static uint32_t patch_gain(uint32_t nid, ngs_patch *patch, const uint32_t regs[16], guest_memory memory) {
    if (!patch) return NGS_HANDLE;
    float values[4];
    if (nid == 0xA0F5402D) {
        const uint8_t *source = span(memory,regs[1],sizeof values);
        if (!source) return NGS_PARAM;
        memcpy(values,source,sizeof values);
        for (unsigned i = 0; i < 4; i++) if (!isfinite(values[i])) return NGS_RANGE;
        memcpy(patch->gains,values,sizeof values);
    } else {
        unsigned channel = regs[1], count = regs[3];
        if (channel >= patch->source->rack->channels) return NGS_PARAM;
        if (nid == 0xA3C807BC) {
            float gain = f32(&regs[3]);
            if (regs[2] > 1 || !isfinite(gain)) return NGS_PARAM;
            patch->gains[channel][regs[2]] = gain;
        } else {
            if (!count || count > 2) return NGS_PARAM;
            const uint8_t *source = span(memory,regs[2],count*4);
            if (!source) return NGS_PARAM;
            memcpy(values,source,count*4);
            for (unsigned i = 0; i < count; i++) if (!isfinite(values[i])) return NGS_RANGE;
            memcpy(patch->gains[channel],values,count*4);
        }
    }
    return 0;
}

static uint32_t set_params(ngs_voice *voice, uint32_t module, const uint8_t *params, uint32_t bytes) {
    if (module == pauser_index(voice) && module != UINT32_MAX) {
        if (!params || bytes != NGS_PAUSER_BYTES || word(params+4) != bytes) return NGS_SIZE;
        if (word(params) != NGS_PAUSER_ID) return NGS_INTERFACE;
        if (word(params+8) > 480000 || word(params+12) > 480000) return NGS_RANGE;
        voice->pause_in = word(params+8);
        voice->pause_out = word(params+12);
        return 0;
    }
    size_t expected = player_params_size(voice);
    if (module || !expected) return NGS_MODULE;
    if (!params || bytes != expected || word(params+4) != bytes) return NGS_SIZE;
    uint32_t result = NGS_UNSUPPORTED;
    if (voice->rack->kind == NGS_PCM) result = validate_player(params);
#ifdef VX_ENABLE_AUDIODEC
    else result = validate_at9(params);
#endif
    if (!result) memcpy(voice->params,params,bytes);
    return result;
}

static uint32_t voice_params_block(ngs_voice *voice, const uint32_t regs[16], guest_memory memory) {
    const uint8_t *source = span(memory,regs[1],regs[2]);
    uint8_t *error_out = output(memory,regs[3],4);
    if (!source || (regs[3] && !error_out) || regs[2] > 65536) return NGS_PARAM;
    uint32_t first_error = 0, errors = 0;
    for (uint32_t off = 0; off < regs[2];) {
        uint32_t available = regs[2]-off;
        if (available < 16) {
            errors++;
            first_error = NGS_SIZE;
            break;
        }
        const uint8_t *entry = source+off;
        uint32_t bytes = word(entry+12);
        if (bytes < 8 || bytes > available-8) {
            errors++;
            first_error = NGS_SIZE;
            break;
        }
        uint32_t result = (word(entry+4) != UINT32_MAX && word(entry+4) != 0) ? NGS_PARAM :
                          voice->locked ? NGS_LOCKED : set_params(voice,word(entry),entry+8,bytes);
        if (result) {
            errors++;
            if (!first_error) first_error = result;
        }
        off += 8+bytes;
    }
    if (error_out) copy_out(error_out,&errors,4);
    return first_error;
}

static uint32_t voice_import(uint32_t nid, ngs_voice *voice, const uint32_t r[16],
                             guest_memory memory, uint32_t owner) {
    if (!voice) return NGS_HANDLE;
    ngs_rack *rack = voice->rack;
    uint32_t module_count = rack->kind == NGS_AT9 ? 6 :
                            (rack->kind == NGS_MASTER || rack->kind == NGS_PAUSER) ? 2 : 1;
    uint32_t parameter_size = (uint32_t)player_params_size(voice);
    uint32_t pause_module = pauser_index(voice);
    int set_pauser = pause_module != UINT32_MAX && r[1] == pause_module;
    uint32_t param_address = voice->address + (set_pauser && rack->kind == NGS_AT9 ? 96 : 0);
    uint32_t param_size = set_pauser ? NGS_PAUSER_BYTES : parameter_size;
    uint8_t *dest;
    switch (nid) {
    case 0x5551410D: {
        dest = output(memory,r[1],24);
        if (!dest) return NGS_PARAM;
        uint32_t info[] = {voice->state,module_count,rack->inputs ? 1 : 0,rack->outputs,rack->slots,voice->updates};
        copy_out(dest,info,sizeof info);
        return 0;
    }
    case 0x1DDBEBEB:
        if (voice->state & NGS_ACTIVE) return NGS_STATE;
        if ((r[2]&2) && (r[1] || voice->locked)) return r[1] ? NGS_UNSUPPORTED : NGS_LOCKED;
        if (r[2]&1) unpatch(voice);
        if (r[2]&2) {
            defaults(voice);
            voice->bypass = 0;
        }
        if (r[2]&4) {
            voice->finish = voice->module_callback = 0;
            voice->finish_user = voice->module_user = 0;
        }
        voice->initialized = 1;
        voice->state = voice->updates = 0;
        return 0;
    case 0x8A88E665:
        if (r[1]) return NGS_UNSUPPORTED;
        if (voice->locked) return NGS_LOCKED;
        defaults(voice);
        voice->bypass = 0;
        return 0;
    case 0xFB8174B1: return voice_params_block(voice,r,memory);
    case 0xAB6BEF8F: {
        if ((!set_pauser && r[1]) || !param_size) return NGS_MODULE;
        if (voice->locked) return NGS_LOCKED;
        dest = output(memory,r[3],8);
        uint8_t *parameters = output(memory,param_address,param_size);
        if (!dest || !parameters || overlaps(r[3],8,param_address,param_size)) return NGS_PARAM;
        if (set_pauser) {
            if (r[2] != NGS_PAUSER_ID) return NGS_INTERFACE;
            uint32_t values[] = {NGS_PAUSER_ID,NGS_PAUSER_BYTES,voice->pause_in,voice->pause_out};
            copy_out(parameters,values,sizeof values);
        } else {
            uint32_t id = word(voice->params);
            if (id && ((id ^ r[2]) & 0xffff)) return NGS_INTERFACE;
            copy_out(parameters,voice->params,param_size);
            copy_out(parameters,&r[2],4);
        }
        uint32_t info[] = {param_address,param_size};
        copy_out(dest,info,sizeof info);
        voice->locked = r[1]+1;
        return 0;
    }
    case 0x3D46D8A7:
        if ((!set_pauser && r[1]) || !param_size) return NGS_MODULE;
        if (voice->locked != r[1]+1) return NGS_STATE;
        voice->locked = 0;
        return set_params(voice,r[1],span(memory,param_address,param_size),param_size);
    case 0xFA0A0F34:
        if (!voice->initialized || voice->state & NGS_ACTIVE) return NGS_STATE;
        if (rack->kind == NGS_PCM) {
            voice->buffer = voice->params[81];
            voice->offset = word(voice->params+72);
            voice->lead = word(voice->params+64);
        }
#ifdef VX_ENABLE_AUDIODEC
        if (rack->kind == NGS_AT9) {
            voice->buffer = 0;
            voice->offset = 0;
            voice->lead = word(voice->params+80);
            vx_atrac9_clear(voice->at9.decoder);
            voice->at9.cursor = voice->at9.end = 0;
        }
#endif
        voice->updates = voice->loops = voice->sample_bytes = voice->samples = 0;
        voice->fraction = 0;
        voice->state = NGS_ACTIVE;
        return 0;
    case 0xBB13373D:
        if (!(voice->state & NGS_ACTIVE) || voice->state & NGS_KEYOFF) return NGS_STATE;
        voice->state |= NGS_KEYOFF;
        return 0;
    case 0x0E291AAD:
        voice->state = 0;
        return 0;
    case 0xD7786E99:
        if (voice->state & NGS_PAUSED) return NGS_STATE;
        voice->state |= NGS_PAUSED;
        return 0;
    case 0x54CFB981:
        voice->state &= ~NGS_PAUSED;
        return 0;
    case 0x9AB87E71:
        if (r[1] >= module_count || (r[2] != 0 && r[2] != 2)) return NGS_PARAM;
        if (r[2]) voice->bypass |= 1u << r[1]; else voice->bypass &= ~(1u << r[1]);
        return 0;
    case 0x431BF3AB: {
        if (r[1] >= module_count || !(dest=output(memory,r[2],4))) return NGS_PARAM;
        uint32_t flag = voice->bypass & (1u << r[1]) ? 2 : 0;
        copy_out(dest,&flag,4);
        return 0;
    }
    case 0xB307185E: {
        if (!set_pauser && (r[1] || !parameter_size)) return NGS_MODULE;
        if (!(dest=output(memory,r[2],4))) return NGS_PARAM;
        uint32_t type = set_pauser ? NGS_PAUSER_MODULE : player_module(voice);
        copy_out(dest,&type,4);
        return 0;
    }
    case 0x01A52E3A: {
        if (r[1] >= rack->outputs || r[2] >= rack->slots || !(dest=output(memory,r[3],4))) return NGS_PARAM;
        ngs_patch *patch = find_slot(voice,r[1],r[2]);
        uint32_t token = patch ? patch->handle : 0;
        copy_out(dest,&token,4);
        return token ? 0 : NGS_PATCH;
    }
    case 0x17A6F564:
        if (r[1] && !owner) return NGS_STATE;
        voice->finish = r[1];
        voice->finish_user = r[2];
        return 0;
    case 0x24E909A8:
        if (r[1] || !parameter_size) return NGS_MODULE;
        if (r[2] && !owner) return NGS_STATE;
        voice->module_callback = r[2];
        voice->module_user = r[3];
        return 0;
    case 0xC9B8C0B4:
        if (!r[1] && parameter_size) {
            uint32_t state[] = {voice->offset,voice->buffer,voice->samples,voice->sample_bytes,
                                voice->total_samples,voice->total_bytes};
            if (r[3] != sizeof state) return NGS_SIZE;
            if (!(dest=output(memory,r[2],sizeof state))) return NGS_PARAM;
            copy_out(dest,state,sizeof state);
            return 0;
        }
        if (r[1] == 1 && rack->kind == NGS_MASTER) {
            size_t bytes = rack->system->grain * 2 * sizeof(int16_t);
            if (r[3] != bytes) return NGS_SIZE;
            if (!(dest=output(memory,r[2],bytes))) return NGS_PARAM;
            copy_out(dest,voice->rendered,bytes);
            return 0;
        }
        return NGS_MODULE;
    default: return NGS_UNSUPPORTED;
    }
}

/* FW 3.60 range translation for single- and four-frame ATRAC9 packets. */
static uint32_t section_details(const uint32_t r[16], guest_memory memory) {
    uint8_t *dest = output(memory,r[3],16);
    if (!dest) return NGS_PARAM;
    uint32_t result[4] = {0};
    copy_out(dest,result,sizeof result);
    uint32_t code = (r[2]>>12)&15;
    uint32_t frame_samples = code == 1 ? 64 : code == 4 ? 128 : code == 7 ? 256 : 0;
    uint32_t frame_bytes = (((r[2]>>16)&255)*8) + (r[2]>>29) + 1;
    if ((r[2]&255) != 0xfe || !frame_samples || r[1] > INT32_MAX) return NGS_PARAM;
    uint64_t start = r[0]&INT32_MAX;
    if (r[0]>>31) start = start > frame_samples ? start-frame_samples : 0;
    uint32_t super = !!(r[2] & (3u<<27));
    uint32_t packet_samples = super ? frame_samples*4 : frame_samples;
    uint32_t packet_bytes = super ? frame_bytes*4 : frame_bytes;
    if (super) start += frame_samples;
    uint64_t packet = start / packet_samples;
    uint32_t skip = (uint32_t)(start % packet_samples);
    if (!super) skip += frame_samples;
    else if (skip < frame_samples && packet) {
        packet--;
        skip += packet_samples;
    }
    uint64_t packets = ((uint64_t)skip+r[1]+packet_samples-1)/packet_samples;
    if (packet*packet_bytes > INT32_MAX || packets*packet_bytes > INT32_MAX)
        return NGS_RANGE;
    result[0] = (uint32_t)packet*packet_bytes;
    result[1] = (uint32_t)packets*packet_bytes;
    result[2] = skip | ((uint32_t)(packets*packet_samples-skip-r[1])<<16);
    result[3] = super;
    copy_out(dest,result,sizeof result);
    return 0;
}

int vx_ngs_import(uint32_t nid, const uint32_t r[16], uint8_t *memory_data,
                  size_t size, uint32_t base, uint32_t owner, uint32_t *result) {
    guest_memory memory = {memory_data,size,base};
    ngs_system *system;
    ngs_rack *rack;
    uint8_t *dest;
    uint32_t v;
    switch (nid) {
    case 0x2A9FA501: *result = section_details(r,memory); return 1;
    case 0x0D5399CF: *result = NGS_DEF_BASE + NGS_PCM; return 1;
    case 0x45CF2A73: *result = NGS_DEF_BASE + NGS_AT9; return 1;
    case 0x214485D6: *result = NGS_DEF_BASE + NGS_PAUSER; return 1;
    case 0x79A121D1: *result = NGS_DEF_BASE + NGS_MASTER; return 1;
    case 0xE0AC8776: *result = NGS_DEF_BASE + NGS_MIXER; return 1;
    case 0x6CE8B36F:
        v = system_size(span(memory,r[0],20));
        dest = output(memory,r[1],4);
        *result = NGS_PARAM;
        if (v && dest) {
            copy_out(dest,&v,4);
            *result = 0;
        }
        return 1;
    case 0xED14CF4A: *result = create_system(r[0],r[1],r[2],r[3],memory); return 1;
    case 0x477318C0:
        system = system_for(r[0]);
        if (!system) { *result = NGS_HANDLE; return 1; }
        v = rack_size(span(memory,r[1],24),system);
        dest = output(memory,r[2],4);
        *result = NGS_PARAM;
        if (v && dest) {
            copy_out(dest,&v,4);
            *result = 0;
        }
        return 1;
    case 0x0A92E4EC:
        system = system_for(r[0]);
        *result = system ? create_rack(system,span(memory,r[1],8),span(memory,r[2],24),r[3],memory) : NGS_HANDLE;
        return 1;
    case 0xFE1A98E9:
        rack = rack_for(r[0]);
        dest = output(memory,r[2],4);
        *result = !rack ? NGS_HANDLE : NGS_PARAM;
        if (rack && r[1] < rack->count && dest) {
            copy_out(dest,&rack->voices[r[1]].handle,4);
            *result = 0;
        }
        return 1;
    case 0xDD5CA10B:
        rack = rack_for(r[0]);
        if (!rack) *result = NGS_HANDLE;
        else if (r[1]) *result = NGS_UNSUPPORTED;
        else {
            release_rack(rack);
            *result = 0;
        }
        return 1;
    case 0x4A25BEBC: case 0x684F080C: case 0x64D80013: case 0xB9D971F2: case 0x0A93EA96:
        system = system_for(r[0]);
        *result = NGS_HANDLE;
        if (!system) return 1;
        *result = 0;
        if (nid == 0x684F080C) {
            *result = system->locks && owner != system->owner ? NGS_LOCKED : update(system,memory,owner);
        } else if (nid == 0x64D80013) {
            if (r[1] & ~1u) *result = NGS_PARAM;
            else system->flags = r[1];
        } else if (nid == 0xB9D971F2) {
            if (system->locks && owner != system->owner) *result = NGS_LOCKED;
            else { system->owner = owner; system->locks++; }
        } else if (nid == 0x0A93EA96) {
            if (!system->locks || owner != system->owner) *result = NGS_STATE;
            else if (!--system->locks) system->owner = 0;
        } else {
            ngs_voice *voices[NGS_MAX_VOICES];
            if (graph(system,voices) || system->locks) *result = NGS_DEPENDENCY;
            else { free(system->mix); *system = (ngs_system){0}; }
        }
        return 1;
    case 0xD668B49C: *result = patch_create(span(memory,r[0],20),output(memory,r[1],4)); return 1;
    case 0xD0C9AE5A: {
        ngs_patch *patch = patch_for(r[0]);
        *result = NGS_HANDLE;
        if (patch) { *patch = (ngs_patch){0}; *result = 0; }
        return 1;
    }
    case 0x98703DBC: *result = patch_info(patch_for(r[0]),r[1],r[2],memory); return 1;
    case 0xA3C807BC: case 0xBD6F57F0: case 0xA0F5402D:
        *result = patch_gain(nid,patch_for(r[0]),r,memory);
        return 1;
    case 0x5551410D: case 0x1DDBEBEB: case 0x8A88E665: case 0xFB8174B1:
    case 0xAB6BEF8F: case 0x3D46D8A7: case 0xFA0A0F34: case 0xBB13373D: case 0x0E291AAD:
    case 0xD7786E99: case 0x54CFB981: case 0x9AB87E71: case 0x431BF3AB: case 0xB307185E:
    case 0x01A52E3A: case 0x17A6F564: case 0x24E909A8: case 0xC9B8C0B4:
        *result = voice_import(nid,voice_for(r[0]),r,memory,owner);
        return 1;
    default: return 0;
    }
}
