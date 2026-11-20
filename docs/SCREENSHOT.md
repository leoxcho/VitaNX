# Screenshot permission and metadata

The reached import f26fc97d/76e674d1 is sceScreenShotEnable(void).
The native compatibility provider retains per-session screenshot permission:
enable sets it, disable clears it. Initial state is unspecified rather than an
assertion about original firmware defaults. Success means that the policy changed,
not that an image was captured or a GPU frame existed. Report fields expose this
boundary explicitly; captures_written remains zero.

sceScreenShotSetParam retains the public16-byte parameter structure. Guest32-bit
pointers resolve into the shared memory. Photo/game titles and comments decode
bounded, terminated SceWChar32 strings (64/64/128 words including terminator),
and reserved must be null. Null field pointers mean unspecified metadata in this
compatibility model. Invalid addresses, unterminated strings, invalid Unicode
scalars, alignment or reserved fields return SDK INVALID_ARGUMENT transactionally.
These checks are a defined safe compatibility policy; firmware edge-case behavior
has not been independently measured. The provider writes no guest memory or files.

Capture and notification functions remain unresolved. They require real
framebuffer capture/presentation integration; returning success without that work
would misrepresent their behavior. Permissions must be consulted by a future
capture operation. Enabling the permission does not allocate an overlay or image.

Sources inspected November10,2026 (numeric ABI/declarations only; no implementation
copied):
- https://github.com/vitasdk/vita-headers/blob/master/include/psp2/screenshot.h
- https://github.com/vitasdk/vita-headers/blob/master/db/360/SceScreenShot.yml
- https://github.com/Vita3K/Vita3K/blob/master/vita3k/modules/SceScreenShot/SceScreenShot.cpp

Vita3K currently leaves all these exports unimplemented, so it provides no
validated capture behavior to reuse. Tests cover permission transitions, metadata
bounds, UTF32 validation, transactional rejection and report isolation. Native
ARM tests also verify exact library qualification and CPU/SP preservation.

Overlay configuration now decodes the actual app0 PNG into retained RGBA pixels
with standard-library CRC, bounded zlib and PNG filters0..4. Only noninterlaced
RGBA8 up to960x544 and4MiB encoded data are supported; other formats return the
SDK unsupported-format error. Strict app0 paths, guest string bounds and symlink
checks prevent escaping original read-only assets. Missing files return the SDK
file-not-found error. Errors preserve prior configuration. Signed offsets are
retained without requiring the whole overlay to fit the framebuffer: the actual
startup can deliberately place it partly outside. A future compositor must clip
these offsets before writing pixels. No capture or displayed-frame claim follows
from this configuration API. PNG reference: https://www.w3.org/TR/png-3/#9Filters

Bounded original Gravity Rush observation: after enabling, startup calls SetParam
with three empty WCHAR32 strings, then SetOverlayImage for
app0:/sysdata/screenshot_overlay.png (3654encoded bytes). Independent decoder
produced480x272 RGBA,522240bytes, pixel SHA256
dcefc45c711c67673f4c9cd00eb04e33bd6ccfcd61114634eb47a48c8bd1b08d. This
is an overlay asset, not an authentic rendered game frame. Following calls load
sysmodule6(FIBER) and14(PGF), from VitaSDK sysmodule.h. Neither provider was
synthesized by this work.
