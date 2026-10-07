import threading
import time
import unittest
from unittest.mock import Mock

from shundo_hunter.encounter_vision import VisionError, validate_result
from shundo_hunter.screen_recovery import (ScreenRecovery, RecoveryCancelled,
    ScreenChanged, recovery_point, egg_hint, notice_hint, native_recovery_guard)


def frame():
    return dict(pixelWidth=1284, pixelHeight=2778, cropTop=.16, cropHeight=.8,
                grid=[80]*9216, image="fake", pid=42)


def result(scene="map", action="none", box=None, label=""):
    return dict(scene=scene, action=action, target_box=box, control_text=label,
                evidence="Observed scene-specific UI", uncertainty="")


NOTICE = result("startup_notice", "dismiss_notice", dict(x=.4,y=.65,width=.2,height=.05), "OK")
NOTICE_LOCAL = dict(scene="uncertain", evidence=["Be aware of your surroundings", "OK"],
                    lines=[dict(text="OK",x=.46,y=.68,width=.08,height=.04)])
EGG = result("egg_prompt", "tap_egg", dict(x=.35,y=.35,width=.3,height=.3))
EGG_LOCAL = dict(scene="uncertain", evidence=["Oh?"], lines=[])
DETAIL = result("pokemon_details", "close_hatched_details",dict(x=.45,y=.94,width=.1,height=.035),"X")
DETAIL_LOCAL = dict(scene="uncertain", evidence=["Weight", "Height", "CP 300"], lines=[])
SPEED = {**NOTICE, "control_text": "I'M A PASSENGER"}
SPEED_LOCAL = dict(scene="uncertain", evidence=["You're going too fast!", "I'M A PASSENGER"],
                   lines=[dict(text="I'M A PASSENGER",x=.35,y=.68,width=.3,height=.04)])
WEATHER = result("startup_notice","dismiss_notice",dict(x=.291,y=.598,width=.418,height=.079),"I AM SAFE")
WEATHER_LOCAL = dict(scene="uncertain",evidence=["Weather warning", "Weather conditions are potentially dangerous", "I AM SAFE"],
                    lines=[dict(text="I AM SAFE",x=.4,y=.658,width=.2,height=.024)])
NEWS = result("announcement", "dismiss_announcement", dict(x=.418,y=.963,width=.164,height=.022), "DISMISS")
NEWS_FRAME = {**frame(), "cropHeight": .82}
NEWS_LOCAL = dict(scene="uncertain", evidence=["GO Pass: September", "34 Days Ago", "SEE DETAILS"],
                  lines=[dict(text="SEE DETAILS",x=.374,y=.525,width=.252,height=.017),
                         dict(text="DISMISS",x=.418,y=.9506,width=.164,height=.0174)])
INVENTORY = result("egg_inventory","close_hatch_inventory",dict(x=.44,y=.92,width=.12,height=.065),"X")
INVENTORY_LOCAL = dict(scene="uncertain",evidence=["Incubate eggs while Pokémon GO is closed.",
                       "TURN ON SYSTEM SETTINGS","0 / 2 km","0 / 5 km","Bonus Storage"],lines=[])


class RecoveryPolicyTests(unittest.TestCase):
    def test_post_hatch_inventory_requires_both_prior_hatch_steps(self):
        self.assertIsNotNone(recovery_point(INVENTORY,NEWS_FRAME,INVENTORY_LOCAL,True,True))
        actual_ocr={"evidence":["Incubal","ggs while Pokémon GO is closed.","TURN ON SYSTEM SETTINGS",
                               "0/2km","0 /2 km","0 / 5 km","Log in tomorrow to get another Daily","Adventure Egg.","Bony","prage"]}
        self.assertIsNotNone(recovery_point(INVENTORY,NEWS_FRAME,actual_ocr,True,True))
        with self.assertRaises(VisionError):
            recovery_point(INVENTORY,NEWS_FRAME,{"evidence":actual_ocr["evidence"]+["Log in to your account"]},True,True)
        for seen,closed in [(False,False),(True,False),(False,True)]:
            with self.assertRaises(VisionError):recovery_point(INVENTORY,NEWS_FRAME,INVENTORY_LOCAL,seen,closed)
        for changed,local in [({"control_text":"TURN ON SYSTEM SETTINGS"},INVENTORY_LOCAL),
                              ({"target_box":dict(x=.82,y=.02,width=.1,height=.05)},INVENTORY_LOCAL),
                              ({},{"evidence":["Eggs"]}),({},{**INVENTORY_LOCAL,"scene":"encounter"})]:
            with self.assertRaises(VisionError):recovery_point({**INVENTORY,**changed},NEWS_FRAME,local,True,True)

    def test_observed_news_dismiss_below_old_crop_is_allowed(self):
        self.assertTrue(notice_hint(NEWS_LOCAL))
        x,y = recovery_point(NEWS,NEWS_FRAME,NEWS_LOCAL,False)
        self.assertAlmostEqual(x,.5)
        self.assertGreater(y,.955)

    def test_news_never_opens_details_or_uses_unidentified_close(self):
        for changed,local in [({"control_text":"SEE DETAILS"},NEWS_LOCAL),
                              ({"target_box":dict(x=.4,y=.44,width=.2,height=.03)},NEWS_LOCAL),
                              ({},{**NEWS_LOCAL,"lines":NEWS_LOCAL["lines"][:1]}),
                              ({},{**NEWS_LOCAL,"lines":NEWS_LOCAL["lines"][1:]}),
                              ({},{**NEWS_LOCAL,"scene":"encounter"}),
                              ({},{**NEWS_LOCAL,"evidence":["Terms of Service"]}),
                              ({"target_box":dict(x=.4,y=.993,width=.2,height=.005)},NEWS_LOCAL)]:
            with self.assertRaises(VisionError):recovery_point({**NEWS,**changed},NEWS_FRAME,local,False)

    def test_observed_weather_safe_button_and_local_corroboration(self):
        self.assertTrue(notice_hint(WEATHER_LOCAL))
        self.assertIsNotNone(recovery_point(WEATHER,frame(),WEATHER_LOCAL,False))
        for local in [NOTICE_LOCAL,{**WEATHER_LOCAL,"lines":[]},{**WEATHER_LOCAL,"evidence":["Weather warning", "Terms of Service"]}]:
            with self.assertRaises(VisionError):recovery_point(WEATHER,frame(),local,False)
    def test_real_notice_requires_local_text_and_button_bounds(self):
        self.assertIsNotNone(recovery_point(NOTICE,frame(),NOTICE_LOCAL,False))
        for local in ({**NOTICE_LOCAL,"lines":[]}, {**NOTICE_LOCAL,"evidence":["Welcome", "OK"]},
                      {**NOTICE_LOCAL,"evidence":["Be aware of your surroundings", "Terms of Service"]}):
            with self.assertRaises(VisionError):recovery_point(NOTICE,frame(),local,False)

    def test_egg_prompt_needs_local_corroboration(self):
        self.assertTrue(egg_hint(EGG_LOCAL))
        self.assertFalse(egg_hint({"evidence":["Egg inventory", "Hatch 3 eggs"]}))
        self.assertIsNotNone(recovery_point(EGG,frame(),EGG_LOCAL,False))
        with self.assertRaises(VisionError):recovery_point(EGG,frame(),{"evidence":[]},False)

    def test_speed_notice_needs_exact_game_text_and_button(self):
        self.assertTrue(notice_hint(SPEED_LOCAL))
        self.assertIsNotNone(recovery_point(SPEED,frame(),SPEED_LOCAL,False))
        # The real iPhone's acknowledgment spans almost three quarters of its width.
        live = {**SPEED,"target_box":dict(x=.132,y=.587,width=.736,height=.08)}
        ocr = {**SPEED_LOCAL,"lines":[dict(text="I'M A PASSENGER",x=.3019,y=.6526,width=.3805,height=.01744)]}
        self.assertIsNotNone(recovery_point(live,frame(),ocr,False))
        with self.assertRaises(VisionError):recovery_point(SPEED,frame(),NOTICE_LOCAL,False)

    def test_details_only_after_hatch_and_only_bottom_close(self):
        self.assertIsNotNone(recovery_point(DETAIL,frame(),DETAIL_LOCAL,True))
        for change, local, seen in [({},DETAIL_LOCAL,False),({"control_text":"Evolve"},DETAIL_LOCAL,True),
                                   ({},{"evidence":["CP 300"]},True),
                                   ({"target_box":dict(x=.4,y=.5,width=.1,height=.03)},DETAIL_LOCAL,True)]:
            with self.assertRaises(VisionError):recovery_point({**DETAIL,**change},frame(),local,seen)

    def test_observed_grookey_checkmark_with_weight_record(self):
        live = {**DETAIL,"control_text":"checkmark",
                "target_box":dict(x=.438,y=.901,width=.12,height=.053)}
        local=dict(scene="uncertain",evidence=["Grookey","88 / 88 HP","2.53kg","LIGHTEST","0.24m","HEIGHT","POWER UP","EVOLVE"])
        self.assertIsNotNone(recovery_point(live,NEWS_FRAME,local,True))
        for changed,seen in [({},False),({"control_text":"EVOLVE"},True),
                             ({"target_box":dict(x=.8,y=.9,width=.12,height=.053)},True),
                             ({"target_box":dict(x=.438,y=.7,width=.12,height=.053)},True)]:
            with self.assertRaises(VisionError):recovery_point({**live,**changed},NEWS_FRAME,local,seen)

    def test_encounter_unknown_permission_never_tapped(self):
        for scene in ("encounter","other","uncertain"):
            with self.assertRaises(VisionError):recovery_point(result(scene),frame(),NOTICE_LOCAL,True)
        for scene in ("encounter","caught","fled","blocked-ball"):
            with self.assertRaises(VisionError):recovery_point(NOTICE,frame(),{**NOTICE_LOCAL,"scene":scene},False)
        for kind in ("Alert","Sheet","TextField","SecureTextField"):
            with self.assertRaises(VisionError):native_recovery_guard(f'<App><XCUIElementType{kind}/></App>')

    def test_malformed_or_ambiguous_evidence_rejected(self):
        for update in ({"action":"throw"},{"uncertainty":"not sure"},{"evidence":""},
                       {"target_box":dict(x=float("nan"),y=.3,width=.1,height=.1)},
                       {"target_box":dict(x=.95,y=.3,width=.1,height=.1)}):
            with self.assertRaises(VisionError):recovery_point({**NOTICE,**update},frame(),NOTICE_LOCAL,False)
        with self.assertRaises(VisionError):validate_result({**NOTICE,"unexpected":True},"recover")


class RecoveryFlowTests(unittest.TestCase):
    def setUp(self):
        self.guard=Mock()
        self.guard.operation_lock=threading.RLock()
        self.guard.active=True; self.guard.protected=False
        self.guard.stop_event.is_set.return_value=False
        self.guard.stop_event.wait.return_value=False
        self.guard.power.poll.return_value=None
        self.guard.vision.client.status.return_value={"visionConfigured":True}
        self.r=ScreenRecovery(self.guard)
        self.r._capture=Mock(return_value=(frame(),NOTICE_LOCAL))
        self.r._tap=Mock()
        self.r._ask=Mock(side_effect=[NOTICE,result(),result()])

    def test_notice_then_two_maps(self):
        self.r.run("test",lambda:None)
        self.assertEqual(self.r._tap.call_count,1)
        self.assertEqual(self.r._ask.call_count,3)
        self.assertEqual(self.r.state,"map-ready")
        self.assertFalse(self.r.busy)
        self.guard.controller.throw_once.assert_not_called()

    def test_stacked_speed_then_news_then_two_maps(self):
        self.r._capture.side_effect=[(frame(),SPEED_LOCAL),(NEWS_FRAME,NEWS_LOCAL),(frame(),{}),(frame(),{})]
        self.r._ask.side_effect=[SPEED,NEWS,result(),result()]
        self.r.run("stacked notices",lambda:None)
        self.assertEqual(self.r._tap.call_count,2)
        self.assertEqual(self.r.state,"map-ready")
        self.assertFalse(self.r.resume_pending)

    def test_read_only_capture_retries_transient_banner_foreground_failure(self):
        self.r._capture_once=Mock(side_effect=[RuntimeError("foreground changed"),(frame(),NOTICE_LOCAL)])
        self.assertEqual(ScreenRecovery._capture(self.r,lambda:None)[0],frame())
        self.assertEqual(self.r._capture_once.call_count,2)
        self.r._tap.assert_not_called()

    def test_capture_retry_is_bounded_and_preserves_diagnostic(self):
        self.r._capture_once=Mock(side_effect=RuntimeError("foreground changed"))
        with self.assertRaisesRegex(VisionError,"Screen observation unavailable.*foreground changed"):
            ScreenRecovery._capture(self.r,lambda:None)
        self.assertEqual(self.r._capture_once.call_count,8)
        self.r._tap.assert_not_called()

    def test_pending_alert_wins_over_simultaneous_capture_error(self):
        pending=False
        def capture(check):
            nonlocal pending
            pending=True
            raise RuntimeError("foreground changed")
        def check():
            if pending:raise RecoveryCancelled("Hundo pending")
        self.r._capture_once=capture
        with self.assertRaises(RecoveryCancelled):ScreenRecovery._capture(self.r,check)
        self.r._tap.assert_not_called()

    def test_full_egg_flow(self):
        self.r._capture.side_effect=[(frame(),EGG_LOCAL),(frame(),EGG_LOCAL),(frame(),DETAIL_LOCAL),(frame(),{}),(frame(),{})]
        self.r._ask.side_effect=[EGG,result("egg_animation","wait"),DETAIL,result(),result()]
        self.r.run("egg",lambda:None)
        self.assertEqual(self.r._tap.call_count,2)
        self.assertEqual(self.r.state,"map-ready")

    def test_hatch_details_then_inventory_then_map(self):
        self.r._capture.side_effect=[(frame(),EGG_LOCAL),(frame(),DETAIL_LOCAL),
                                    (NEWS_FRAME,INVENTORY_LOCAL),(frame(),{}),(frame(),{})]
        self.r._ask.side_effect=[EGG,DETAIL,INVENTORY,result(),result()]
        self.r.run("full hatch inventory flow",lambda:None)
        self.assertEqual(self.r._tap.call_count,3)
        self.assertEqual(self.r.state,"map-ready")
        self.assertFalse(self.r.hatch_details_closed)

    def test_restart_cannot_reuse_hatch_history_to_close_inventory(self):
        self.r.hatch_process=42;self.r.hatch_observed_at=time.monotonic()
        self.r.hatch_details_closed=True;self.r.resume_pending=True
        self.r._capture.return_value=({**NEWS_FRAME,"pid":99},INVENTORY_LOCAL)
        self.r._ask.side_effect=[INVENTORY]
        with self.assertRaises(VisionError):self.r.run("new process",lambda:None)
        self.r._tap.assert_not_called()

    def test_repeat_notice_cannot_be_spammed(self):
        self.r._ask.side_effect=[NOTICE,NOTICE]
        with self.assertRaisesRegex(VisionError,"progress"):self.r.run("test",lambda:None)
        self.assertEqual(self.r._tap.call_count,1)

    def test_interrupted_delivered_tap_cannot_repeat_on_same_process(self):
        self.r.resume_pending=True
        self.r.resume_action=("startup_notice","dismiss_notice")
        self.r.resume_pid=42
        with self.assertRaisesRegex(VisionError,"progress"):
            self.r.run("resumed notice",lambda:None)
        self.r._tap.assert_not_called()

    def test_same_process_hatch_history_survives_ordinary_hundo_yield(self):
        self.r.resume_pending=True
        self.r.hatch_process=42
        self.r.hatch_observed_at=time.monotonic()
        self.r._capture.side_effect=[(frame(),DETAIL_LOCAL),(frame(),{}),(frame(),{})]
        self.r._ask.side_effect=[DETAIL,result(),result()]
        self.r.run("resumed hatch",lambda:None)
        self.assertEqual(self.r._tap.call_count,1)
        self.assertEqual(self.r.state,"map-ready")

    def test_uncertain_touch_delivery_is_not_retried(self):
        self.r._tap.side_effect=TimeoutError()
        with self.assertRaises(VisionError):self.r.run("test",lambda:None)
        self.assertEqual(self.r._tap.call_count,1)
        self.assertEqual(self.r.state,"attention")

    def test_changed_screen_observed_again_without_retrying_delivery(self):
        self.r._tap.side_effect=ScreenChanged("changed before delivery")
        self.r.run("test",lambda:None)
        self.assertEqual(self.r._tap.call_count,1)
        self.assertEqual(self.r.state,"map-ready")

    def test_bounded_loading_and_hourly_cloud_budget(self):
        self.r._ask.side_effect=None;self.r._ask.return_value=result("loading","wait")
        with self.assertRaisesRegex(VisionError,"budget"):self.r.run("test",lambda:None)
        self.assertEqual(self.r._ask.call_count,8)
        self.r._tap.assert_not_called()
        other=ScreenRecovery(self.guard);other.calls.extend([time.monotonic()]*60)
        with self.assertRaisesRegex(VisionError,"hourly"):other._ask(frame(),lambda:None)
        self.guard.vision.client.analyze.assert_not_called()

    def test_cancel_or_shundo_preemption_before_tap(self):
        self.r._capture.side_effect=RecoveryCancelled("Shundo pending")
        with self.assertRaises(RecoveryCancelled):self.r.run("test",lambda:None)
        self.r._tap.assert_not_called()
        self.assertTrue(self.r.resume_pending)

    def test_protected_encounter_blocks_routine_recovery(self):
        self.guard.protected=True
        # Real capture invokes the guard before accessing the phone.
        self.r._capture=lambda check:(check(),{})
        with self.assertRaises(RecoveryCancelled):self.r.run("test",lambda:None)

    def test_cancel_during_cloud_call_is_checked(self):
        self.r._ask=ScreenRecovery._ask.__get__(self.r)
        def analyze(*args):self.r.cancel();return NOTICE
        self.guard.vision.client.analyze.side_effect=analyze
        with self.assertRaises(RecoveryCancelled):self.r.run("test",lambda:None)
        self.r._tap.assert_not_called()

    def test_shundo_preemption_keeps_same_process_hatch_provenance(self):
        self.r._capture.side_effect=[(frame(),EGG_LOCAL),RecoveryCancelled("Shundo pending")]
        self.r._ask.side_effect=[EGG]
        with self.assertRaises(RecoveryCancelled):self.r.run("egg",lambda:None)
        self.guard.protected=True;self.guard.state="opening";self.guard.event={}
        self.r._capture.side_effect=[(frame(),DETAIL_LOCAL),(frame(),{}),(frame(),{})]
        self.r._ask.side_effect=[DETAIL,result(),result()]
        self.r.run("Shundo preflight",lambda:None,protected=True)
        self.assertEqual(self.r._tap.call_count,2)
        self.assertIsNone(self.r.hatch_process)

    def test_old_or_different_process_hatch_history_cannot_close_details(self):
        self.guard.protected=True;self.guard.state="opening";self.guard.event={}
        for pid,at in [(43,time.monotonic()),(42,time.monotonic()-181)]:
            self.r.hatch_process=pid;self.r.hatch_observed_at=at
            self.r._capture.return_value=(frame(),DETAIL_LOCAL)
            self.r._ask.side_effect=[DETAIL]
            with self.assertRaisesRegex(VisionError,"observed hatch"):self.r.run("Shundo preflight",lambda:None,protected=True)
        self.r._tap.assert_not_called()


class RecoveryTouchTests(unittest.TestCase):
    def setUp(self):
        self.guard=Mock();self.guard.operation_lock=threading.RLock()
        self.guard.controller.session_id="session"
        def request(method,path,*args):
            if path.endswith('/size'):return {"value":{"width":428,"height":926}}
            if path.endswith('/source'):return {"value":"<App/>"}
            return {"value":None}
        self.guard.controller._request.side_effect=request
        self.r=ScreenRecovery(self.guard)
        self.r._capture=Mock(return_value=(frame(),NOTICE_LOCAL))

    def actions(self):
        return [c for c in self.guard.controller._request.call_args_list if c.args[1].endswith('/actions')]

    def test_guarded_notice_tap(self):
        self.r._tap(frame(),NOTICE_LOCAL,NOTICE,False,lambda:None)
        self.assertEqual(len(self.actions()),1)

    def test_weather_acknowledgment_requires_active_spoof_stream(self):
        self.r._capture.return_value=(frame(),WEATHER_LOCAL)
        self.guard.device.location_process=None
        with self.assertRaisesRegex(VisionError,"simulated-location"):
            self.r._tap(frame(),WEATHER_LOCAL,WEATHER,False,lambda:None)
        self.assertEqual(self.actions(),[])
        self.guard.device.location_process=Mock(poll=Mock(return_value=None))
        self.guard.device.status.return_value={"phoneSimulatedLocation":{"latitude":40,"longitude":-111}}
        self.r._tap(frame(),WEATHER_LOCAL,WEATHER,False,lambda:None)
        self.assertEqual(len(self.actions()),1)

    def test_speed_notice_requires_live_hunter_location_process(self):
        self.r._capture.return_value=(frame(),SPEED_LOCAL)
        for process in [None,Mock(poll=Mock(return_value=1))]:
            self.guard.device.location_process=process
            with self.assertRaisesRegex(VisionError,"simulated-location"):self.r._tap(frame(),SPEED_LOCAL,SPEED,False,lambda:None)
        self.assertEqual(self.actions(),[])
        self.guard.device.location_process=Mock(poll=Mock(return_value=None))
        self.guard.device.status.return_value={"phoneSimulatedLocation":{"latitude":40,"longitude":-111}}
        self.r._tap(frame(),SPEED_LOCAL,SPEED,False,lambda:None)
        self.assertEqual(len(self.actions()),1)

    def test_stale_and_encounter_frames_never_tap(self):
        for fresh,local in [({**frame(),"pid":43},NOTICE_LOCAL),({**frame(),"grid":[255]*9216},NOTICE_LOCAL),
                            (frame(),{**NOTICE_LOCAL,"scene":"encounter"})]:
            self.r._capture.return_value=(fresh,local)
            with self.assertRaises(VisionError):self.r._tap(frame(),NOTICE_LOCAL,NOTICE,False,lambda:None)
        self.assertEqual(self.actions(),[])


if __name__ == '__main__': unittest.main()
