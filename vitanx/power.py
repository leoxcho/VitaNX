"""Guest power-policy hints, independent of host power or clock controls.

ABI identifiers: VitaSDK ScePower.yml. Configuration-mode validation follows
observed Vita3K accepted values; its implementation is not copied. Neither
source defines profile-to-clock mappings, so accepting a mode never changes
requested clocks. Values returned by clock queries describe this virtual policy,
not measured Vita firmware clocks or Apple Silicon frequencies.
"""
import threading

LIBRARY = '1082da7f'
INVALID_VALUE = 0x802b0000
MODES = frozenset((0x80, 0x800, 0x10880))
CLOCK_GETTERS = {0xabc6f88f: 'arm', 0x478fe6f5: 'bus',
                 0x1b04a1d6: 'gpu', 0x0a750dee: 'gpu_xbar'}
CLOCK_SETTERS = {0x74db5ae5: 'arm', 0xb8d7b3fb: 'bus',
                 0x717db06c: 'gpu', 0xa7739dbe: 'gpu_xbar'}
APIS = {0x3ce187b6: 'set_configuration_mode',
        0xd541ff03: 'get_using_wireless', 0x4d695c1f: 'set_using_wireless',
        **{nid: 'get_' + name + '_clock' for nid, name in CLOCK_GETTERS.items()},
        **{nid: 'set_' + name + '_clock' for nid, name in CLOCK_SETTERS.items()}}


class PowerPolicy:
    def __init__(self, session=None):
        self.lock = threading.RLock()
        self.requested_mode = None
        self.clocks = {'arm': 444, 'bus': 222, 'gpu': 222, 'gpu_xbar': 166}
        self.wireless = 0
        self.trace = []

    def invoke(self, nid, r):
        with self.lock:
            argument = int(r[0]) & 0xffffffff
            result = 0
            if nid == 0x3ce187b6:
                if argument not in MODES:
                    result = INVALID_VALUE
                else:
                    self.requested_mode = argument
            elif nid in CLOCK_GETTERS:
                result = self.clocks[CLOCK_GETTERS[nid]]
            elif nid in CLOCK_SETTERS:
                # ABI accepts signed int MHz. These are retained hints; no
                # scheduling speed or host clock adjustment is implied.
                if argument > 0x7fffffff:
                    result = INVALID_VALUE
                else:
                    self.clocks[CLOCK_SETTERS[nid]] = argument
            elif nid == 0xd541ff03:
                result = self.wireless
            elif nid == 0x4d695c1f:
                if argument not in (0, 1):
                    result = INVALID_VALUE
                else:
                    self.wireless = argument
            else:
                raise ValueError('unsupported ScePower NID')
            self.trace.append({'nid': '%08x' % nid, 'argument': argument, 'result': result})
            self.trace = self.trace[-64:]
            return result

    def report(self):
        with self.lock:
            return {'requested_configuration_mode': self.requested_mode,
                    'requested_clocks_mhz': dict(self.clocks),
                    'wireless_usage_hint': self.wireless,
                    'host_power_controls_changed': False,
                    'scope': 'virtual guest policy hints; no firmware profile mapping, host clocks, battery emulation or callbacks',
                    'trace': [dict(item) for item in self.trace]}
