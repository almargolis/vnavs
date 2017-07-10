from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)


#from Tkinter import *		# python 2.7
#from tkinter import ttk	# python 3
#from tkinter import Canvas
import cv2
import tkFileDialog
import Tkinter			# python 2.7
import ScrolledText
import ttk			# python 2.7 - Tk themed widget set
from PIL import ImageTk, Image

SAME_ROW = -1
NEXT_ROW = -2
BOTTOM_ROW = -3
EXTEND_ROW = -4
SAME_COL = -1
NEXT_COL = -2
RIGHT_COL = -3
EXTEND_COL = -4
COL_SPAN_ALL = -1

class TkWidgetDef(object):
    root = None
    debug_all = False

    def __init__(self, wname, tkw, Data=None, tkw_label=None, parm_id=None, IsContainer=False, debug=None):
        self.isContainer = IsContainer
        self.wname = wname		# reference name for this widget
        self.tkw = tkw			# tk widget
        self.tkw_label = tkw_label	# tk widget of associated label
        self.tkd = Data			# the tk data (usually StringVar) for this widget
        self.hbar = None
        self.vbar = None
        self.opencv_im = None
        self.row = None			# row where positioned
        self.col = None			# col where positioned (left side)
        self.right_col = 0		# furthest right colum used
        self.bottom_row = 0		# highest number row used
        self.last_used_row = -1 	# not necesarilly, highest used. for sequential positioning
        self.last_used_rowspan = 1
        self.last_used_col = -1		# not necesarilly highest used. for sequential positioning
        self.last_used_colspan = 1
        self.row_span = 0		# height of this TkWidgetDef object (# of rows)
        self.col_span = 0		# width of this TkWidgetDef object (# of columns)
        self.thumbnail = None		# update this thumbnail if image is changed
        self.thumbnailwidth = 0		# width of thumbnail
        self.children = []
        self.canvasWidth = 400
        self.canvasHeight = 200
        self.parm_id = parm_id		# associated application field, not directly used for TK stuff
        if TkWidgetDef.root is None:
            TkWidgetDef.root = self
            if debug is not None:
                TkWidgetDef.debug_all = debug
        if debug is None:
            self.debug_this = TkWidgetDef.debug_all
        else:
            self.debug_this = debug
        self.file_opt = {}
        self.file_opt['defaultextension'] = '.txt'
        #specifying file types on OSX seems limit what can be selected
        # osx doesn't have an option to select the file categories
        #self.file_opt['filetypes'] = [('all files', '.*'), ('text files', '.txt')]
        self.file_opt['initialdir'] = 'C:\\'
        self.file_opt['initialfile'] = 'myfile.txt'
        self.file_opt['title'] = 'This is a title'

    def ReprPos(self):
       res = "(%s,%s) Span(%s,%s) Ext(%s,%s) Last(%s,%s)" % (self.row, self.col,
								self.row_span, self.col_span,
								self.bottom_row, self.right_col,
								self.last_used_row, self.last_used_col)
       return res

    def DoFileNameDialog(self, Dir=None):
        self.file_opt['parent'] = self.tkw
        if Dir is not None:
            self.file_opt['initialdir'] = Dir
        return tkFileDialog.askopenfilename(**self.file_opt)

    def DoFileOpenDialog(self):
        return tkFileDialog.askopenfile(mode='r', **self.file_opt)

    def Focus(self):
        self.tkw.focus()

    def Update(self):			# Process Tkinter events
        self.tkw.update()

    def AddButton(self, caption, command, row=NEXT_ROW, col=SAME_COL):
        if self.debug_this:
            print("AddButton", row, col, caption)
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Button(self.tkw, text=caption, command=command))
        frame.tkw.grid(row=row, column=col)
        self.RememberPosition(frame, row, col)
        self.children.append(frame)
        return frame

    def AddEntryField(self, caption, width=10, value='', row=NEXT_ROW, col=SAME_COL):
        if self.debug_this:
            print("AddEntryField", row, col, caption)
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')

        tk_data = Tkinter.StringVar()
        tk_data.set(value)
        tk_label = ttk.Label(self.tkw, text=caption)
        tk_label.grid(column=col, row=row, sticky=Tkinter.W)
        tk_entry = ttk.Entry(self.tkw, width=width, textvariable=tk_data)
        tk_entry.grid(column=col+1, row=row, sticky=(Tkinter.W, Tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label, Data=tk_data)
        self.RememberPosition(frame, row, col, colspan=2)
        self.children.append(frame)
        return frame

    def ReplaceValue(self, value, Caption=None):
        if isinstance(self.tkw, ScrolledText.ScrolledText):
            self.tkw.delete("1.0", Tkinter.END)
            self.tkw.insert("1.0", value)
        elif isinstance(self.tkw, ttk.Entry):
            self.tkd.set(value)
        elif isinstance(self.tkw, ttk.Label):
            self.tkw.config(text=value)
        if Caption is not None:
            self.tkw_label.config(text=Caption)

    def Value(self):
        if isinstance(self.tkw, ScrolledText.ScrolledText):
            return self.tkw.get("1.0", Tkinter.END)
        if isinstance(self.tkw, ttk.Entry):
            v = self.tkd.get()
            return v
        if isinstance(self.tkw, Tkinter.Listbox):
            # ix is a tuple like (2,). I assume the 2nd element would be the end of
            # the range. Or maybe it a list of items for multi-selection.
            # This works for now.
            ix = self.tkw.curselection()
            return self.tkw.get(ix)

    def AddScrolledEntryField(self, caption, width=10, height=5, value='', row=NEXT_ROW, col=SAME_COL):
        if self.debug_this:
            print("AddScrolledEntryField", row, col, caption)
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')

        tk_data = Tkinter.StringVar()
        tk_data.set(value)
        tk_label = ttk.Label(self.tkw, text=caption)
        tk_label.grid(column=col, row=row, sticky=Tkinter.W)
        tk_entry = ScrolledText.ScrolledText(master=self.tkw, width=width, height=height, wrap=Tkinter.WORD)
        tk_entry.grid(column=col+1, row=row, sticky=(Tkinter.W, Tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label, Data=tk_data)
        self.RememberPosition(frame, row, col, colspan=2, rowspan=height)
        self.children.append(frame)
        return frame

    def AddLabel(self, text='', width=10, value='', row=NEXT_ROW, col=SAME_COL):
        # An alternate method would be to create a TK StringVar and when creating the label
        # use the textvariable property instead of text. Visually this shouldn't be any different.
        # The update process would be a bit different in some cases because the label would 
        # be automagically updated if something changed the variable.
        refname = 'X'
        row, col = self.Position(row=row, col=col)
        tk_label = ttk.Label(self.tkw, text=text)
        tk_label.grid(column=col, row=row, sticky=Tkinter.W)
        frame = TkWidgetDef(refname, tk_label)
        self.RememberPosition(frame, row, col)
        self.children.append(frame)
        return frame

    def AddDropDown(self, caption=None, s_items=[], Selection=None, row=NEXT_ROW, col=SAME_COL, command=None):
        if self.debug_this:
            print("AddDropDown", row, col, caption)
        row, col = self.Position(row=row, col=col)
        if caption is None:
            refname = "QWE"
            tk_label = None
            entry_col = col
            remember_colspan = 1
        else:
            refname = caption.lower().replace(' ', '_')
            tk_label = ttk.Label(self.tkw, text=caption)
            tk_label.grid(column=col, row=row, sticky=Tkinter.W)
            entry_col = col + 1
            remember_colspan = 2

        tk_data = Tkinter.StringVar()
        tk_data.set(Selection)
        args = [self.tkw, tk_data] + s_items
        tk_entry = Tkinter.OptionMenu(*args)
        tk_entry.grid(column=entry_col, row=row, sticky=(Tkinter.W, Tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label, Data=tk_data)
        if command is not None:
            frame.tkw.bind("<Double-Button-1>", command)
        self.RememberPosition(frame, row, col, colspan=remember_colspan)
        self.children.append(frame)
        return frame

    def AddListbox(self, caption, s_items, Selection=None, row=NEXT_ROW, col=SAME_COL, rowspan=5, command=None, XSCROLL=False):
        frame = self.AddScrolledWidget(Tkinter.Listbox, {'exportselection': 0, 'height': rowspan},
						caption=caption, row=row, col=col, rowspan=rowspan, XSCROLL=XSCROLL)
        for this_item in s_items:
            frame.tkw.insert(Tkinter.END, this_item)
        if command is not None:
            frame.tkw.bind("<Double-Button-1>", command)
        if Selection is None:
            active_index = 0
        else:
            try:
                active_index = s_items.index(Selection)
            except ValueError:
                active_index = 0
        frame.tkw.selection_set(active_index)
        frame.tkw.see(active_index)
        return frame

    def AddScrolledWidget(self, tk_widget_class, tk_widget_parms, caption=None, row=NEXT_ROW, col=SAME_COL, rowspan=5, XSCROLL=False):
        # Getting scrolled widgets right is verbose and fussy. I found this technique using a seperate frame and 
        # explicit borderwidth and weight on StackOverflow somewhere.
        # The goal is for this tmethod to create any widget that needs scroll bars.
        #
        row, col = self.Position(row=row, col=col)

        if caption is None:
            tk_label = None
            refname = "ZXC"
        else:
            refname = caption.lower().replace(' ', '_')
            tk_label = ttk.Label(self.tkw, text=caption)
            tk_label.grid(column=col, row=row, sticky=Tkinter.W)

        container = ttk.Frame(master=self.tkw, borderwidth=2, relief=Tkinter.SUNKEN)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        container.grid(row=row, column=col+1)
        if XSCROLL:
            xscrollbar = ttk.Scrollbar(master=container, orient=Tkinter.HORIZONTAL)
            xscrollbar.grid(row=1, column=0, sticky=Tkinter.E+Tkinter.W)
        else:
            xscrollbar = None
        yscrollbar = ttk.Scrollbar(master=container, orient=Tkinter.VERTICAL)
        yscrollbar.grid(row=0, column=1, sticky=Tkinter.N+Tkinter.S)
        tkw = tk_widget_class(master=container, borderwidth=0, yscrollcommand=yscrollbar.set, **tk_widget_parms)
        if XSCROLL:
            tkw.config(xscrollcommand=xscrollbar.set)
            xscrollbar.config(command=tkw.xview)
        yscrollbar.config(command=tkw.yview)
        parms = {'column': col+1, 'row': row, 'sticky': (Tkinter.W, Tkinter.E) }
        if rowspan > 1:
            parms['rowspan'] = rowspan
        tkw.grid(row=0, column=0, sticky=Tkinter.N+Tkinter.S+Tkinter.E+Tkinter.W)
        frame = TkWidgetDef(refname, tkw, tkw_label=tk_label)
        frame.hbar = xscrollbar
        frame.vbar = yscrollbar
        self.RememberPosition(frame, row, col, rowspan=rowspan, colspan=2)
        self.children.append(frame)
        return frame

    def MakeThumbnail(self, im, width):
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

    def Position(self, row=NEXT_ROW, col=-SAME_COL):
        # This makes convenient substitutions for special, negative values.
        # Positive or zero values are unchanged since they are specified positions.
        # SAME_ROW/COL and NEXT_ROW/COL are relative to last component placed, which may 
        # not be sequential. The others are relative to the extents of component.
        # This is called in the context of a container for the component thas is about to be created.
        if row == SAME_ROW:
            # same row as the previous item, fixup initial value for first row.
            if self.last_used_row < 0:
                self.last_used_row = 0
            row = self.last_used_row
        elif row == NEXT_ROW:
            # next sequential row
            row = self.last_used_row + self.last_used_rowspan
            self.last_used_rowspan = 1
            self.last_used_col = -1		# initialize column for new row
            self.last_used_colspan = 1
        elif row == BOTTOM_ROW:
            # row below everything else
            row = self.bottom_row
        elif row == EXTEND_ROW:
            # row below everything else
            row = self.bottom_row + 1
        if col == SAME_COL:
            # use current column, fixup initial value for first column.
            if self.last_used_col < 0:
                self.last_used_col = 0
            col = self.last_used_col
        elif col == NEXT_COL:
            col = self.last_used_col + self.last_used_colspan
        elif col == RIGHT_COL:
            col = self.right_col
        elif col == EXTEND_COL:
            # use next column to right of everything else.
            # If components are placed sequentially, this is the same as NEXT_COL.
            col = self.right_col + 1
        return (row, col)

    def RememberPosition(self, new_TkWidgetDef, row, col, colspan=1, rowspan=1):
        # Update the new widgets position info.
        # Theses properties are relative to the container, ususally set by Position().
        # The last_used_XXX properties and corresponding NEXT_XXX position
        # substitutions work only when doing a rectangular grid, layed out by 
        # rows and left to right within each row.
        new_TkWidgetDef.row = row
        new_TkWidgetDef.col = col
        new_TkWidgetDef.col_span = colspan
        new_TkWidgetDef.row_span = rowspan
        # Update container positioning to reflect this new widget
        assert self.isContainer
        new_widget_right_col = col + colspan - 1
        new_widget_bottom_row = row + rowspan - 1
        self.last_used_row = row
        if rowspan > self.last_used_rowspan:
            self.last_used_rowspan  = rowspan		# track deepest widget per row
        self.last_used_col = col
        self.last_used_colspan = colspan
        if new_widget_bottom_row > self.bottom_row:
            self.bottom_row = new_widget_bottom_row
        if new_widget_right_col > self.right_col:
            self.right_col = new_widget_right_col
        if self.debug_this:
            print("RememberPosition/new", new_TkWidgetDef.ReprPos())
            print("RememberPosition/parent", self.ReprPos())

    def AddCanvas(self, fn=None, opencv=None, opencvfn=None,
				thumbnailof=None, thumbnailwidth=100,
				width=400, height=200,
				row=NEXT_ROW, col=SAME_COL, colspan=1, rowspan=1):
        frame = self.AddScrolledWidget(Tkinter.Canvas, {'width': width, 'height': height},
						row=row, col=col, rowspan=rowspan, XSCROLL=True)
        frame.scrollableImage = None
        frame.canvasWidth = width
        frame.canvasHeight = height

        if thumbnailof is None:
            frame.UpdateImage(fn=fn, opencv=opencv, opencvfn=opencvfn)
        else:
            # after this, the thumbnail will be automatically updated whenever the base image is updated
            frame.UpdateImage(opencv=self.MakeThumbnail(thumbnailof.opencv_im, thumbnailwidth))
            thumbnailof.thumbnail = frame
            thumbnailof.thumbnailwidth = thumbnailwidth

        return frame

    def AddLabelImage(self, fn=None, opencv=None, opencvfn=None,
				thumbnailof=None, thumbnailwidth=100,
				row=NEXT_ROW, col=SAME_COL, colspan=1):
        row, col = self.Position(row=row, col=col)
        frame = TkWidgetDef('', ttk.Label(self.tkw))
        if thumbnailof is None:
            frame.UpdateImage(fn=fn, opencv=opencv, opencvfn=opencvfn)
        else:
            # after this, the thumbnail will be automatically updated whenever the base image is updated
            frame.UpdateImage(opencv=self.MakeThumbnail(thumbnailof.opencv_im, thumbnailwidth))
            thumbnailof.thumbnail = frame
            thumbnailof.thumbnailwidth = thumbnailwidth

        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=Tkinter.W)
        self.RememberPosition(frame, row, col, colspan=colspan)
        self.children.append(frame)
        return frame

    def UpdateImage(self, fn=None, opencv=None, opencvfn=None):
        # Replaces image in Canvas and Label widgets
        img_pil = None
        img_tk = None
        if fn is not None:
            try:
                img_pil = Image.open(fn)
            except IOError:
                img_pil = None
            self.opencv_im = None
        elif opencv is not None:
            img_pil = Image.fromarray(opencv)
            self.opencv_im = opencv
        elif opencvfn is not None:
            opencv = cv2.imread(opencvfn)
            self.opencv_im = opencv
            img_pil = Image.fromarray(opencv)
        #
        if img_pil is not None:
            imWidth = img_pil.width
            if self.canvasWidth < imWidth:
                imHeight = img_pil.height
                height = int((self.canvasWidth / imWidth) * imHeight)
                img_pil = img_pil.resize((self.canvasWidth, height))
                #print("RESIZE", self.canvasWidth, height)
            img_tk = ImageTk.PhotoImage(img_pil)
        self.tkd = img_tk
        if img_tk is not None:
            if isinstance(self.tkw, ttk.Label):
                self.tkw.configure(image=img_tk)
            elif isinstance(self.tkw, Tkinter.Canvas):
                if self.scrollableImage is None:
                    self.scrollableImage = self.tkw.create_image(0, 0, image=img_tk, anchor='nw')
                else:
                    self.tkw.itemconfig(self.scrollableImage, image=img_tk)
                width, height = img_pil.size
                self.tkw.config(scrollregion=(0, 0, width, height))
                pctWidth = self.canvasWidth / width
                if pctWidth > 1.0:
                    pctWidth = 1.0
                self.hbar.set(0.0, pctWidth)
                pctHeight = self.canvasHeight / height
                if pctHeight > 1.0:
                    pctHeight = 1.0
                self.vbar.set(0.0, pctHeight)
            else:
                raise TypeError("Unsupported image widget: " + self.tkw.__class__.__name__)
        if self.thumbnail:
            self.thumbnail.UpdateImage(opencv=self.MakeThumbnail(self.opencv_im, self.thumbnailwidth))

    def AddLabelFrame(self, caption, row=NEXT_ROW, col=SAME_COL, colspan=1):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Labelframe(self.tkw, text=caption), IsContainer=True)
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=Tkinter.W)
        self.RememberPosition(frame, row, col, colspan=colspan)
        self.children.append(frame)
        return frame

    def AddFrame(self, row=NEXT_ROW, col=SAME_COL, colspan=1):
        if self.debug_this:
            print("AddFrame", row, col, colspan)
        row, col = self.Position(row=row, col=col)
        refname = 'X'
        frame = TkWidgetDef(refname, ttk.Frame(self.tkw), IsContainer=True)
        if colspan == COL_SPAN_ALL:
            colspan = self.right_col - col + 1
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=Tkinter.W)
        self.RememberPosition(frame, row, col, colspan=colspan)
        self.children.append(frame)
        return frame

    def AddNotebook(self, row=NEXT_ROW, col=SAME_COL, colspan=1):
        row, col = self.Position(row=row, col=col)
        frame = TkWidgetDef('', ttk.Notebook(self.tkw), IsContainer=True)
        #frame.tkw.pack(expand="yes")
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=Tkinter.W)
        self.RememberPosition(frame, row, col, colspan=colspan)
        self.children.append(frame)
        return frame

    def AddTab(self, caption):
        # Add a tab to notebook
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Frame(self.tkw), IsContainer=True)
        self.tkw.add(frame.tkw, text=caption)
        self.children.append(frame)
        return frame

class EasyTk(TkWidgetDef):
    def __init__(self, debug=False):
        super().__init__('root', Tkinter.Tk(), IsContainer=True, debug=debug)
