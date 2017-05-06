from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)


#from Tkinter import *		# python 2.7
#from tkinter import ttk	# python 3
#from tkinter import Canvas
#import tkFileDialog
import Tkinter			# python 2.7
import ttk			# python 2.7 - Tk themed widget set

SAME_ROW = -1
NEXT_ROW = -2
NEXT_COL = -3

class TkWidgetDef(object):
    root = None

    def __init__(self, wname, tkw, Data=None, tkw_label=None, parm_id=None):
        self.wname = wname		# reference name for this widget
        self.tkw = tkw			# tk widget
        self.tkw_label = tkw_label	# tk widget of associated label
        self.tkd = Data			# the tk data (usually StringVar) for this widget
        self.hbar = None
        self.vbar = None
        self.opencv_im = None
        self.row = None			# row where positioned
        self.col = None			# col where positioned (left side)
        self.right_col = None		# furthest right colum used
        self.last_row = 0		# not necesarilly, highest used. for sequential positioning
        self.last_col = 0		# not necesarilly highest used. for sequential positioning
        self.row_ct = 0			# height of this TkWidgetDef object (# of rows)
        self.col_ct = 0			# width of this TkWidgetDef object (# of columns)
        self.thumbnail = None		# update this thumbnail if image is changed
        self.thumbnailwidth = 0		# width of thumbnail
        self.children = []
        self.canvasWidth = 400
        self.canvasHeight = 200
        self.parm_id = parm_id		# associated application field, not directly used for TK stuff
        if self.root is None:
            self.root = self

        self.file_opt = options = {}
        options['defaultextension'] = '.txt'
        #specifying file types on OSX seems limit what can be selected
        # osx doesn't have an option to select the file categories
        #options['filetypes'] = [('all files', '.*'), ('text files', '.txt')]
        options['initialdir'] = 'C:\\'
        options['initialfile'] = 'myfile.txt'
        options['title'] = 'This is a title'

    def DoFileNameDialog(self):
        self.file_opt['parent'] = self.tkw
        return tkFileDialog.askopenfilename(**self.file_opt)

    def DoFileOpenDialog(self):
        return tkFileDialog.askopenfile(mode='r', **self.file_opt)

    def AddButton(self, caption, command, row=-2, col=-2):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Button(self.tkw, text=caption, command=command))
        frame.tkw.grid(row=row, column=col)
        self.RememberPosition(frame, row, col, 1)
        self.children.append(frame)
        return frame

    def AddEntryField(self, caption, Width=10, Value='', row=-2, col=-2):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')

        tk_data = Tkinter.StringVar()
        tk_data.set(Value)
        tk_label = ttk.Label(self.tkw, text=caption)
        tk_label.grid(column=col, row=row, sticky=Tkinter.W)
        tk_entry = ttk.Entry(self.tkw, width=Width, textvariable=tk_data)
        tk_entry.grid(column=col+1, row=row, sticky=(Tkinter.W, Tkinter.E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label, Data=tk_data)
        self.RememberPosition(frame, row, col, 2)
        self.children.append(frame)
        return frame

    def UpdateEntryField(self, Value='', Caption=None):
        self.tkd.set(Value)
        if Caption is not None:
            self.tkw_label.config(text=Caption)

    def AddLabel(self, text='', Width=10, Value='', row=-2, col=-2):
        refname = 'X'
        row, col = self.Position(row=row, col=col)
        tk_label = ttk.Label(self.tkw, text=text)
        tk_label.grid(column=col, row=row, sticky=Tkinter.W)
        frame = TkWidgetDef(refname, tk_label)
        self.RememberPosition(frame, row, col, 1)
        self.children.append(frame)
        return frame

    def UpdateLabel(self, text):
        self.tkw.config(text=text)

    def AddListbox(self, caption, s_items, Selection=None, row=-2, col=-2, height=5, rowspan=0, Command=None):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')

        #tk_data = Tkinter.StringVar()
        #tk_data.set('')
        tk_label = ttk.Label(self.tkw, text=caption).grid(column=0, row=self.last_row, sticky=Tkinter.W)
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
        parms = {'column': 1, 'row': self.last_row, 'sticky': (Tkinter.W, Tkinter.E) }
        if rowspan > 0:
            parms['rowspan'] = rowspan
        tk_entry.grid(**parms)
        if self.col_ct < 2:
            self.col_ct = 2
        #frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label, Data=tk_data)
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label)
        self.RememberPosition(frame, row, col, 2)
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

    def Position(self, row=-2, col=-2):
        if row == -1:
            # same row as the previous item
            row = self.last_row
        elif row == -2:
            # next sequential row
            self.last_row += 1
            row = self.last_row
        elif row == -3:
            # row below everything else
            row = self.row_ct + 1
        if col == -2:
            # use current column -- consisten with row -2 for most common sequential position
            col = self.last_col
        elif col == -3:
            # use next column to right of everything else
            col = self.col_ct + 1
        return (row, col)

    def RememberPosition(self, new_TkWidgetDef, row, col, colspan=1, rowspan=1):
        new_TkWidgetDef.row = row
        new_TkWidgetDef.col = col
        new_TkWidgetDef.col_ct = colspan
        new_TkWidgetDef.row_ct = rowspan
        new_TkWidgetDef.right_col = col + colspan - 1
        self.last_row = row
        self.last_col = col
        if row > self.row_ct:
            self.row_ct = row
        if new_TkWidgetDef.right_col > self.col_ct:
            self.col_ct = new_TkWidgetDef.right_col

    def AddCanvas(self, fp=None, opencv=None, opencvfn=None,
				thumbnailof=None, thumbnailwidth=100,
				width=400, height=200,
				row=-2, col=-2, colspan=1, rowspan=1):
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
            frame.UpdateImage(fp=fp, opencv=opencv, opencvfn=opencvfn)
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
				row=-2, col=-2, colspan=1):
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
        self.RememberPosition(frame, row, col, colspan)
        self.children.append(frame)
        return frame

    def UpdateImage(self, fp=None, opencv=None, opencvfn=None):
        # Replaces image in Canvas and Label widgets
        img_pil = None
        img_tk = None
        if fp is not None:
            try:
                img_pil = Image.open(fp)
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

    def AddLabelFrame(self, caption, row=-2, col=-2, colspan=1):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Labelframe(self.tkw, text=caption))
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=Tkinter.W)
        self.RememberPosition(frame, row, col, colspan)
        self.children.append(frame)
        return frame

    def AddNotebook(self, row=-2, col=-2, colspan=1):
        row, col = self.Position(row=row, col=col)
        frame = TkWidgetDef('', ttk.Notebook(self.tkw))
        #frame.tkw.pack(expand="yes")
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=Tkinter.W)
        self.RememberPosition(frame, row, col, colspan)
        self.children.append(frame)
        return frame

    def AddTab(self, caption):
        # Add a tab to notebook
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Frame(self.tkw))
        self.tkw.add(frame.tkw, text=caption)
        self.children.append(frame)
        return frame

class EasyTk(TkWidgetDef):
    def __init__(self):
        super().__init__('root', Tkinter.Tk())
