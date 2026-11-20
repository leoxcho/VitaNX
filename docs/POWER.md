# ScePower guest policy

`vitanx/power.py` implements a per-session requested-policy model for exact
ScePower library `1082da7f`. Accepted configuration requests (`0x80`, `0x800`,
`0x10880`) are retained and reported. Unknown modes return `0x802b0000` without
changing policy. This supplies meaningful state at Gravity Rush's reached
`3ce187b6(0x800)` boundary; the combined real-game diagnostic now passes this call and reaches SceScreenShot.

Clock setters retain nonnegative signed-int MHz requests, and corresponding
queries return those requests. Initial virtual values are ARM 444, bus 222,
GPU 222, crossbar 166 MHz, explicit compatibility defaults. They are not measured
firmware clocks, do not control instruction timing, and never change host clocks.
No evidence establishes a configuration-mode-to-clock mapping, so mode changes
do not alter clock requests. Wireless usage is another retained boolean hint.
Battery, callbacks, reset, suspend and display power APIs remain unsupported.
No APIs here alter macOS power settings or network settings.

Sources inspected November 10, 2026:
- [VitaSDK declarations](https://github.com/vitasdk/vita-headers/blob/master/include/psp2/power.h): configuration-mode behavior is unspecified; clock APIs use MHz.
- [VitaSDK NIDs](https://github.com/vitasdk/vita-headers/blob/master/db/360/ScePower.yml): exact user library and function identifiers.
- [Vita3K ScePower](https://github.com/Vita3K/Vita3K/blob/master/vita3k/modules/ScePower/ScePower.cpp): accepted mode values and invalid-value error provide compatibility evidence. Implementation was independently written; no GPL implementation was copied.

Focused validation: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m unittest -v test_power`.
Three cases check transactional mode rejection, independent requested clocks,
signed arguments, round-trip queries, wireless validation, unsupported NIDs,
bounded diagnostics and report isolation. Native import integration must also
verify exact library dispatch and guest CPU argument/return preservation.
