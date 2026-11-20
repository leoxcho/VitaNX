import unittest
from vitanx.power import PowerPolicy, CLOCK_GETTERS, CLOCK_SETTERS, INVALID_VALUE


class PowerPolicyTests(unittest.TestCase):
    def test_profile_validation_is_transactional_and_independent_of_clocks(self):
        policy = PowerPolicy()
        before = policy.report()['requested_clocks_mhz']
        for mode in (0x80, 0x800, 0x10880):
            self.assertEqual(policy.invoke(0x3ce187b6, [mode]), 0)
            self.assertEqual(policy.report()['requested_configuration_mode'], mode)
        for mode in (0, 0xffffffff, 0x801):
            self.assertEqual(policy.invoke(0x3ce187b6, [mode]), INVALID_VALUE)
            self.assertEqual(policy.report()['requested_configuration_mode'], 0x10880)
        self.assertEqual(policy.report()['requested_clocks_mhz'], before)
        self.assertFalse(policy.report()['host_power_controls_changed'])

    def test_requested_clock_roundtrip_and_rejected_signed_values(self):
        policy = PowerPolicy()
        for setter, name in CLOCK_SETTERS.items():
            getter = next(nid for nid, field in CLOCK_GETTERS.items() if field == name)
            self.assertEqual(policy.invoke(setter, [123]), 0)
            self.assertEqual(policy.invoke(getter, [999]), 123)
            self.assertEqual(policy.invoke(setter, [0xffffffff]), INVALID_VALUE)
            self.assertEqual(policy.invoke(getter, [0]), 123)
        self.assertEqual(policy.invoke(0x4d695c1f, [1]), 0)
        self.assertEqual(policy.invoke(0x4d695c1f, [2]), INVALID_VALUE)
        self.assertEqual(policy.invoke(0xd541ff03, [0]), 1)
        with self.assertRaises(ValueError):
            policy.invoke(0, [0])

    def test_report_does_not_expose_mutable_state_and_trace_is_bounded(self):
        policy = PowerPolicy()
        for _ in range(70):
            policy.invoke(0x3ce187b6, [0x800])
        report = policy.report()
        self.assertEqual(len(report['trace']), 64)
        report['trace'][0]['result'] = 42
        report['requested_clocks_mhz']['arm'] = 42
        self.assertEqual(policy.report()['trace'][0]['result'], 0)
        self.assertEqual(policy.report()['requested_clocks_mhz']['arm'], 444)
