import numpy as np
import pytest

from vnavslib import easytk


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_container(**overrides):
    """Create a TkWidgetDef with container defaults, bypassing __init__."""
    c = object.__new__(easytk.TkWidgetDef)
    c.is_container = True
    c.right_col = 0
    c.bottom_row = 0
    c.last_used_row = -1
    c.last_used_col = -1
    c.last_used_rowspan = 1
    c.last_used_colspan = 1
    c.debug_this = None
    for key, value in overrides.items():
        setattr(c, key, value)
    return c


def make_widget():
    """Create a bare TkWidgetDef to use as a placed child widget."""
    w = object.__new__(easytk.TkWidgetDef)
    w.row = None
    w.col = None
    w.row_span = 0
    w.col_span = 0
    w.debug_this = None
    return w


# ---------------------------------------------------------------------------
# _position() tests
# ---------------------------------------------------------------------------


class TestPositionRowConstants:
    def test_first_row(self):
        c = make_container()
        row, col = c._position(row=easytk.FIRST_ROW, col=easytk.SAME_COL)
        assert row == 0

    def test_same_row_initial_becomes_zero(self):
        c = make_container()
        row, _ = c._position(row=easytk.SAME_ROW, col=easytk.SAME_COL)
        assert row == 0
        assert c.last_used_row == 0

    def test_same_row_subsequent_stays_current(self):
        c = make_container(last_used_row=3)
        row, _ = c._position(row=easytk.SAME_ROW, col=easytk.SAME_COL)
        assert row == 3

    def test_next_row_from_initial(self):
        c = make_container()
        row, _ = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        # last_used_row=-1, last_used_rowspan=1 → row = -1 + 1 = 0
        assert row == 0

    def test_next_row_advances(self):
        c = make_container(last_used_row=2, last_used_rowspan=1)
        row, _ = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        assert row == 3

    def test_next_row_accounts_for_rowspan(self):
        c = make_container(last_used_row=1, last_used_rowspan=3)
        row, _ = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        assert row == 4

    def test_next_row_resets_rowspan(self):
        c = make_container(last_used_row=0, last_used_rowspan=5)
        c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        assert c.last_used_rowspan == 1

    def test_next_row_resets_col_state(self):
        c = make_container(last_used_row=0, last_used_col=3, last_used_colspan=2)
        c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        assert c.last_used_col == 0  # SAME_COL fixup after reset to -1
        assert c.last_used_colspan == 1

    def test_bottom_row(self):
        c = make_container(bottom_row=7)
        row, _ = c._position(row=easytk.BOTTOM_ROW, col=easytk.SAME_COL)
        assert row == 7

    def test_extend_row(self):
        c = make_container(bottom_row=4)
        row, _ = c._position(row=easytk.EXTEND_ROW, col=easytk.SAME_COL)
        assert row == 5

    def test_overlay_row(self):
        c = make_container(last_used_row=2, last_used_col=3)
        row, col = c._position(row=easytk.OVERLAY_ROW, col=easytk.SAME_COL)
        assert row == 2
        assert col == 3  # OVERLAY forces col to OVERLAY_COL too


class TestPositionColConstants:
    def test_same_col_initial_becomes_zero(self):
        c = make_container()
        _, col = c._position(row=easytk.FIRST_ROW, col=easytk.SAME_COL)
        assert col == 0
        assert c.last_used_col == 0

    def test_same_col_subsequent_stays_current(self):
        c = make_container(last_used_col=5)
        _, col = c._position(row=easytk.FIRST_ROW, col=easytk.SAME_COL)
        assert col == 5

    def test_next_col(self):
        c = make_container(last_used_col=1, last_used_colspan=2)
        _, col = c._position(row=easytk.FIRST_ROW, col=easytk.NEXT_COL)
        assert col == 3

    def test_right_col(self):
        c = make_container(right_col=6)
        _, col = c._position(row=easytk.FIRST_ROW, col=easytk.RIGHT_COL)
        assert col == 6

    def test_left_col_same_as_same_col(self):
        # LEFT_COL == SAME_COL == -1, so LEFT_COL hits the SAME_COL branch
        assert easytk.LEFT_COL == easytk.SAME_COL
        c = make_container(last_used_col=4)
        _, col = c._position(row=easytk.FIRST_ROW, col=easytk.LEFT_COL)
        assert col == 4  # behaves like SAME_COL

    def test_extend_col(self):
        c = make_container(right_col=3)
        _, col = c._position(row=easytk.FIRST_ROW, col=easytk.EXTEND_COL)
        assert col == 4

    def test_overlay_col_forces_both(self):
        c = make_container(last_used_row=5, last_used_col=2)
        row, col = c._position(row=easytk.FIRST_ROW, col=easytk.OVERLAY_COL)
        # OVERLAY_COL triggers both row and col to overlay
        assert row == 5
        assert col == 2


class TestPositionPositiveValues:
    def test_positive_row_passes_through(self):
        c = make_container()
        row, _ = c._position(row=7, col=easytk.SAME_COL)
        assert row == 7

    def test_positive_col_passes_through(self):
        c = make_container()
        _, col = c._position(row=easytk.FIRST_ROW, col=4)
        assert col == 4

    def test_zero_row_col_pass_through(self):
        c = make_container()
        row, col = c._position(row=0, col=0)
        assert row == 0
        assert col == 0


class TestPositionOverlayInteraction:
    def test_overlay_row_only_forces_both(self):
        c = make_container(last_used_row=3, last_used_col=2)
        row, col = c._position(row=easytk.OVERLAY_ROW, col=easytk.NEXT_COL)
        assert row == 3
        assert col == 2  # col forced to OVERLAY_COL despite NEXT_COL

    def test_overlay_col_only_forces_both(self):
        c = make_container(last_used_row=4, last_used_col=1)
        row, col = c._position(row=easytk.NEXT_ROW, col=easytk.OVERLAY_COL)
        assert row == 4
        assert col == 1  # row forced to OVERLAY_ROW despite NEXT_ROW


# ---------------------------------------------------------------------------
# _remember_position() tests
# ---------------------------------------------------------------------------


class TestRememberPosition:
    def test_sets_widget_position(self):
        c = make_container()
        w = make_widget()
        c._remember_position(w, row=2, col=3, colspan=2, rowspan=1)
        assert w.row == 2
        assert w.col == 3
        assert w.col_span == 2
        assert w.row_span == 1

    def test_updates_container_last_used(self):
        c = make_container()
        w = make_widget()
        c._remember_position(w, row=1, col=2, colspan=3, rowspan=1)
        assert c.last_used_row == 1
        assert c.last_used_col == 2
        assert c.last_used_colspan == 3

    def test_expands_right_col(self):
        c = make_container(right_col=2)
        w = make_widget()
        c._remember_position(w, row=0, col=3, colspan=2)
        # new_widget_right_col = 3 + 2 - 1 = 4
        assert c.right_col == 4

    def test_no_shrink_right_col(self):
        c = make_container(right_col=5)
        w = make_widget()
        c._remember_position(w, row=0, col=0, colspan=1)
        assert c.right_col == 5

    def test_expands_bottom_row(self):
        c = make_container(bottom_row=1)
        w = make_widget()
        c._remember_position(w, row=3, col=0, rowspan=2)
        # new_widget_bottom_row = 3 + 2 - 1 = 4
        assert c.bottom_row == 4

    def test_no_shrink_bottom_row(self):
        c = make_container(bottom_row=10)
        w = make_widget()
        c._remember_position(w, row=0, col=0)
        assert c.bottom_row == 10

    def test_rowspan_tracks_max_in_row(self):
        c = make_container()
        w1 = make_widget()
        c._remember_position(w1, row=0, col=0, rowspan=3)
        assert c.last_used_rowspan == 3
        # second widget in same row with smaller rowspan: max is preserved
        w2 = make_widget()
        c._remember_position(w2, row=0, col=1, rowspan=1)
        assert c.last_used_rowspan == 3

    def test_rowspan_increases_for_taller_widget(self):
        c = make_container()
        w1 = make_widget()
        c._remember_position(w1, row=0, col=0, rowspan=2)
        assert c.last_used_rowspan == 2
        w2 = make_widget()
        c._remember_position(w2, row=0, col=1, rowspan=5)
        assert c.last_used_rowspan == 5

    def test_default_colspan_rowspan(self):
        c = make_container()
        w = make_widget()
        c._remember_position(w, row=0, col=0)
        assert w.col_span == 1
        assert w.row_span == 1

    def test_requires_container(self):
        c = make_container(is_container=False)
        w = make_widget()
        with pytest.raises(AssertionError):
            c._remember_position(w, row=0, col=0)


# ---------------------------------------------------------------------------
# Integration: sequential layout
# ---------------------------------------------------------------------------


class TestSequentialLayout:
    def test_row_by_row_grid(self):
        """Simulate placing 3 widgets in a 3-row, 1-column layout."""
        c = make_container()
        for expected_row in range(3):
            row, col = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
            assert row == expected_row
            assert col == 0
            w = make_widget()
            c._remember_position(w, row, col)

    def test_two_columns_per_row(self):
        """Place widgets in a 2-row x 2-col grid."""
        c = make_container()
        positions = []
        for r in range(2):
            row, col = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
            w = make_widget()
            c._remember_position(w, row, col)
            positions.append((row, col))

            row2, col2 = c._position(row=easytk.SAME_ROW, col=easytk.NEXT_COL)
            w2 = make_widget()
            c._remember_position(w2, row2, col2)
            positions.append((row2, col2))

        assert positions == [(0, 0), (0, 1), (1, 0), (1, 1)]

    def test_multi_row_span_advances_correctly(self):
        """A widget with rowspan=3 means NEXT_ROW jumps past it."""
        c = make_container()
        row, col = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        w = make_widget()
        c._remember_position(w, row, col, rowspan=3)
        assert row == 0

        row2, col2 = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        assert row2 == 3  # jumped past the 3-row span

    def test_extent_growth(self):
        """bottom_row and right_col grow as widgets are placed."""
        c = make_container()
        w1 = make_widget()
        r, co = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        c._remember_position(w1, r, co, colspan=2)
        assert c.right_col == 1
        assert c.bottom_row == 0

        w2 = make_widget()
        r2, co2 = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        c._remember_position(w2, r2, co2, colspan=3, rowspan=2)
        assert c.right_col == 2
        assert c.bottom_row == 2

    def test_colspan_two_then_next_col(self):
        """NEXT_COL after a colspan=2 widget should skip past it."""
        c = make_container()
        row, col = c._position(row=easytk.NEXT_ROW, col=easytk.SAME_COL)
        w1 = make_widget()
        c._remember_position(w1, row, col, colspan=2)

        _, col2 = c._position(row=easytk.SAME_ROW, col=easytk.NEXT_COL)
        assert col2 == 2  # 0 + 2 = 2


# ---------------------------------------------------------------------------
# Notebook.tab_ix() tests
# ---------------------------------------------------------------------------


def make_notebook():
    """Create a Notebook instance without Tkinter, using object.__new__()."""
    nb = object.__new__(easytk.Notebook)
    nb.tab_frames = ["frame_a", "frame_b", "frame_c"]
    nb.tab_labels_tk = [".nb.tab0", ".nb.tab1", ".nb.tab2"]
    nb.tab_labels_widget = ["widget_a", "widget_b", "widget_c"]
    nb.tab_labels_text = ["Alpha", "Beta", "Gamma"]
    return nb


class TestNotebookTabIx:
    def test_lookup_by_valid_int(self):
        nb = make_notebook()
        assert nb.tab_ix(0) == 0
        assert nb.tab_ix(1) == 1
        assert nb.tab_ix(2) == 2

    def test_int_out_of_range_falls_through(self):
        nb = make_notebook()
        # Negative int or too-large int should not match as index;
        # falls through to list searches. If not found, raises ValueError.
        with pytest.raises(ValueError):
            nb.tab_ix(99)

    def test_negative_int_falls_through(self):
        nb = make_notebook()
        with pytest.raises(ValueError):
            nb.tab_ix(-1)

    def test_lookup_by_frame(self):
        nb = make_notebook()
        assert nb.tab_ix("frame_b") == 1

    def test_lookup_by_tk_widget_id(self):
        nb = make_notebook()
        assert nb.tab_ix(".nb.tab2") == 2

    def test_lookup_by_widget_object(self):
        nb = make_notebook()
        assert nb.tab_ix("widget_a") == 0

    def test_lookup_by_text_caption(self):
        nb = make_notebook()
        assert nb.tab_ix("Beta") == 1

    def test_unknown_raises_value_error(self):
        nb = make_notebook()
        with pytest.raises(ValueError):
            nb.tab_ix("NoSuchTab")


class TestNotebookTabs:
    def test_tabs_returns_labels(self):
        nb = make_notebook()
        assert nb.tabs() == ["Alpha", "Beta", "Gamma"]


# ---------------------------------------------------------------------------
# make_thumbnail() geometry tests
# ---------------------------------------------------------------------------


class TestMakeThumbnail:
    def _make_tkwd(self):
        w = object.__new__(easytk.TkWidgetDef)
        w.debug_this = None
        return w

    def test_none_returns_none(self):
        w = self._make_tkwd()
        assert w.make_thumbnail(None, 100) is None

    def test_landscape_resize(self):
        w = self._make_tkwd()
        im = np.zeros((100, 200, 3), dtype=np.uint8)
        result = w.make_thumbnail(im, 50)
        assert result.shape == (25, 50, 3)

    def test_portrait_resize(self):
        w = self._make_tkwd()
        im = np.zeros((400, 200, 3), dtype=np.uint8)
        result = w.make_thumbnail(im, 100)
        assert result.shape == (200, 100, 3)

    def test_grayscale_image(self):
        w = self._make_tkwd()
        im = np.zeros((80, 160), dtype=np.uint8)
        result = w.make_thumbnail(im, 40)
        assert result.shape == (20, 40)

    def test_square_image(self):
        w = self._make_tkwd()
        im = np.zeros((300, 300, 3), dtype=np.uint8)
        result = w.make_thumbnail(im, 150)
        assert result.shape == (150, 150, 3)
