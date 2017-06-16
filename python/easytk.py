from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)


#from Tkinter import *		# python 2.7
#from tkinter import ttk	# python 3
#from tkinter import Canvas
#import tkFileDialog
import Tkinter			# python 2.7
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
        self.last_used_row = 0		# not necesarilly, highest used. for sequential positioning
        self.last_used_col = 0		# not necesarilly highest used. for sequential positioning
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
        self.file_opt = options = {}
        options['defaultextension'] = '.txt'
        #specifying file types on OSX seems limit what can be selected
        # osx doesn't have an option to select the file categories
        #options['filetypes'] = [('all files', '.*'), ('text files', '.txt')]
        options['initialdir'] = 'C:\\'
        options['initialfile'] = 'myfile.txt'
        options['title'] = 'This is a title'

    def ReprPos(self):
       res = "(%s,%s) Span(%s,%s) Ext(%s,%s) Last(%s,%s)" % (self.row, self.col,
								self.row_span, self.col_span,
								self.bottom_row, self.right_col,
								self.last_used_row, self.last_used_col)
       return res

    def DoFileNameDialog(self):
        self.file_opt['parent'] = self.tkw
        return tkFileDialog.askopenfilename(**self.file_opt)

    def DoFileOpenDialog(self):
        return tkFileDialog.askopenfile(mode='r', **self.file_opt)

    def Focus(self):
        self.tkw.focus()

    def Update(self):
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

    def UpdateEntryField(self, value='', Caption=None):
        self.tkd.set(value)
        if Caption is not None:
            self.tkw_label.config(text=Caption)

    def AddLabel(self, text='', width=10, value='', row=NEXT_ROW, col=SAME_COL):
        refname = 'X'
        row, col = self.Position(row=row, col=col)
        tk_label = ttk.Label(self.tkw, text=text)
        tk_label.grid(column=col, row=row, sticky=Tkinter.W)
        frame = TkWidgetDef(refname, tk_label)
        self.RememberPosition(frame, row, col)
        self.children.append(frame)
        return frame

    def UpdateLabel(self, text):
        # An alternate method would be to create a TK StringVar and when creating the label
        # use the textvariable property instead of text. Visually this shouldn't be any different.
        # The update process would be a bit different in some cases because the label would 
        # be automagically updated if something changed the variable.
        self.tkw.config(text=text)

    def AddListbox(self, caption, s_items, Selection=None, row=NEXT_ROW, col=SAME_COL, height=5, rowspan=0, Command=None):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')

        #tk_data = Tkinter.StringVar()
        #tk_data.set('')
        tk_label = ttk.Label(self.tkw, text=caption).grid(column=0, row=self.last_used_row, sticky=Tkinter.W)
        scrollbar = ttk.Scrollbar(self.tkw, orient=Tkinter.VERTICAL)
        tk_entry = Tkinter.Listbox(self.tkw, yscrollcommand=scrollbar.set, exportselection=0)
        tk_entry.config(height=height)
        scrollbar.config(command=tk_entry.yview)
        for this_item in s_items:
            tk_entry.insert(Tkinter.END, this_item)
        if Command is not None:
            tk_entry.bind("<Double-Button-1>", Command)
        if Selection is None:
            active_index = 0
        else:
            try:
                active_index = s_items.index(Selection)
            except ValueError:
                active_index = 0
        tk_entry.selection_set(active_index)
        tk_entry.see(active_index)
        parms = {'column': 1, 'row': self.last_used_row, 'sticky': (Tkinter.W, Tkinter.E) }
        if rowspan > 0:
            parms['rowspan'] = rowspan
        tk_entry.grid(**parms)
        if self.col_span < 2:
            self.col_span = 2
        #frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label, Data=tk_data)
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label)
        self.RememberPosition(frame, row, col, colspan=2)
        self.children.append(frame)
        return frame

    def CurrentValue(self):
        if isinstance(self.tkw, ttk.Entry):
            v = self.tkd.get()
            print("CurrentValue", v)
            return v
        if isinstance(self.tkw, Tkinter.Listbox):
            # ix is a tuple like (2,). I assume the 2nd element would be the end of
            # the range. Or maybe it a list of items for multi-selection.
            # This works for now.
            ix = self.tkw.curselection()
            return self.tkw.get(ix)

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
            # same row as the previous item
            row = self.last_used_row
        elif row == NEXT_ROW:
            # next sequential row
            row = self.last_used_row + 1
        elif row == BOTTOM_ROW:
            # row below everything else
            row = self.bottom_row
        elif row == EXTEND_ROW:
            # row below everything else
            row = self.bottom_row + 1
        if col == SAME_COL:
            # use current column -- consisten with row -2 for most common sequential position
            col = self.last_used_col
        elif col == NEXT_COL:
            col = self.last_used_col + 1
        elif col == RIGHT_COL:
            col = self.right_col
        elif col == EXTEND_COL:
            # use next column to right of everything else.
            # If components are placed sequentially, this is the same as NEXT_COL.
            col = self.right_col + 1
        return (row, col)

    def RememberPosition(self, new_TkWidgetDef, row, col, colspan=1, rowspan=1):
        # Update the new widgets position info.
        # Theses properties are relative to the container, ususally set by Position() 
        new_TkWidgetDef.row = row
        new_TkWidgetDef.col = col
        new_TkWidgetDef.col_span = colspan
        new_TkWidgetDef.row_span = rowspan
        # Update container positioning to reflect this new widget
        assert self.isContainer
        new_widget_right_col = col + colspan - 1
        new_widget_bottom_row = row + rowspan - 1
        self.last_used_row = row
        self.last_used_col = col
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
        row, col = self.Position(row=row, col=col)
        canvas = Tkinter.Canvas(self.tkw, width=width, height=height)
        frame = TkWidgetDef('', canvas)

        # The scrollbars are TK properties of the same frame as as the canvas.
        # We save the widget definitions with the canvas.
        frame.scrollableImage = None
        frame.canvasWidth = width
        frame.canvasHeight = height
        frame.hbar=ttk.Scrollbar(self.tkw, orient=Tkinter.HORIZONTAL)
        frame.hbar.grid(row=row+1, column=col, sticky=Tkinter.E+Tkinter.W)
        frame.vbar=ttk.Scrollbar(self.tkw, orient=Tkinter.VERTICAL)
        frame.vbar.grid(row=row, column=col+1, sticky=Tkinter.N+Tkinter.S)
        frame.tkw.config(width=frame.canvasWidth, height=frame.canvasHeight)
        self.AttachScrollbars()

        if thumbnailof is None:
            frame.UpdateImage(fn=fn, opencv=opencv, opencvfn=opencvfn)
        else:
            # after this, the thumbnail will be automatically updated whenever the base image is updated
            frame.UpdateImage(opencv=self.MakeThumbnail(thumbnailof.opencv_im, thumbnailwidth))
            thumbnailof.thumbnail = frame
            thumbnailof.thumbnailwidth = thumbnailwidth

        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=Tkinter.W)
        # colspan and rowspan need to be expanded to allow for scrollbars ???
        self.RememberPosition(frame, row, col, colspan=colspan+1, rowspan=rowspan+1)
        self.children.append(frame)
        return frame

    def AttachScrollbars(self):
        if self.hbar is not None:
            self.hbar.config(command=self.tkw.xview)
            self.tkw.config(xscrollcommand=self.hbar.set)
        if self.vbar is not None:
            self.vbar.config(command=self.tkw.yview)
            self.tkw.config(yscrollcommand=self.vbar.set)

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
                print("RESIZE", self.canvasWidth, height)
            img_tk = ImageTk.PhotoImage(img_pil)
        self.tkd = img_tk
        if img_tk is not None:
            if isinstance(self.tkw, ttk.Label):
                self.tkw.configure(image=img_tk)
            elif isinstance(self.tkw, Canvas):
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
        self.AttachScrollbars()
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
