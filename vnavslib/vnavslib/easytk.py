import cv2
from PIL import ImageTk, Image
import os
import sys

import tkinter
import tkinter.ttk
import tkinter.scrolledtext as ScrolledText
import tkinter.filedialog as tkFileDialog

try:
    import OpticChiasm
except:
    OpticChiasm = None

FIRST_ROW = 0
SAME_ROW = -1
NEXT_ROW = -2
BOTTOM_ROW = -3
EXTEND_ROW = -4
OVERLAY_ROW = -5
SAME_COL = -1
NEXT_COL = -2
RIGHT_COL = -3
LEFT_COL = -1
EXTEND_COL = -4
OVERLAY_COL = -5
COL_SPAN_ALL = -1


#
# Notebook - substitute for ttk.Notebook
# 	Intended to work identically, except for styling
#
class Notebook(tkinter.Frame):
    def __init__(self, master):
        tkinter.Frame.__init__(self, master)
        self.content_tabs_frame = tkinter.Frame(self)
        self.content_tabs_frame.grid(column=0, row=0)
        self.tab_labels_text = []
        self.tab_labels_widget = []
        self.tab_labels_tk = []
        self.tab_frames = []
        self.content_frame = tkinter.Frame(self)
        self.content_frame.grid(column=0, row=1)
        self.selected_tab = None

    def add(self, frame, text=None, where=None):
        print("Notebook.add()", text)
        ix = len(self.tab_labels_text)
        if text is None:
            text = "Tab {}".format(ix + 1)
        label = tkinter.Label(self.content_tabs_frame, text=text)
        label.bind("<Button-1>", self.on_tab_click)
        if where is None:
            self.tab_labels_text.append(text)
            self.tab_labels_widget.append(label)
            self.tab_labels_tk.append(label._w)
            self.tab_frames.append(frame)
        else:
            ix = self.tab_ix(where)
            self.tab_labels_text.insert(ix, text)
            self.tab_labels_widget.insert(ix, label)
            self.tab_labels_tk.insert(ix, label._w)
            self.tab_frames.insert(ix, frame)
        frame.grid(column=0, row=1)
        for label_col in range(ix, len(self.tab_labels_text)):
            self.tab_labels_widget[label_col].grid(column=label_col, row=0)
        # The new tab is not visible, unless its the first tab.
        # This is the behavior of ttk.Notebook.
        # We cannot run select() immediately because the client (cvlab)
        # won't get it. Waiting for 100 is too short. after_idle() didn't solve.
        # ttk.Notebook does something with the same effect and cvlab depends on
        # that. In general, it seems to make sense to assure that the client
        # applications gets the initial select event.
        if len(self.tab_labels_text) == 1:
            self.after(500, self.select, text)
        else:
            frame.lower()

    def enable_traversal(self):
        pass

    def forget(self, tabid):
        ix = self.tab_ix(tabid)
        print("Notebook.forget() BEGIN", tabid, ix)
        #
        # Select another tab before deleting this
        #
        if ix == (len(self.tab_frames) - 1):
            select_ix = ix - 1  # this is last, so select previous tab
        else:
            select_ix = ix + 1  # select the next tab
        tab = self.tab_frames[select_ix]
        tab.lift()
        #
        # Delete this tab
        #
        label = self.tab_labels_widget[ix]
        frame = self.tab_frames[ix]
        self.tab_labels_text.pop(ix)
        self.tab_labels_widget.pop(ix)
        self.tab_labels_tk.pop(ix)
        self.tab_frames.pop(ix)
        label.destroy()
        frame.destroy()
        # The event must be generated last because the handler get executed immediately.
        # Before the method completes execution.
        self.event_generate("<<NotebookTabChanged>>")
        print("Notebook.forget() END")

    def insert(self, where, frame, text=None):
        self.add(frame, text=text, where=where)

    def select(self, tabid=None):
        if tabid is None:
            return self.tab_labels_text[self.selected_tab]
        ix = self.tab_ix(tabid)
        print("Notebook.select()", ix, self.tab_labels_text[ix])
        self.selected_tab = ix
        tab = self.tab_frames[ix]
        tab.lift()
        # The event must be generated last because the handler get executed immediately.
        # Before the method completes execution.
        self.event_generate("<<NotebookTabChanged>>")
        return tab

    def tab(self, tabid, **kw):
        ix = self.tab_ix(tabid)
        for key, new_value in kw.items():
            if key == "text":
                self.tab_labels_widget[ix].config(text=new_value)

    def tab_ix(self, tabid):
        #
        # Not all these matches are used
        #   self.tab_labels_tk is used by event handlers as event.widget.
        #     It is probably the C++ widget id. It is found in tkinter widget
        #     attribute _w.
        #   self.tab_labels_text is the tab caption. It is used as the tabid
        #     for select() and OnTabSelected events.
        #   self.tab_frames is the tab content frame. It is used in cvlab
        #     to select the tab for a process step.
        #
        # The above were in use by cvlab and mission_control using
        # ttk.Notebook. This works identically.
        #
        if isinstance(tabid, int):
            if (tabid >= 0) and (tabid < len(self.tab_frames)):
                return tabid
        try:
            return self.tab_frames.index(tabid)
        except ValueError:
            pass
        except:
            raise
        try:
            return self.tab_labels_tk.index(tabid)
        except ValueError:
            pass
        except:
            raise
        try:
            return self.tab_labels_widget.index(tabid)
        except ValueError:
            pass
        except:
            raise
        return self.tab_labels_text.index(tabid)

    def tabs(self):
        return self.tab_labels_text

    def on_tab_click(self, event):
        print("Notebook.on_tab_click()", event.widget)
        """
        for this in self.tab_labels_widget:
            print(">>>")
            for that in dir(this):
                print("   ", that, ":", getattr(this, that))
        """
        self.select(tabid=event.widget)


#
# ScrolledFrame - A child of Frame with scroll bars
#
# Adapted from http://code.activestate.com/recipes/580793-tkinter-table-with-scrollbars/
#
"""
    def __init__(self, master, columns, column_weights=None, column_minwidths=None, height=500, minwidth=20, minheight=20, padx=5, pady=5, cell_font=None, cell_foreground="black", cell_background="white", cell_anchor=W, header_font=None, header_background="white", header_foreground="black", header_anchor=CENTER, bordercolor = "#999999", innerborder=True, outerborder=True, stripped_rows=("#EEEEEE", "white"), on_change_data=None, mousewheel_speed = 2, scroll_horizontally=False, scroll_vertically=True):
"""


class ScrolledFrame(tkinter.Frame):
    def __init__(
        self,
        HeadingRow=False,
        HeadingColumn=False,
        bordercolor="#999999",
        outerborder=True,
        scroll_horizontally=False,
        scroll_vertically=True,
    ):
        super().__init__()
        outerborder_width = 1 if outerborder else 0
        self.heading_frame = tkinter.Frame(
            self,
            highlightbackground=bordercolor,
            highlightcolor=bordercolor,
            highlightthickness=outerborder_width,
            bd=0,
        )
        self.heading_frame.grid(row=0, column=0, sticky=tkinter.E + tkinter.W)
        if scroll_horizontally:
            xscrollbar = Scrollbar(self, orient=HORIZONTAL)
            xscrollbar.grid(row=2, column=0, sticky=E + W)
        else:
            xscrollbar = None

        if scroll_vertically:
            yscrollbar = Scrollbar(self, orient=VERTICAL)
            yscrollbar.grid(row=1, column=1, sticky=N + S)
        else:
            yscrollbar = None


class TkWidgetDef:
    __slots__ = (
        "bottom_row",
        "canvas_height",
        "canvas_width",
        "children",
        "col",
        "col_span",
        "debug_this",
        "file_opt",
        "hbar",
        "is_container",
        "is_initializing",
        "last_used_col",
        "last_used_colspan",
        "last_used_row",
        "last_used_rowspan",
        "list_items",
        "opencv_im",
        "parent",
        "parm_id",
        "pil_im",
        "pil_resize_ratio",
        "rgb_im",
        "right_col",
        "row",
        "row_span",
        "scroll_container",
        "scrollable_image",
        "table",
        "thumbnail",
        "thumbnail_of",
        "thumbnail_width",
        "tkd",
        "tkw",
        "tkw_label",
        "vbar",
        "wname",
    )

    def __init__(
        self,
        wname,
        tkw,
        data=None,
        tkw_label=None,
        parm_id=None,
        is_container=False,
        debug=None,
    ):
        self.is_container = is_container
        self.is_initializing = True
        self.wname = wname  # reference name for this widget
        self.tkw = tkw  # tk widget
        self.tkw_label = tkw_label  # tk widget of associated label
        self.tkd = data  # the tk data (usually StringVar) for this widget
        self.scroll_container = None  # tk frame widget holding tkw plus scrollbars
        self.hbar = None
        self.vbar = None
        self.rgb_im = None
        self.row = None  # row where positioned
        self.col = None  # col where positioned (left side)
        self.right_col = 0  # furthest right colum used
        self.bottom_row = 0  # highest number row used
        self.last_used_row = (
            -1
        )  # not necesarilly, highest used. for sequential positioning
        self.last_used_rowspan = 1
        self.last_used_col = (
            -1
        )  # not necesarilly highest used. for sequential positioning
        self.last_used_colspan = 1
        self.row_span = 0  # height of this TkWidgetDef object (# of rows)
        self.col_span = 0  # width of this TkWidgetDef object (# of columns)
        self.table = None  # table for scrollable table widget.
        self.thumbnail = None  # update this thumbnail if image is changed
        self.thumbnail_of = None  # this is a thumbnail of that image
        self.thumbnail_width = 0  # width of thumbnail
        self.parent = None
        self.children = []
        self.canvas_width = 400
        self.canvas_height = 200
        self.parm_id = (
            parm_id  # associated application field, not directly used for TK stuff
        )
        self.pil_resize_ratio = None
        self.debug_this = debug
        self.file_opt = {}
        self.file_opt["defaultextension"] = ".txt"
        # specifying file types on OSX seems limit what can be selected
        # osx doesn't have an option to select the file categories
        # self.file_opt['filetypes'] = [('all files', '.*'), ('text files', '.txt')]
        self.file_opt["initialdir"] = "C:\\"
        self.file_opt["initialfile"] = "myfile.txt"
        self.file_opt["title"] = "This is a title"

    def file_dialog_parms(self, file_name=None, directory=None, file_types=None):
        self.file_opt["parent"] = self.tkw
        if file_name is not None:
            self.file_opt["initialfile"] = file_name
        if directory is not None:
            self.file_opt["initialdir"] = directory
        if file_types is not None:
            self.file_opt["filetypes"] = file_types

    def do_file_name_dialog(self, directory=None, file_types=None):
        self.file_dialog_parms(directory=directory, file_types=file_types)
        return tkFileDialog.askopenfilename(**self.file_opt)

    def do_file_save_as_name_dialog(self, file_name=None, directory=None, file_types=None):
        self.file_dialog_parms(file_name=file_name, directory=directory, file_types=file_types)
        return tkFileDialog.asksaveasfilename(**self.file_opt)

    def do_file_open_dialog(self, mode="r", directory=None, file_types=None):
        self.file_dialog_parms(directory=directory, file_types=file_types)
        return tkFileDialog.askopenfile(mode=mode, **self.file_opt)

    def add_button(
        self, caption, command, width=None, padx=None, row=NEXT_ROW, col=SAME_COL
    ):
        if self.debug_this:
            print("add_button", row, col, caption)
        row, col = self._position(row=row, col=col)
        refname = caption.lower().replace(" ", "_")
        options = {}
        options["text"] = caption
        options["command"] = command
        if width is not None:
            options["width"] = width
        if padx is not None:
            options["padx"] = padx
        frame = TkWidgetDef(refname, tkinter.Button(self.tkw, **options))
        frame.tkw.grid(row=row, column=col)
        self._remember_position(frame, row, col)
        self.append_child(frame)
        return frame

    def append_child(self, frame):
        self.children.append(frame)
        frame.parent = self

    def add_canvas(
        self,
        pil_fn=None,
        rgb_im=None,
        opencv_fn=None,
        on_click=None,
        thumbnailof=None,
        thumbnailwidth=100,
        width=400,
        height=200,
        row=NEXT_ROW,
        col=SAME_COL,
        colspan=1,
        rowspan=1,
    ):
        frame = self._add_scrolled_widget(
            tkinter.Canvas,
            {"width": width, "height": height},
            on_click=on_click,
            row=row,
            col=col,
            rowspan=rowspan,
            xscroll=True,
        )
        frame.scrollable_image = None
        frame.canvas_width = width
        frame.canvas_height = height

        if (pil_fn is not None) or (opencv_fn is not None) or (rgb_im is not None):
            if thumbnailof is None:
                frame.update_image(pil_fn=pil_fn, rgb_im=rgb_im, opencv_fn=opencv_fn)
            else:
                # after this, the thumbnail will be automatically updated whenever the base image is updated
                frame.update_image(
                    rgb_im=self.make_thumbnail(thumbnailof.rgb_im, thumbnailwidth)
                )
                thumbnailof.thumbnail = frame
                thumbnailof.thumbnail_width = thumbnailwidth
                self.thumbnail_of = thumbnailof
        return frame

    def add_dropdown(
        self,
        caption=None,
        s_items=["None"],
        selection=None,
        row=NEXT_ROW,
        col=SAME_COL,
        command=None,
    ):
        # If command is specified, this uses variable trace to provide an on_change event.
        # The callback supplies three paramters that are meaningful to tk but not useful to the application,
        # so the callback declarations should be something like "def command(self, *args).
        # I am leaving this as a required idiom when using easytk. There is something to be said for creating
        # an OnChange event for easytk, but I would then have to track more tk internals in order to identify
        # the control that changed.
        #
        # If s_items is an empty list, tkinter.OptionMenu() raises the confusing exception:
        #     TypeError: __init__() takes at least 4 arguments (3 given)
        #
        if self.debug_this:
            print("add_dropdown", row, col, caption)
        row, col = self._position(row=row, col=col)
        if caption is None:
            refname = "QWE"
            tk_caption = None
            entry_col = col
            remember_colspan = 1
        else:
            refname = caption.lower().replace(" ", "_")
            tk_caption = tkinter.Label(self.tkw, text=caption)
            tk_caption.grid(column=col, row=row, sticky=tkinter.W)
            entry_col = col + 1
            remember_colspan = 2

        tk_data = tkinter.StringVar()
        tk_data.set(selection)
        if command is not None:
            tk_data.trace("w", command)
        args = [self.tkw, tk_data] + s_items
        tk_entry = tkinter.OptionMenu(*args)
        tk_entry.grid(column=entry_col, row=row, sticky=(tkinter.W, tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_caption, data=tk_data)
        self._remember_position(frame, row, col, colspan=remember_colspan)
        self.append_child(frame)
        return frame

    def add_entry_field(
        self,
        caption=None,
        width=10,
        value="",
        row=NEXT_ROW,
        col=SAME_COL,
        on_double_click=None,
    ):
        if self.debug_this:
            print("add_entry_field", row, col, caption)
        row, col = self._position(row=row, col=col)

        tk_data = tkinter.StringVar()
        tk_data.set(value)
        if caption is None:
            col_span = 1
            tk_caption = None
            refname = "EntryBox"
        else:
            tk_caption = tkinter.Label(self.tkw, text=caption)
            tk_caption.grid(column=col, row=row, sticky=tkinter.W)
            col_span = 2
            refname = caption.lower().replace(" ", "_")
        tk_entry = tkinter.Entry(self.tkw, width=width, textvariable=tk_data)
        tk_entry.grid(column=col + 1, row=row, sticky=(tkinter.W, tkinter.E))
        if on_double_click is not None:
            tk_entry.bind("<Double-Button-1>", on_double_click)
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_caption, data=tk_data)
        self._remember_position(frame, row, col, colspan=col_span)
        self.append_child(frame)
        return frame

    def add_checkbox(self, caption=None, value=False, row=NEXT_ROW, col=SAME_COL):
        if self.debug_this:
            print("add_checkbox", row, col, caption)
        row, col = self._position(row=row, col=col)

        tk_data = tkinter.IntVar()
        if value:
            tk_data.set(1)
        else:
            tk_data.set(0)
        if caption is None:
            refname = "Checkbox"
        else:
            refname = caption.lower().replace(" ", "_")
        tk_entry = tkinter.Checkbutton(self.tkw, text=caption, variable=tk_data)
        tk_entry.grid(column=col, row=row, sticky=(tkinter.W, tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, data=tk_data)
        self._remember_position(frame, row, col, colspan=1)
        self.append_child(frame)
        return frame

    def add_frame(self, row=NEXT_ROW, col=SAME_COL, colspan=1):
        if self.debug_this:
            print("add_frame", row, col, colspan)
        row, col = self._position(row=row, col=col)
        refname = "X"
        frame = TkWidgetDef(refname, tkinter.Frame(self.tkw), is_container=True)
        if colspan == COL_SPAN_ALL:
            colspan = self.right_col - col + 1
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=tkinter.W)
        self._remember_position(frame, row, col, colspan=colspan)
        self.append_child(frame)
        return frame

    def add_label(self, text="", width=10, row=NEXT_ROW, col=SAME_COL):
        # An alternate method would be to create a TK StringVar and when creating the label
        # use the textvariable property instead of text. Visually this shouldn't be any different.
        # The update process would be a bit different in some cases because the label would
        # be automagically updated if something changed the variable.
        refname = "X"
        row, col = self._position(row=row, col=col)
        tk_caption = tkinter.Label(self.tkw, text=text)
        tk_caption.grid(column=col, row=row, sticky=tkinter.W)
        frame = TkWidgetDef(refname, tk_caption)
        self._remember_position(frame, row, col)
        self.append_child(frame)
        return frame

    def add_label_frame(self, caption, row=NEXT_ROW, col=SAME_COL, colspan=1):
        row, col = self._position(row=row, col=col)
        refname = caption.lower().replace(" ", "_")
        frame = TkWidgetDef(
            refname, tkinter.LabelFrame(self.tkw, text=caption), is_container=True
        )
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=tkinter.W)
        self._remember_position(frame, row, col, colspan=colspan)
        self.append_child(frame)
        return frame

    def add_label_image(
        self,
        pil_fn=None,
        opencv_im=None,
        opencv_fn=None,
        thumbnailof=None,
        thumbnailwidth=100,
        row=NEXT_ROW,
        col=SAME_COL,
        colspan=1,
    ):
        row, col = self._position(row=row, col=col)
        frame = TkWidgetDef("", tkinter.Label(self.tkw))
        if thumbnailof is None:
            frame.update_image(pil_fn=pil_fn, source_im=opencv_im, opencv_fn=opencv_fn)
        else:
            # after this, the thumbnail will be automatically updated whenever the base image is updated
            frame.update_image(
                rgb_im=self.make_thumbnail(thumbnailof.rgb_im, thumbnailwidth)
            )
            thumbnailof.thumbnail = frame
            thumbnailof.thumbnail_width = thumbnailwidth

        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=tkinter.W)
        self._remember_position(frame, row, col, colspan=colspan)
        self.append_child(frame)
        return frame

    def destroy(self):
        # Clear both sides of thumbnail links to avoid refencing stale references
        if self.thumbnail is not None:
            self.thumbnail.thumbnail_of = None
            self.thumbnail = None
        if self.thumbnail_of is not None:
            self.thumbnail_of.thumbnail = None
            self.thumbnail = None
        for this_child in self.children:
            this_child.destroy()
        if self.parent is not None:
            try:
                self.parent.children.remove(self)
            except:
                print(
                    "destroy() child ",
                    self.tkw.__class__.__name__,
                    "not in parent",
                    self.parent.tkw.__class__.__name__,
                )
                raise
        if self.tkw_label is not None:
            self.tkw_label.destroy()
        if self.tkd is not None:
            if isinstance(self.tkd, ImageTk.PhotoImage):
                self.tkd = None
            else:
                self.tkd.destroy()
        if self.hbar is not None:
            self.hbar.destroy()
        if self.vbar is not None:
            self.vbar.destroy()
        self.tkw.destroy()

    def add_label_info(self, caption, value="", width=10, row=NEXT_ROW, col=SAME_COL):
        # This is much like add_entry_field() but the field is another lable so it is
        # display only.
        row, col = self._position(row=row, col=col)
        tk_data = tkinter.StringVar()
        tk_data.set(value)
        if caption is None:
            col_span = 1
            tk_caption = None
            refname = "LabelInfo"
        else:
            refname = caption.lower().replace(" ", "_")
            tk_caption = tkinter.Label(self.tkw, text=caption)
            tk_caption.grid(column=col, row=row, sticky=tkinter.W)
            col_span = 2
        tk_info = tkinter.Label(self.tkw, textvariable=tk_data)
        tk_info.grid(column=col + 1, row=row, sticky=(tkinter.W, tkinter.E))
        frame = TkWidgetDef(refname, tk_info, tkw_label=tk_caption, data=tk_data)
        self._remember_position(frame, row, col, colspan=col_span)
        self.append_child(frame)
        return frame

    def add_listbox(
        self,
        caption,
        s_items,
        selection=None,
        row=NEXT_ROW,
        col=SAME_COL,
        rowspan=5,
        command=None,
        xscroll=False,
    ):
        frame = self._add_scrolled_widget(
            tkinter.Listbox,
            {"exportselection": 0, "height": rowspan},
            caption=caption,
            row=row,
            col=col,
            rowspan=rowspan,
            xscroll=xscroll,
        )
        for this_item in s_items:
            frame.tkw.insert(tkinter.END, this_item)
        if command is not None:
            frame.tkw.bind("<Double-Button-1>", command)
        if selection is None:
            active_index = 0
        else:
            try:
                active_index = s_items.index(selection)
            except ValueError:
                active_index = 0
        frame.tkw.selection_set(active_index)
        frame.tkw.see(active_index)
        frame.list_items = s_items
        return frame

    def add_scrolled_entry_field(
        self, caption, width=10, height=5, value="", row=NEXT_ROW, col=SAME_COL
    ):
        if self.debug_this:
            print("add_scrolled_entry_field", row, col, caption)
        row, col = self._position(row=row, col=col)
        refname = caption.lower().replace(" ", "_")

        tk_data = tkinter.StringVar()
        tk_data.set(value)
        tk_caption = tkinter.Label(self.tkw, text=caption)
        tk_caption.grid(column=col, row=row, sticky=tkinter.W)
        tk_entry = ScrolledText.ScrolledText(
            master=self.tkw, width=width, height=height, wrap=tkinter.WORD
        )
        tk_entry.grid(column=col + 1, row=row, sticky=(tkinter.W, tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_caption, data=tk_data)
        self._remember_position(frame, row, col, colspan=2, rowspan=height)
        self.append_child(frame)
        return frame

    def add_slider_field(
        self,
        caption=None,
        width=10,
        value=None,
        min_value=0,
        max_value=100,
        orient=tkinter.HORIZONTAL,
        row=NEXT_ROW,
        col=SAME_COL,
    ):
        if self.debug_this:
            print("add_slider_field", row, col, caption)
        # print('Slider', row, col, self.last_used_row, self.last_used_col)
        row, col = self._position(row=row, col=col)
        # print('Slider', row, col, self.last_used_row, self.last_used_col)
        if caption is None:
            refname = "Slider"
            tk_caption = None
        else:
            refname = caption.lower().replace(" ", "_")
            tk_caption = tkinter.Label(self.tkw, text=caption)
            tk_caption.grid(column=col, row=row, sticky=tkinter.W)
        # if specified, label appears above the slider
        # the default showvalue=1 displays the value above the slider, moving with tthe cursor
        tk_entry = tkinter.Scale(
            self.tkw, length=width, from_=min_value, to=max_value, orient=orient
        )
        tk_entry.config(showvalue=0)
        if value is not None:
            tk_entry.set(value)
        tk_entry.grid(column=col + 1, row=row, sticky=(tkinter.W, tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_caption)
        self._remember_position(frame, row, col, colspan=2)
        self.append_child(frame)
        return frame

    def x_make_popup_window(self, title):
        popup = tkinter.Toplevel()
        popup.title(title)

        ksbar = tkinter.Scrollbar(popup, orient=tkinter.VERTICAL)
        ksbar.grid(row=0, column=1, sticky="ns")

        popCanv = tkinter.Canvas(
            popup, width=300, height=300, scrollregion=(0, 0, 500, 800)
        )  # width=1256, height = 1674)
        popCanv.grid(row=0, column=0, sticky=tkinter.W)  # added sticky

        ksbar.config(command=popCanv.yview)
        popCanv.config(yscrollcommand=ksbar.set)

        self.xxopencv_im = cv2.imread("zoom.jpeg")
        self.xximg_pil = Image.fromarray(self.xxopencv_im)
        self.xximg = ImageTk.PhotoImage(self.xximg_pil)  # amended
        image = popCanv.create_image(
            300, 400, image=self.xximg
        )  # correct way of adding an image to canvas
        # popCanv.create_text(420,790,text=source)

        popup.rowconfigure(0, weight=1)  # added (answer to your question)
        popup.columnconfigure(0, weight=1)  # added (answer to your question)

    def make_popup_window(self, title):
        refname = title
        top = tkinter.Toplevel()
        top.title(title)
        frame = TkWidgetDef(refname, top, is_container=True)
        return frame

    #
    # Scrollable Table
    #
    def add_cell(self, text="", row=0, col=0):
        cell = tkinter.Label(self.table, text=text)
        cell.grid(column=col, row=row)

    def add_table(
        self,
        on_click=None,
        width=400,
        height=200,
        xscroll=True,
        row=NEXT_ROW,
        col=SAME_COL,
        colspan=1,
        rowspan=1,
    ):
        # width and height are the size of the visible portion of the canvas
        row, col = self._position(row=row, col=col)
        refname = "T"
        frame = self._add_scrolled_widget(
            tkinter.Canvas,
            {"width": width, "height": height},
            row=0,
            col=0,
            rowspan=1,
            xscroll=xscroll,
        )
        # frame.tkw is a canvas with scroll bars
        # frame.scroll_container is a container for the canvas plus its scroll bars
        frame.table = tkinter.Frame(frame.tkw)
        frame.tkw.create_window(0, 0, window=frame.table, anchor="nw")
        for r in range(50):
            for c in range(5):
                frame.add_cell(text="{}{}".format(chr(ord("A") + c), r), row=r, col=c)
        frame.tkw.update()  # this calculates reqwidth / reqheight (among otehr things)
        frame.tkw.configure(
            scrollregion=(
                0,
                0,
                frame.table.winfo_reqwidth(),
                frame.table.winfo_reqheight(),
            )
        )  # size of logical drawing area
        if colspan == COL_SPAN_ALL:
            colspan = self.right_col - col + 1
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=tkinter.W)
        self._remember_position(frame, row, col, colspan=colspan)
        self.append_child(frame)
        self.is_container = False
        return frame

    #
    # Tabed Notebook Widget
    #
    def add_notebook(self, on_tab_selected=None, row=NEXT_ROW, col=SAME_COL, colspan=1):
        row, col = self._position(row=row, col=col)
        # nb_class = tkinter.ttk.Notebook
        nb_class = Notebook
        frame = TkWidgetDef("", nb_class(self.tkw), is_container=True)
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=tkinter.W)
        frame.tkw.enable_traversal()
        if on_tab_selected is not None:
            frame.tkw.bind("<<NotebookTabChanged>>", on_tab_selected)
        self._remember_position(frame, row, col, colspan=colspan)
        self.append_child(frame)
        return frame

    def delete_tab(self, ix):
        print("TAB CT", len(self.tkw.tabs()))
        self.tkw.forget(ix)
        self.children.pop(ix)

    def add_tab(self, caption, where=None, on_click=None):
        # Add a tab to notebook
        refname = caption.lower().replace(" ", "_")
        frame = TkWidgetDef(refname, tkinter.Frame(self.tkw), is_container=True)
        frame.tkw.grid(sticky=tkinter.NSEW)
        if where is None:
            self.tkw.add(frame.tkw, text=caption)
        else:
            self.tkw.insert(where, frame.tkw, text=caption)
        if on_click is not None:
            frame.tkw.bind("<Button-1>", on_click)
        self.append_child(frame)
        return frame

    #
    # Standardized Operations
    #
    #   TK has lots of idioms for different widgets. The following methods
    #   attempt to standardize them so there is less to remember.
    #

    def create_substitute_image(
        self,
        width,
        height,
        caption=None,
        textcolor=(255, 255, 255),
        text_start_xy=(10, 10),
    ):
        blank_image = np.zeros((height, width, 3), np.uint8)
        if caption is not None:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 4
            line_thickness = 2
            cv2.putText(
                blank_image,
                caption,
                text_start_xy,
                font,
                font_scale,
                textcolor,
                line_thickness,
                cv2.LINE_AA,
            )
        return blank_image

    def focus(self):
        self.tkw.focus()

    def make_thumbnail(self, im, width):
        # im is an OpenCv / numpy buffer. It can be either RGB or BGR. The color format is not changed.
        if im is None:
            return None
        if len(im.shape) > 2:
            ih, iw, ic = im.shape
        else:
            ih, iw = im.shape
            ic = 1
        tw = width
        th = int((tw / iw) * ih)
        t = cv2.resize(im, (tw, th), interpolation=cv2.INTER_LINEAR)
        return t

    def replace_choices(self, choices):
        if isinstance(self.tkw, tkinter.OptionMenu):
            # adpated from https://stackoverflow.com/questions/17580218/changing-the-options-of-a-optionmenu-when-clicking-a-button
            current_selection = self.tkd.get()
            self.tkw["menu"].delete(0, "end")
            for this_choice in choices:
                self.tkw["menu"].add_command(
                    label=this_choice, command=tkinter._setit(self.tkd, this_choice)
                )
            if current_selection in choices:
                self.tkd.set(current_selection)
            else:
                if len(choices) > 0:
                    self.tkd.set(choices[0])

    def replace_value(self, new_value, caption=None):
        debug = "replace_value({0}): tkw {1} '{2}' -- ".format(
            new_value, self.tkw.__class__.__name__, self.value()
        )
        if self.tkd is None:
            debug += "None"
        elif isinstance(self.tkd, tkinter.StringVar):
            debug += "StringVar '{0}".format(self.tkd.get())
        else:
            debug += "{0} '{1}'".format(self.tkd.__class__.__name__, repr(self.tkd))
        # print(debug)

        if isinstance(self.tkw, ScrolledText.ScrolledText):
            self.tkw.delete("1.0", tkinter.END)
            self.tkw.insert("1.0", new_value)
        elif isinstance(self.tkw, tkinter.Label) and (self.tkw_label is None):
            # if self.tkw_label is not None, this is from add_label_info(): update self.tk_data
            self.tkw.config(text=new_value)
        elif isinstance(self.tkw, tkinter.Listbox):
            # clear current selection first, else multi-selection occurs
            cur_selection = self.tkw.curselection()
            self.tkw.select_clear(cur_selection)
            ix = self.list_items.index(new_value)
            self.tkw.selection_set(ix)
            self.tkw.see(ix)
        elif isinstance(self.tkw, tkinter.Scale):
            self.tkw.set(new_value)
        elif isinstance(self.tkw, tkinter.Checkbutton):
            if new_value:
                self.tkd.set(1)
            else:
                self.tkd.set(0)
        else:
            # For many/most widgets, the value is in the self.tkd StringVar
            if isinstance(self.tkd, tkinter.StringVar):
                self.tkd.set(new_value)
        if caption is not None:
            self.tkw_label.config(text=caption)

    def update(self):  # Process tkinter events
        self.is_initializing = False
        self.tkw.update()

    def update_image(self, pil_fn=None, source_im=None, opencv_fn=None, rgb_im=None):
        # Replaces image in Canvas and Label widgets
        # We can have up to 3 stages of image buffers. We keep references to all
        # for debugging and becaues of some strange garbage collection issues with
        # TK images.
        # self.tkd is ImageTk.PhotoImage() which actually gets placed on widget
        # self.pil_im is a Pillow Image() which TK directly uses
        # self.source_im is either an OpenCV buffer or an OpticChiasm.Image for JPEG (or other) files
        #
        self.pil_im = None
        self.rgb_im = None
        if pil_fn is not None:
            try:
                self.pil_im = Image.open(pil_fn)
            except IOError:
                self.pil_im = None
            self.rgb_im = None
        elif rgb_im is not None:
            self.rgb_im = rgb_im
            self.pil_im = Image.fromarray(self.rgb_im)
        elif source_im is not None:
            if self.debug_this:
                print(
                    "update_image() source_im",
                    source_im.__class__.__name__,
                    source_im.shape,
                )
            if (OpticChiasm is None) or (not isinstance(source_im, OpticChiasm.Image)):
                # this is an OpenCv image
                if len(source_im.shape) > 2:
                    self.rgb_im = cv2.cvtColor(source_im, cv2.COLOR_BGR2RGB)
                else:
                    self.rgb_im = cv2.cvtColor(source_im, cv2.COLOR_GRAY2RGB)
            else:
                self.rgb_im = source_im.ImAsRGB()
            self.pil_im = Image.fromarray(self.rgb_im)
        elif opencv_fn is not None:
            print("***", os.getcwd(), opencv_fn)
            opencv_im = cv2.imread(opencv_fn)
            self.rgb_im = cv2.cvtColor(opencv_im, cv2.COLOR_BGR2RGB)
            self.pil_im = Image.fromarray(self.rgb_im)
        #
        if self.pil_im is None:
            print(
                "update_image() unable to create PILLOW image object",
                pil_fn,
                opencv_fn,
                source_im.__class__.__name__,
            )
            # should blank thumbnail here
            return False
        imWidth = self.pil_im.width
        self.pil_resize_ratio = None
        if self.canvas_width < imWidth:
            self.pil_resize_ratio = float(self.canvas_width) / float(imWidth)
            imHeight = self.pil_im.height
            height = int(self.pil_resize_ratio * imHeight)
            self.pil_im = self.pil_im.resize((self.canvas_width, height))
            # print("RESIZE", self.canvas_width, height)
        self.tkd = ImageTk.PhotoImage(self.pil_im)
        if self.tkd is None:
            print("update_image() unable to create TK image object")
            # should blank thumbnail here
            return False
        if isinstance(self.tkw, tkinter.Label):
            self.tkw.configure(image=self.tkd)
        elif isinstance(self.tkw, tkinter.Canvas):
            if self.scrollable_image is None:
                self.scrollable_image = self.tkw.create_image(
                    0, 0, image=self.tkd, anchor="nw"
                )
            else:
                self.tkw.itemconfig(self.scrollable_image, image=self.tkd)
            width, height = self.pil_im.size
            self.tkw.config(scrollregion=(0, 0, width, height))
            pctWidth = float(self.canvas_width) / float(width)
            if pctWidth > 1.0:
                pctWidth = 1.0
            self.hbar.set(0.0, pctWidth)
            pctHeight = self.canvas_height / height
            if pctHeight > 1.0:
                pctHeight = 1.0
            self.vbar.set(0.0, pctHeight)
            if self.debug_this:
                print(
                    "update_image()",
                    self.canvas_width,
                    self.canvas_height,
                    width,
                    height,
                    pctWidth,
                    pctHeight,
                    opencv_fn,
                )
        else:
            raise TypeError("Unsupported image widget: " + self.tkw.__class__.__name__)
        if self.thumbnail:
            return self.thumbnail.update_image(
                rgb_im=self.make_thumbnail(self.rgb_im, self.thumbnail_width)
            )
        else:
            return True

    def value(self):
        if isinstance(self.tkw, ScrolledText.ScrolledText):
            return self.tkw.get("1.0", tkinter.END)
        if isinstance(self.tkw, tkinter.Listbox):
            # ix is a tuple like (2,). I assume the 2nd element would be the end of
            # the range. Or maybe it a list of items for multi-selection.
            # This works for now.
            ix = self.tkw.curselection()
            return self.tkw.get(ix)
        if isinstance(self.tkw, tkinter.Scale):
            return self.tkw.get()
        if isinstance(self.tkw, tkinter.Checkbutton):
            v = self.tkd.get()
            if v:
                return True
            else:
                return False
        # For many/most widgets, the value is in the self.tkd StringVar
        if isinstance(self.tkd, tkinter.StringVar):
            v = self.tkd.get()
            if isinstance(self.tkw, tkinter.OptionMenu) and (v == "None"):
                # I'm not sure if its me or tkinter that turned no selection to a string
                v = None
            # print("value() tkd '{0}'".format(v))
            return v

    #
    # These are internal management functions that simplify and standardize widget coding.
    #

    def _add_scrolled_widget(
        self,
        tk_widget_class,
        tk_widget_parms,
        caption=None,
        on_click=None,
        row=NEXT_ROW,
        col=SAME_COL,
        rowspan=5,
        xscroll=False,
    ):
        # Getting scrolled widgets right is verbose and fussy. I found this technique using a seperate frame and
        # explicit borderwidth and weight on StackOverflow somewhere.
        # The goal is for this tmethod to create any widget that needs scroll bars.
        #
        row, col = self._position(row=row, col=col)

        if caption is None:
            tk_caption = None
            refname = "ZXC"
        else:
            refname = caption.lower().replace(" ", "_")
            tk_caption = tkinter.Label(self.tkw, text=caption)
            tk_caption.grid(column=col, row=row, sticky=tkinter.W)

        container = tkinter.Frame(master=self.tkw, borderwidth=2, relief=tkinter.SUNKEN)
        tkw = tk_widget_class(master=container, borderwidth=0, **tk_widget_parms)
        frame = TkWidgetDef(refname, tkw, tkw_label=tk_caption)
        frame.scroll_container = container  # may be needed to avoid garbage collection

        if xscroll:
            frame.hbar = tkinter.Scrollbar(
                master=frame.scroll_container, orient=tkinter.HORIZONTAL
            )
            frame.hbar.grid(row=1, column=0, sticky=tkinter.E + tkinter.W)
        else:
            frame.hbar = None
        frame.vbar = tkinter.Scrollbar(
            master=frame.scroll_container, orient=tkinter.VERTICAL
        )
        frame.vbar.grid(row=0, column=1, sticky=tkinter.N + tkinter.S)
        frame.tkw.config(yscrollcommand=frame.vbar.set)
        frame.vbar.config(command=frame.tkw.yview)
        if xscroll:
            frame.tkw.config(xscrollcommand=frame.hbar.set)
            frame.hbar.config(command=frame.tkw.xview)
        frame.tkw.grid(
            row=0, column=0, sticky=tkinter.N + tkinter.S + tkinter.E + tkinter.W
        )
        frame.scroll_container.grid_rowconfigure(0, weight=1)
        frame.scroll_container.grid_columnconfigure(0, weight=1)
        frame.scroll_container.grid(row=row, column=col + 1)
        if on_click is not None:
            frame.tkw.bind("<Button-1>", on_click)
        self._remember_position(frame, row, col, rowspan=rowspan, colspan=2)
        self.append_child(frame)
        return frame

    def _position(self, row=NEXT_ROW, col=-SAME_COL):
        # This makes convenient substitutions for special, negative values.
        # Positive or zero values are unchanged since they are specified positions.
        # SAME_ROW/COL and NEXT_ROW/COL are relative to last component placed, which may
        # not be sequential. The others are relative to the extents of component.
        # This is called in the context of a container for the component thas is about to be created.
        if (row == OVERLAY_ROW) or (col == OVERLAY_COL):
            # an overlay is an overlay. This is a convenience so you don't have to specify both row and col
            row = OVERLAY_ROW
            col = OVERLAY_COL
        if row == SAME_ROW:
            # same row as the previous item, fixup initial value for first row.
            if self.last_used_row < FIRST_ROW:
                self.last_used_row = FIRST_ROW
            row = self.last_used_row
        elif row == NEXT_ROW:
            # next sequential row
            row = self.last_used_row + self.last_used_rowspan
            self.last_used_rowspan = 1
            self.last_used_col = -1  # initialize column for new row
            self.last_used_colspan = 1
        elif row == BOTTOM_ROW:
            # row below everything else
            row = self.bottom_row
        elif row == EXTEND_ROW:
            # row below everything else
            row = self.bottom_row + 1
        elif row == OVERLAY_ROW:
            # row & col in same place, to swap widgets with lift / lower
            row = self.last_used_row
        if col == SAME_COL:
            # use current column, fixup initial value for first column.
            if self.last_used_col < 0:
                self.last_used_col = 0
            col = self.last_used_col
        elif col == NEXT_COL:
            col = self.last_used_col + self.last_used_colspan
        elif col == RIGHT_COL:
            col = self.right_col
        elif col == LEFT_COL:
            col = 0
        elif col == EXTEND_COL:
            # use next column to right of everything else.
            # If components are placed sequentially, this is the same as NEXT_COL.
            col = self.right_col + 1
        elif col == OVERLAY_COL:
            # row & col in same place, to swap widgets with lift / lower
            col = self.last_used_col
        return (row, col)

    def _remember_position(self, new_TkWidgetDef, row, col, colspan=1, rowspan=1):
        # Update the new widgets position info.
        # Theses properties are relative to the container, ususally set by _position().
        # The last_used_XXX properties and corresponding NEXT_XXX position
        # substitutions work only when doing a rectangular grid, layed out by
        # rows and left to right within each row.
        new_TkWidgetDef.row = row
        new_TkWidgetDef.col = col
        new_TkWidgetDef.col_span = colspan
        new_TkWidgetDef.row_span = rowspan
        # Update container positioning to reflect this new widget
        assert self.is_container
        new_widget_right_col = col + colspan - 1
        new_widget_bottom_row = row + rowspan - 1
        self.last_used_row = row
        if rowspan > self.last_used_rowspan:
            self.last_used_rowspan = rowspan  # track deepest widget per row
        self.last_used_col = col
        self.last_used_colspan = colspan
        if new_widget_bottom_row > self.bottom_row:
            self.bottom_row = new_widget_bottom_row
        if new_widget_right_col > self.right_col:
            self.right_col = new_widget_right_col
        if self.debug_this:
            print("_remember_position/new", new_TkWidgetDef._repr_pos())
            print("_remember_position/parent", self._repr_pos())

    def _repr_pos(self):
        res = "(%s,%s) Span(%s,%s) Ext(%s,%s) Last(%s,%s)" % (
            self.row,
            self.col,
            self.row_span,
            self.col_span,
            self.bottom_row,
            self.right_col,
            self.last_used_row,
            self.last_used_col,
        )
        return res


#
# This is the application class at the root of an app.
#


class EasyTk(TkWidgetDef):
    __slots__ = ()

    def __init__(self, debug=False):
        super().__init__("root", tkinter.Tk(), is_container=True, debug=debug)


def simple_test():
    t = EasyTk()
    t.add_button("This", None)
    t.tkw.mainloop()


class RawTestObject:
    def __init__(self):
        self.root = tkinter.Tk()
        self.root.title("Entry Sheet")
        self.root.font = ("Helvetica", "13")
        self.root.header_font = ("Helvetica", "18")
        self.root.exercise_font = ("Helvetica", "13", "bold")
        self.root.delete = "a"
        # self.root.new_user()

        self.frame = tkinter.Frame(self.root)
        self.frame.pack()

        self.button = tkinter.Button(
            self.frame, text="QUIT", fg="red", bg="blue", command=quit
        )
        self.button.pack(side=tkinter.LEFT)
        self.slogan = tkinter.Button(
            self.frame, text="Hello", command=self.write_slogan
        )
        self.slogan.pack(side=tkinter.LEFT),

    def write_slogan(self):
        print("tkinter is easy to use!")

    def loop(self):
        self.root.mainloop()


def raw_test():
    t = RawTestObject()
    t.loop()


if __name__ == "__main__":
    # simple_test()
    raw_test()
