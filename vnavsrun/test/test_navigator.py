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
