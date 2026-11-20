import unittest
from vitanx.diagnostics import summarize
class DiagnosticsTests(unittest.TestCase):
    def test_counters_and_linkage_never_establish_interactive_gameplay(self):
        report={'status':-9,'total_instructions':408997,'native_builds':[{'cache_hit':True},{'cache_hit':False}],
                'fault_context':{'library_nid':'1082da7f'},'media':{'enabled':True}}
        result=summarize(report)
        self.assertEqual(result['translation'],{'regions':2,'reused':1})
        self.assertEqual(result['execution']['guest_dispatches'],408997)
        self.assertEqual(result['boundary'],report['fault_context'])
        self.assertEqual(result['verification']['interactive_gameplay'],'unverified')
        self.assertEqual(summarize({})['media'],{})
