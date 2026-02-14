import time

import numpy as np

from vnavslib import opticchiasm as oc
from vnavslib import vnavs_data as vdata
from vnavsrun import cvlab


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class MockLabel:
    """Stand-in for an easytk label widget."""

    def __init__(self):
        self.last_value = None

    def replace_value(self, value):
        self.last_value = value


class MockCanvas:
    """Stand-in for an easytk canvas widget."""

    def __init__(self):
        self.last_source_im = None

    def update_image(self, source_im=None):
        self.last_source_im = source_im


_PROCESS_STEP_SLOT_DEFAULTS = {
    "cv_filter_name": None,
    "cv_specs": None,
    "deposition": MockLabel(),
    "exec_annotated": None,
    "exec_contours": None,
    "exec_hierarchy": None,
    "exec_hsvspec": None,
    "exec_im": None,
    "exec_objects": None,
    "exec_rect": None,
    "execution_time": MockLabel(),
    "filter_selection": None,
    "image_widget": MockCanvas(),
    "info_data": [],
    "info_widgets": [],
    "input_panel": None,
    "ix": 0,
    "output_panel": None,
    "parm_widgets": [],
    "parm_values": {},
    "parms_specs": [],
    "point_target": None,
    "source_im": None,
    "source_path": None,
    "tab": None,
    "tab_title": "Step 0",
    "thumbnail": None,
    "use_annotation": None,
    "use_objects": None,
    "zoom_popup": None,
}


def make_process_step(**overrides):
    """Create a ProcessStep without invoking __init__ (which needs Tkinter)."""
    ps = object.__new__(cvlab.ProcessStep)
    defaults = {k: v for k, v in _PROCESS_STEP_SLOT_DEFAULTS.items()}
    # Give each instance its own mutable containers
    defaults["info_data"] = []
    defaults["info_widgets"] = []
    defaults["parm_widgets"] = []
    defaults["parm_values"] = {}
    defaults["parms_specs"] = []
    defaults["deposition"] = MockLabel()
    defaults["execution_time"] = MockLabel()
    defaults["image_widget"] = MockCanvas()
    defaults.update(overrides)
    for attr, val in defaults.items():
        setattr(ps, attr, val)
    return ps


# ---------------------------------------------------------------------------
# Fixtures (manual, matching existing project style)
# ---------------------------------------------------------------------------

_saved_steps = None
_saved_app = None


def _save_class_state():
    global _saved_steps, _saved_app
    _saved_steps = cvlab.ProcessStep.steps
    _saved_app = cvlab.ProcessStep.app


def _restore_class_state():
    cvlab.ProcessStep.steps = _saved_steps
    cvlab.ProcessStep.app = _saved_app


def _with_clean_class_state(fn):
    """Decorator that saves/restores ProcessStep class state around a test."""
    def wrapper(*args, **kwargs):
        _save_class_state()
        cvlab.ProcessStep.steps = []
        try:
            return fn(*args, **kwargs)
        finally:
            _restore_class_state()
    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Tests: info_data management (clear_info, add_info, set_info)
# ---------------------------------------------------------------------------

def test_clear_info_empties_existing_list():
    ps = make_process_step(info_data=[("a", "1"), ("b", "2")])
    ps.clear_info()
    assert ps.info_data == []


def test_clear_info_on_already_empty_list():
    ps = make_process_step(info_data=[])
    ps.clear_info()
    assert ps.info_data == []


def test_add_info_returns_correct_indices():
    ps = make_process_step()
    assert ps.add_info("first", "1") == 0
    assert ps.add_info("second", "2") == 1
    assert ps.add_info("third", "3") == 2


def test_add_info_stores_tuples():
    ps = make_process_step()
    ps.add_info("label_a", "value_a")
    ps.add_info("label_b", "value_b")
    assert ps.info_data == [("label_a", "value_a"), ("label_b", "value_b")]


def test_set_info_pads_when_index_beyond_end():
    ps = make_process_step()
    ps.set_info(3, "far", "away")
    assert len(ps.info_data) == 4
    assert ps.info_data[0] == ("", "")
    assert ps.info_data[1] == ("", "")
    assert ps.info_data[2] == ("", "")
    assert ps.info_data[3] == ("far", "away")


def test_set_info_overwrites_existing_entry():
    ps = make_process_step()
    ps.add_info("old_label", "old_value")
    ps.set_info(0, "new_label", "new_value")
    assert ps.info_data[0] == ("new_label", "new_value")


def test_set_info_at_exact_length_extends_by_one():
    ps = make_process_step()
    ps.add_info("a", "1")
    ps.set_info(1, "b", "2")
    assert len(ps.info_data) == 2
    assert ps.info_data[1] == ("b", "2")


# ---------------------------------------------------------------------------
# Tests: save_parameters
# ---------------------------------------------------------------------------

def test_save_parameters_empty_parm_widgets_is_noop():
    ps = make_process_step(parm_widgets=[])
    # Should not raise
    ps.save_parameters()


# ---------------------------------------------------------------------------
# Tests: get_code_str
# ---------------------------------------------------------------------------

def _make_test_filter(name, code, parms=None, flags=None, annotate_code=None):
    """Create an ImageFilter for testing. Returns the filter object."""
    if parms is None:
        parms = []
    filt = oc.ImageFilter(name, code, parms, flags=flags)
    if annotate_code is not None:
        filt.annotate_code = annotate_code
    return filt


def _cleanup_filter(name):
    """Remove a test filter from ImageFilterCollection."""
    if name in oc.ImageFilterCollection.image_filters:
        del oc.ImageFilterCollection.image_filters[name]
    if name in oc.ImageFilterCollection.image_filter_names:
        oc.ImageFilterCollection.image_filter_names.remove(name)


def test_get_code_str_image_filter_script_mode():
    fname = "_test_img_script"
    try:
        filt = _make_test_filter(
            fname,
            "{x_output_im} = xstep.source_im.copy()",
            flags=[oc.FLAG_ISBASE],
        )
        ps = make_process_step(
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[],
            parm_values={},
        )
        result = ps.get_code_str(script=True)
        assert "im_in = xstep.source_im.copy()" in result
        assert "im_base = im_in" in result
    finally:
        _cleanup_filter(fname)


def test_get_code_str_image_filter_exec_mode():
    fname = "_test_img_exec"
    try:
        filt = _make_test_filter(
            fname,
            "{x_output_im} = xstep.source_im.copy()",
            flags=[oc.FLAG_ISBASE],
        )
        ps = make_process_step(
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[],
            parm_values={},
        )
        result = ps.get_code_str(script=False)
        assert "xstep.exec_im = xstep.source_im.copy()" in result
        assert "im_base" not in result
    finally:
        _cleanup_filter(fname)


def test_get_code_str_with_data_attrib_int_parameter():
    fname = "_test_int_parm"
    try:
        parm = vdata.DataAttribInt("threshold", "128")
        filt = _make_test_filter(
            fname,
            "{x_output_im} = oc.threshold(im_in, {threshold})",
            parms=[parm],
            flags=[],
        )
        ps = make_process_step(
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[parm],
            parm_values={fname + "_threshold": "42"},
        )
        result = ps.get_code_str(script=True)
        assert "42" in result
    finally:
        _cleanup_filter(fname)


def test_get_code_str_with_annotation_shown():
    fname = "_test_annot_show"
    try:
        annot_parm = vdata.DataAttribBoolean(cvlab.SHOW_ANNOTATION, "True")
        filt = _make_test_filter(
            fname,
            "{x_output_im} = im_in.copy()",
            parms=[annot_parm],
            flags=[],
            annotate_code="annotated = im_in.annotate()\n",
        )
        ps = make_process_step(
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[annot_parm],
            parm_values={fname + "_ShowAnnotation": "True"},
        )
        result = ps.get_code_str(script=True)
        assert "annotate" in result
    finally:
        _cleanup_filter(fname)


def test_get_code_str_with_annotation_hidden():
    fname = "_test_annot_hide"
    try:
        annot_parm = vdata.DataAttribBoolean(cvlab.SHOW_ANNOTATION, "False")
        filt = _make_test_filter(
            fname,
            "{x_output_im} = im_in.copy()",
            parms=[annot_parm],
            flags=[],
            annotate_code="annotated = im_in.annotate()\n",
        )
        ps = make_process_step(
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[annot_parm],
            parm_values={fname + "_ShowAnnotation": "False"},
        )
        result = ps.get_code_str(script=True)
        assert "annotate" not in result
    finally:
        _cleanup_filter(fname)


def test_get_code_str_appends_newline_when_missing():
    fname = "_test_no_newline"
    try:
        filt = _make_test_filter(
            fname,
            "x = 1",  # no trailing newline
            flags=[],
        )
        ps = make_process_step(
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[],
            parm_values={},
        )
        result = ps.get_code_str(script=True)
        assert result.endswith("\n")
    finally:
        _cleanup_filter(fname)


# ---------------------------------------------------------------------------
# Tests: execute_step
# ---------------------------------------------------------------------------

@_with_clean_class_state
def test_execute_step_basic_image_filter():
    """Basic Image filter: exec_im gets populated from source_im."""
    fname = "_test_exec_basic"
    try:
        filt = _make_test_filter(
            fname,
            "{x_output_im} = xstep.source_im.copy()",
            flags=[oc.FLAG_ISBASE],
        )
        source = oc.Image(im=np.zeros((10, 10, 3), dtype=np.uint8), colorcode="BGR")
        ps = make_process_step(
            ix=0,
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[],
            parm_values={},
            source_im=source,
            info_widgets=[
                (MockLabel(), MockLabel()),
                (MockLabel(), MockLabel()),
            ],
        )
        cvlab.ProcessStep.steps = [ps]
        ps.execute_step()
        assert ps.exec_im is not None
        assert ps.exec_im.im.shape == (10, 10, 3)
    finally:
        _cleanup_filter(fname)


@_with_clean_class_state
def test_execute_step_two_step_pipeline():
    """Two-step pipeline: step 1 receives step 0's exec_im as im_in."""
    fname0 = "_test_pipe_s0"
    fname1 = "_test_pipe_s1"
    try:
        filt0 = _make_test_filter(
            fname0,
            "{x_output_im} = xstep.source_im.copy()",
            flags=[oc.FLAG_ISBASE],
        )
        filt1 = _make_test_filter(
            fname1,
            "{x_output_im} = im_in.copy()",
            flags=[],
        )
        source = oc.Image(im=np.zeros((8, 8, 3), dtype=np.uint8), colorcode="BGR")
        step0 = make_process_step(
            ix=0,
            cv_filter_name=fname0,
            cv_specs=filt0,
            parms_specs=[],
            parm_values={},
            source_im=source,
            info_widgets=[],
        )
        step1 = make_process_step(
            ix=1,
            cv_filter_name=fname1,
            cv_specs=filt1,
            parms_specs=[],
            parm_values={},
            info_widgets=[],
        )
        cvlab.ProcessStep.steps = [step0, step1]
        step0.execute_step()
        step1.execute_step()
        assert step1.exec_im is not None
        assert step1.exec_im.im.shape == (8, 8, 3)
    finally:
        _cleanup_filter(fname0)
        _cleanup_filter(fname1)


@_with_clean_class_state
def test_execute_step_runtime_error_shows_traceback():
    """Runtime error in filter code: exec_im is None, deposition shows traceback."""
    fname = "_test_exec_err"
    try:
        filt = _make_test_filter(
            fname,
            "raise ValueError('boom')\n",
            flags=[],
        )
        deposition_label = MockLabel()
        ps = make_process_step(
            ix=0,
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[],
            parm_values={},
            deposition=deposition_label,
            info_widgets=[],
        )
        cvlab.ProcessStep.steps = [ps]
        ps.execute_step()
        assert ps.exec_im is None
        assert "boom" in deposition_label.last_value
    finally:
        _cleanup_filter(fname)


@_with_clean_class_state
def test_execute_step_updates_execution_time():
    """execution_time label gets updated."""
    fname = "_test_exec_time"
    try:
        filt = _make_test_filter(
            fname,
            "pass\n",
            flags=[],
        )
        exec_time_label = MockLabel()
        ps = make_process_step(
            ix=0,
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[],
            parm_values={},
            execution_time=exec_time_label,
            info_widgets=[],
        )
        cvlab.ProcessStep.steps = [ps]
        ps.execute_step()
        assert exec_time_label.last_value is not None
        assert "ms" in exec_time_label.last_value
    finally:
        _cleanup_filter(fname)


@_with_clean_class_state
def test_execute_step_populates_info_widgets():
    """info_widgets get populated from info_data."""
    fname = "_test_exec_info"
    try:
        filt = _make_test_filter(
            fname,
            "pass\n",
            flags=[],
        )
        lbl0 = MockLabel()
        val0 = MockLabel()
        lbl1 = MockLabel()
        val1 = MockLabel()
        ps = make_process_step(
            ix=0,
            cv_filter_name=fname,
            cv_specs=filt,
            parms_specs=[],
            parm_values={},
            info_data=[("Speed", "42"), ("Quality", "High")],
            info_widgets=[(lbl0, val0), (lbl1, val1)],
        )
        cvlab.ProcessStep.steps = [ps]
        ps.execute_step()
        assert lbl0.last_value == "Speed"
        assert val0.last_value == "42"
        assert lbl1.last_value == "Quality"
        assert val1.last_value == "High"
    finally:
        _cleanup_filter(fname)


# ---------------------------------------------------------------------------
# Tests: execute_all_steps
# ---------------------------------------------------------------------------

@_with_clean_class_state
def test_execute_all_steps_calls_each_step():
    """Calls execute_step on each step in ProcessStep.steps."""
    fname = "_test_all_steps"
    try:
        filt = _make_test_filter(
            fname,
            "pass\n",
            flags=[],
        )
        steps = []
        for i in range(3):
            ps = make_process_step(
                ix=i,
                cv_filter_name=fname,
                cv_specs=filt,
                parms_specs=[],
                parm_values={},
                info_widgets=[],
            )
            steps.append(ps)
        cvlab.ProcessStep.steps = steps
        # execute_all_steps is a classmethod
        cvlab.ProcessStep.execute_all_steps()
        # Each step should have had its execution_time set
        for ps in steps:
            assert ps.execution_time.last_value is not None
            assert "ms" in ps.execution_time.last_value
    finally:
        _cleanup_filter(fname)


# ---------------------------------------------------------------------------
# Tests: CvLab.do_cameraman_pic_ready
# ---------------------------------------------------------------------------

def test_do_cameraman_pic_ready_stores_payload():
    dr = object.__new__(cvlab.CvLab)
    dr.last_pic_payload = None
    payload = {"filename": "test.jpg", "iso": 800}
    dr.do_cameraman_pic_ready(payload)
    assert dr.last_pic_payload is payload


def test_do_cameraman_pic_ready_overwrites_previous():
    dr = object.__new__(cvlab.CvLab)
    dr.last_pic_payload = {"old": True}
    new_payload = {"filename": "new.jpg"}
    dr.do_cameraman_pic_ready(new_payload)
    assert dr.last_pic_payload is new_payload
    assert "old" not in dr.last_pic_payload


# ---------------------------------------------------------------------------
# Tests: .drk file format parsing
# ---------------------------------------------------------------------------

def test_drk_parse_slash_prefix_becomes_filter_name(tmp_path):
    """'/' prefix lines become filter names."""
    drk_file = tmp_path / "test.drk"
    drk_file.write_text("/Image\nparm.Image_threshold=42\n")
    # Parse manually the same way load_process_file does
    filters = []
    current_filter = None
    current_parms = {}
    f = open(str(drk_file), "r")
    for ln in f:
        ln = ln.strip()
        if ln == "":
            continue
        if ln[0] == "/":
            if current_filter is not None:
                filters.append((current_filter, dict(current_parms)))
                current_parms = {}
            current_filter = ln[1:]
        else:
            sep = ln.find("=")
            if sep > 0:
                key = ln[:sep][5:]  # eliminate "parm." prefix
                value = ln[sep + 1:]
                current_parms[key] = value
    if current_filter is not None:
        filters.append((current_filter, dict(current_parms)))
    f.close()
    assert len(filters) == 1
    assert filters[0][0] == "Image"


def test_drk_parse_parm_key_value(tmp_path):
    """'parm.key=value' lines parse correctly (strips 5-char 'parm.' prefix)."""
    drk_file = tmp_path / "test.drk"
    drk_file.write_text("/MyFilter\nparm.threshold=128\nparm.mode=fast\n")
    filters = []
    current_filter = None
    current_parms = {}
    f = open(str(drk_file), "r")
    for ln in f:
        ln = ln.strip()
        if ln == "":
            continue
        if ln[0] == "/":
            if current_filter is not None:
                filters.append((current_filter, dict(current_parms)))
                current_parms = {}
            current_filter = ln[1:]
        else:
            sep = ln.find("=")
            if sep > 0:
                key = ln[:sep][5:]
                value = ln[sep + 1:]
                current_parms[key] = value
    if current_filter is not None:
        filters.append((current_filter, dict(current_parms)))
    f.close()
    assert filters[0][1] == {"threshold": "128", "mode": "fast"}


def test_drk_parse_empty_lines_skipped(tmp_path):
    """Empty/whitespace lines are skipped."""
    drk_file = tmp_path / "test.drk"
    drk_file.write_text("/FilterA\n\n   \n/FilterB\n")
    filters = []
    current_filter = None
    current_parms = {}
    f = open(str(drk_file), "r")
    for ln in f:
        ln = ln.strip()
        if ln == "":
            continue
        if ln[0] == "/":
            if current_filter is not None:
                filters.append((current_filter, dict(current_parms)))
                current_parms = {}
            current_filter = ln[1:]
        else:
            sep = ln.find("=")
            if sep > 0:
                key = ln[:sep][5:]
                value = ln[sep + 1:]
                current_parms[key] = value
    if current_filter is not None:
        filters.append((current_filter, dict(current_parms)))
    f.close()
    assert len(filters) == 2
    assert filters[0][0] == "FilterA"
    assert filters[1][0] == "FilterB"
