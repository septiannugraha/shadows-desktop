import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"desktop"))
import json
import os
import tempfile
import unittest
import time
from unittest.mock import patch

from pathlib import Path
from model import Selection, read_sessions, cast_for, atomic_json


def session(key, time=100, phase="idle", agents=None):
    return dict(schema=1, protocol="shadows-desktop/1", host="alpha", instanceId=key, sessionId="same-resumed-session", pid=os.getpid(), name='test', cwd='/test',
                heartbeatAt=time, activityAt=time, phase=phase, agents=agents or {})


class Arbitration(unittest.TestCase):
    def test_busy_session_does_not_jump_to_other_process(self):
        s = Selection()
        a = session("a", phase="working")
        self.assertIs(s.choose({"a": a}), a)
        b = session("b", 500)
        self.assertIs(s.choose({"a": a, "b": b}), a)
        a["phase"] = "idle"
        self.assertIs(s.choose({"a": a, "b": b}), b)

    def test_pin_never_falls_back_even_for_same_session_id(self):
        s = Selection(); s.pinned = "gone"
        self.assertIsNone(s.choose({"other": session("other")}))

    def test_heartbeat_does_not_drive_selection(self):
        a, b = session("a", 100), session("b", 200)
        a["heartbeatAt"] = 900
        self.assertEqual(Selection().choose({"a": a, "b": b})["instanceId"], "b")

    def test_stale_partial_and_invalid_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            atomic_json(Path(d)/"a.json", session("a", 100))
            (Path(d)/"partial.json").write_text('{')
            self.assertEqual(list(read_sessions(d, 1000)), ["a"])
            self.assertEqual(read_sessions(d, 21000), {})

    def test_repeated_character_runs_are_distinct_but_not_duplicate_portraits(self):
        runs = {str(i): dict(runId=str(i), agent=agent, phase="running", task="", startedAt=i, updatedAt=i)
                for i, agent in enumerate(["beta", "beta", "delta", "eta"])}
        s = session("a", agents=runs)
        self.assertEqual([a["agent"] for a in cast_for(s, "0", 10)], ["alpha", "beta", "eta"])
        self.assertEqual(len(s["agents"]), 4)


class SpeechAnimation(unittest.TestCase):
    def test_final_reply_animates_once_and_expires(self):
        from model import SpeechClock
        clock = SpeechClock()
        self.assertTrue(clock.update('session/beta-run', 'Hello Shadow!', 10))
        self.assertTrue(clock.update('session/beta-run', 'Hello Shadow!', 11))
        self.assertFalse(clock.update('session/beta-run', 'Hello Shadow!', 30))
        self.assertTrue(clock.update('session/beta-run', 'A new reply', 31))
        self.assertTrue(clock.update('other/beta-run', 'Hello Shadow!', 32))

class Modes(unittest.TestCase):
    def test_commander_host_keeps_real_subagent_identity(self):
        s=session('one',agents={'r':dict(runId='r',agent='beta',phase='running',task='work',startedAt=1,updatedAt=1)})
        s['mode']='commander';s['host']='tenka'
        cast=cast_for(s,now=10)
        self.assertEqual([a['agent'] for a in cast],['tenka','beta'])
        self.assertEqual(cast[0]['runId'],'__host__')

class Foreground(unittest.TestCase):
    def test_host_retakes_dialogue_after_delegated_reply(self):
        from model import speaker_for
        ren=dict(runId='ren-run',agent='ren',phase='success',task='review',dialogue='Reviewed.',startedAt=10,updatedAt=20)
        s=session('one',30,'speaking',{'ren-run':ren});s['mode']='commander';s['host']='tenka'
        self.assertEqual(speaker_for(s,now=31)['agent'],'tenka')
        self.assertEqual(speaker_for(s,'ren-run',now=31)['agent'],'ren')
        s['phase']='working';s['activityAt']=15;ren['phase']='running'
        self.assertEqual(speaker_for(s,now=31)['agent'],'ren')
        self.assertEqual(speaker_for(s,'__host__',now=31)['agent'],'tenka')
        s['mode']='shadow';s['host']='alpha';s['phase']='speaking';s['activityAt']=40
        self.assertEqual(speaker_for(s,now=41)['agent'],'alpha')
        self.assertEqual(speaker_for(s,'ren-run',now=41)['agent'],'ren')
