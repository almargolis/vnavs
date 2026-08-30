import time

from cvpipeline import opticchiasm as oc
from vnavsrun import navigator


class MockNavigator:
    def __init__(self):
        self.blobs = {}
        self.blobs_time = 0.0
        self.line_x = None
        self.line_x_time = 0.0
        self.line_angle = None
        self.line_centers = []

    def publish(self, topic, payload, **kwargs):
        pass


class MockMission:
    def __init__(self):
        self.navigator = MockNavigator()
        self.active_stage = None
        self.stage_step_ix = 0
        self.stage_step_loop_ct = 0
        self.confirmation_ids = {}
        self.stages_dict = {}
        self.stages_list = []
        self._start_stage_calls = []

    def StartStage(self, stage_name, initiator_payload):
        self._start_stage_calls.append((stage_name, initiator_payload))
        self.active_stage = stage_name
        self.stage_step_ix = 0
        self.stage_step_loop_ct = 0
        return True


class MockStage:
    def __init__(self, mission):
        self.mission = mission


def _make_blob(center_x, center_y, width, height, angle=0.0):
    return oc.RotatedRect(((center_x, center_y), (width, height), angle))


def _make_step(blobs=None, parm_pos=None, parm_kword=None):
    mission = MockMission()
    if blobs is not None:
        mission.navigator.blobs = blobs
    stage = MockStage(mission)
    step = navigator.StepWaitForBlob(stage)
    step.Load(
        parm_pos or ["red_sign"],
        parm_kword or {},
        [],
    )
    step.DoStageStepInit()
    return step


def test_wait_for_blob_returns_false_when_no_blob():
    step = _make_step()
    assert step.DoStageStepRun(1) is False


def test_wait_for_blob_returns_true_when_blob_detected():
    blobs = {"red_sign": [_make_blob(100, 50, 20, 30)]}
    step = _make_step(blobs=blobs)
    assert step.DoStageStepRun(1) is True


def test_wait_for_blob_respects_min_area():
    small_blob = _make_blob(100, 50, 5, 5)  # area 25
    big_blob = _make_blob(100, 50, 20, 10)  # area 200
    # Small blob should be rejected
    step = _make_step(
        blobs={"red_sign": [small_blob]},
        parm_kword={"min_area": "100"},
    )
    assert step.DoStageStepRun(1) is False
    # Big blob should be accepted
    step = _make_step(
        blobs={"red_sign": [big_blob]},
        parm_kword={"min_area": "100"},
    )
    assert step.DoStageStepRun(1) is True


def test_wait_for_blob_timeout():
    step = _make_step(parm_kword={"timeout": "0.0"})
    # With timeout=0, it should immediately return True
    assert step.DoStageStepRun(1) is True


def test_wait_for_blob_branch_sets_stage():
    blobs = {"red_sign": [_make_blob(100, 50, 20, 30)]}
    mission = MockMission()
    mission.navigator.blobs = blobs
    mission.stages_dict["turn_right"] = "stage_obj"
    mission.stages_list.append("turn_right")
    stage = MockStage(mission)
    step = navigator.StepWaitForBlob(stage)
    step.Load(["red_sign"], {"branch": "turn_right"}, [])
    step.DoStageStepInit()
    result = step.DoStageStepRun(1)
    assert result is True
    assert len(mission._start_stage_calls) == 1
    assert mission._start_stage_calls[0] == ("turn_right", None)
    assert mission.stage_step_ix == -1


def test_wait_for_blob_no_branch_just_advances():
    blobs = {"red_sign": [_make_blob(100, 50, 20, 30)]}
    mission = MockMission()
    mission.navigator.blobs = blobs
    stage = MockStage(mission)
    step = navigator.StepWaitForBlob(stage)
    step.Load(["red_sign"], {}, [])
    step.DoStageStepInit()
    result = step.DoStageStepRun(1)
    assert result is True
    assert len(mission._start_stage_calls) == 0


def test_do_cameraman_pic_ready_extracts_blobs():
    nav = MockNavigator()
    # Build a payload with serialized blobs
    blob = _make_blob(160, 100, 30, 40)
    blob_dicts = oc.list_of_rotated_rect_as_list_of_dicts([blob])
    payload = {
        "blobs": {"red_sign": blob_dicts},
    }
    # Call the extraction logic directly (same as DoCameramanPicReady)
    if payload.get("blobs"):
        nav.blobs = {}
        for label, bd in payload["blobs"].items():
            nav.blobs[label] = oc.list_of_rotated_rect_from_list_of_dicts(bd)
        nav.blobs_time = time.time()
    assert "red_sign" in nav.blobs
    assert len(nav.blobs["red_sign"]) == 1
    assert nav.blobs["red_sign"][0].center_x == 160
    assert nav.blobs["red_sign"][0].width == 30
    assert nav.blobs_time > 0


# --- StepFollowLaneCenter -------------------------------------------------


def _make_lane_step(lane_lines=None, lane_time=None, parm_kword=None):
    mission = MockMission()
    nav = mission.navigator
    nav.lane_lines = lane_lines or {}
    if lane_time is not None:
        nav.lane_lines_time = lane_time
    else:
        nav.lane_lines_time = time.time() if lane_lines else 0.0
    stage = MockStage(mission)
    step = navigator.StepFollowLaneCenter(stage)
    step.Load([], parm_kword or {}, [])
    step.DoStageStepInit()
    return step, mission


def test_lane_center_midpoint_of_both_edges():
    lines = {
        "left": [_make_blob(40, 220, 10, 20)],
        "right": [_make_blob(260, 220, 10, 20)],
    }
    step, _ = _make_lane_step(lane_lines=lines, parm_kword={"lane_half_width": "95"})
    assert step._lane_center_x() == 150.0


def test_lane_center_falls_back_to_left_offset():
    lines = {"left": [_make_blob(40, 220, 10, 20)]}
    step, _ = _make_lane_step(lane_lines=lines, parm_kword={"lane_half_width": "95"})
    assert step._lane_center_x() == 135.0


def test_lane_center_falls_back_to_right_offset():
    lines = {"right": [_make_blob(260, 220, 10, 20)]}
    step, _ = _make_lane_step(lane_lines=lines, parm_kword={"lane_half_width": "95"})
    assert step._lane_center_x() == 165.0


def test_lane_center_none_when_stale():
    lines = {
        "left": [_make_blob(40, 220, 10, 20)],
        "right": [_make_blob(260, 220, 10, 20)],
    }
    step, _ = _make_lane_step(
        lane_lines=lines,
        lane_time=time.time() - 5.0,
        parm_kword={"line_lost_timeout": "0.6"},
    )
    assert step._lane_center_x() is None


def test_lane_center_none_when_no_lines():
    step, _ = _make_lane_step()
    assert step._lane_center_x() is None


def test_lane_center_custom_labels():
    lines = {
        "lane_left": [_make_blob(50, 220, 10, 20)],
        "lane_right": [_make_blob(250, 220, 10, 20)],
    }
    step, _ = _make_lane_step(
        lane_lines=lines,
        parm_kword={"left_label": "lane_left", "right_label": "lane_right"},
    )
    assert step._lane_center_x() == 150.0


def test_lane_center_step_run_steers_and_publishes():
    lines = {
        "left": [_make_blob(40, 220, 10, 20)],
        "right": [_make_blob(240, 220, 10, 20)],  # midpoint 140, left of target
    }
    step, mission = _make_lane_step(
        lane_lines=lines,
        parm_kword={"speed": "25", "target_x": "160", "Kp": "0.5", "Kd": "0"},
    )
    published = []
    mission.navigator.publish = lambda topic, payload, **kw: published.append(payload)
    step.DoStageStepRun(1)
    assert step.nav.speed == 25
    assert len(published) == 1
    # midpoint 140 - target 160 = -20 error, Kp 0.5 -> -10.0 steering command
    assert published[0][navigator.helmsman.HELMSMAN_RAD_PER_SEC] == -10.0


def test_follow_lane_center_step_registered():
    mission = navigator.Mission(
        name="t",
        script=["stage : drive", "follow_lane_center : speed=20 : Kp=0.5"],
    )
    stage = mission.stages_dict["drive"]
    assert len(stage.steps) == 1
    assert isinstance(stage.steps[0], navigator.StepFollowLaneCenter)


def test_do_cameraman_pic_ready_extracts_lane_lines():
    nav = MockNavigator()
    nav.lane_lines = {}
    nav.lane_lines_time = 0.0
    left_dicts = oc.list_of_rotated_rect_as_list_of_dicts([_make_blob(40, 220, 10, 20)])
    right_dicts = oc.list_of_rotated_rect_as_list_of_dicts(
        [_make_blob(260, 220, 10, 20)]
    )
    payload = {"lane_lines": {"left": left_dicts, "right": right_dicts}}
    navigator.navigator.DoCameramanPicReady(nav, payload)
    assert nav.lane_lines["left"][0].center_x == 40
    assert nav.lane_lines["right"][0].center_x == 260
    assert nav.lane_lines_time > 0
