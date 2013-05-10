'''plateviewer.py - a user interface to view the image files for a plate

CellProfiler is distributed under the GNU General Public License.
See the accompanying file LICENSE for details.

Copyright (c) 2003-2009 Massachusetts Institute of Technology
Copyright (c) 2009-2013 Broad Institute
All rights reserved.

Please see the AUTHORS file for credits.

Website: http://www.cellprofiler.org
'''

import numpy as np
import wx
import wx.grid
import matplotlib
import matplotlib.cm
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
from matplotlib.backends.backend_wx import NavigationToolbar2Wx
import threading
import multiprocessing

from bioformats import load_using_bioformats

class PlateData(object):
    '''The plate data is the data store for the image files
    
    plate_well_site is a 3-level dictionary where the first level
    dictionary has keys that are plate names and whose values are
    dictionaries of wells.
    The second level has keys that are well names and values that are
    dictionaries of sites. The third level has site name as key and
    a list of files at that site as values.
    '''
    D_FILENAME = "filename"
    D_PLANE_INDEX = "planeindex"
    D_CHANNEL = "channel"
    D_Z = "z"
    D_T = "t"
    def __init__(self, 
                 plate_layout = (16, 24),
                 well_layout = None):
        '''Initialize the plate model
        
        plate_layout - the layout of wells on the plate (rows, columns)
        
        well_layout - the layout of sites within a well. Each site should
        have a row and column position. The format is a sequence of two-tuples.
        '''
        self.plate_well_site = {}
        self.plate_layout = plate_layout
        self.well_layout = well_layout
        self.has_channel_names = False
        self.has_z_indexes = False
        self.has_t_indexes = False
        self.registrants = []
        self.max_per_well = 0
        
    def register_for_updates(self, fn):
        self.registrants.append(fn)
        
    def on_update(self):
        #
        # Calculate maximum # of planes per well
        #
        self.max_per_well = 0
        for pd in self.plate_well_site.values():
            for wd in pd.values():
                nplanes = sum([len(x) for x in wd.values()])
                if nplanes > self.max_per_well:
                    self.max_per_well = nplanes
        for registrant in self.registrants:
            registrant()
        
    def add_files(self, filenames, platenames, wellnames, sites, 
                  plane_indexes = None,
                  channel_names = None,
                  z_indexes = None,
                  t_indexes = None):
        '''Add files to the plate model
        
        filenames - a sequence of image file names
        platenames - a sequence of plate names, one per file
        wellnames - a sequence of well names, one per file
        sites - a sequence of site indexes, one per file
        plane_indexes - if present, gives the index of the planar image within
                        the file.
        channel_names - if present, the name of the associated channel for
        the planar image
        z_indexes - if present, the Z index of the plane
        t_indexes - if present, the time index of the plane
        '''
        self.has_channel_names |= channel_names is not None
        self.has_z_indexes |= z_indexes is not None
        self.has_t_indexes |= t_indexes is not None
        for i, (filename, platename, wellname, site) in enumerate(
            zip(filenames, platenames, wellnames, sites)):
                if platename not in self.plate_well_site:
                    self.plate_well_site[platename] = {}
                pd = self.plate_well_site[platename]
                if wellname not in pd:
                    pd[wellname] = {}
                wd = pd[wellname]
                if site not in wd:
                    wd[site] = []
                sd = wd[site]
                fd = { self.D_FILENAME: filename }
                if plane_indexes is not None:
                    fd[self.D_PLANE_INDEX] = plane_indexes[i]
                if channel_names is not None:
                    fd[self.D_CHANNEL] = channel_names[i]
                if z_indexes is not None:
                    fd[self.D_Z] = z_indexes[i]
                if t_indexes is not None:
                    fd[self.D_T] = t_indexes[i]
                sd.append(fd)
        self.on_update()
        
    def get_plate_names(self):
        return self.plate_well_site.keys()
    
    def get_plate(self, name):
        pd = self.plate_well_site[name]
        a = np.zeros(self.plate_layout, object)
        a[:,:] = None
        for wellname, wd in pd.iteritems():
            row = ord(wellname[0].lower()) - ord('a')
            col = int(wellname[1:])-1
            if row < a.shape[0] and col < a.shape[1]:
                a[row, col] = wd
        return a
                
class PlateViewer(object):
    '''The PlateViewer class lets the user view the files associated with plates
    
    The idea here is that the PlateViewer is given a list of image files
    with plate, well and site metadata. The plate viewer organizes the
    files and lets the user browse individual plates.
    '''
    def __init__(self, frame, data):
        self.data = data
        self.palette = matplotlib.cm.jet
        data.register_for_updates(self.on_update)
        self.frame = frame
        self.plate_bitmap = None
        self.frame.Sizer = wx.BoxSizer(wx.VERTICAL)
        self.toolbar = wx.ToolBar(self.frame)
        self.frame.Sizer.Add(self.toolbar, 0, wx.EXPAND)
        self.plate_choice = wx.Choice(self.toolbar)
        self.toolbar.AddControl(self.plate_choice)
        self.toolbar.Realize()
        self.splitter = wx.SplitterWindow(self.frame)
        self.frame.Sizer.Add(self.splitter, 1, wx.EXPAND)
        self.plate_panel = wx.Panel(self.splitter)
        rows, cols = data.plate_layout
        w, h = self.plate_panel.GetTextExtent("".join(["00"] * cols))
        h *= rows
        self.plate_panel.SetMinSize((w, h))
        self.canvas_panel = wx.Panel(self.splitter)
        self.canvas_panel.Sizer = wx.BoxSizer(wx.VERTICAL)
        control_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.canvas_panel.Sizer.Add(control_sizer, 0, wx.EXPAND | wx.ALL, 2)
        self.site_grid = wx.grid.Grid(self.canvas_panel)
        self.site_grid.SetDefaultRenderer(wx.grid.GridCellFloatRenderer())
        self.site_grid.SetDefaultEditor(wx.grid.GridCellFloatEditor())
        self.site_grid.CreateGrid(1,2)
        self.site_grid.SetColLabelValue(0, "X")
        self.site_grid.SetColLabelValue(1, "Y")
        control_sizer.Add(self.site_grid, 0, 
                          wx.ALIGN_LEFT | wx.ALIGN_TOP | wx.ALL, 5)
        
        self.channel_grid = wx.grid.Grid(self.canvas_panel)
        self.channel_grid.CreateGrid(1,4)
        self.channel_grid.SetColLabelValue(0, "Red")
        self.channel_grid.SetColLabelValue(1, "Green")
        self.channel_grid.SetColLabelValue(2, "Blue")
        self.channel_grid.SetColLabelValue(3, "Alpha")
        self.channel_grid.SetDefaultEditor(wx.grid.GridCellNumberEditor())
        self.channel_grid.SetDefaultRenderer(wx.grid.GridCellNumberRenderer())
        control_sizer.Add(self.channel_grid, 0,
                          wx.ALIGN_RIGHT | wx.ALIGN_TOP | wx.ALL, 5)
        self.figure = matplotlib.figure.Figure()
        self.axes = self.figure.add_axes((0.05, 0.05, .9, .9))
        self.canvas = FigureCanvasWxAgg(self.canvas_panel, -1, self.figure)
        self.canvas_panel.Sizer.Add(self.canvas, 1, wx.EXPAND)
        #
        # The following is largely taken from the matplotlib examples:
        # http://matplotlib.sourceforge.net/examples/user_interfaces/embedding_in_wx2.html
        #
        self.toolbar = NavigationToolbar2Wx(self.canvas)
        self.toolbar.Realize()
        if wx.Platform == '__WXMAC__':
            # Mac platform (OSX 10.3, MacPython) does not seem to cope with
            # having a toolbar in a sizer. This work-around gets the buttons
            # back, but at the expense of having the toolbar at the top
            self.frame.SetToolBar(self.toolbar)
        else:
            # On Windows platform, default window size is incorrect, so set
            # toolbar width to figure width.
            tw, th = self.toolbar.GetSizeTuple()
            fw, fh = self.canvas.GetSizeTuple()
            # By adding toolbar in sizer, we are able to put it at the bottom
            # of the frame - so appearance is closer to GTK version.
            # As noted above, doesn't work for Mac.
            self.toolbar.SetSize(wx.Size(fw, th))
            self.canvas_panel.Sizer.Add(self.toolbar, 0, wx.LEFT | wx.EXPAND)
        # update the axes menu on the toolbar
        self.toolbar.update()
        self.image_dict = None
        self.image_dict_lock = multiprocessing.RLock()
        self.image_dict_generation = 0
        self.splitter.SplitVertically(self.plate_panel, self.canvas_panel)
        self.plate_panel.Bind(wx.EVT_PAINT, self.on_paint_plate)
        self.plate_panel.Bind(wx.EVT_ERASE_BACKGROUND, self.on_erase_background)
        self.plate_panel.Bind(wx.EVT_SIZE, self.on_plate_size)
        self.plate_panel.Bind(wx.EVT_MOTION, self.on_plate_motion)
        self.plate_panel.Bind(wx.EVT_LEFT_DOWN, self.on_plate_click)
        self.plate_choice.Bind(wx.EVT_CHOICE, self.on_plate_choice_evt)
        self.site_grid.Bind(wx.grid.EVT_GRID_CELL_CHANGE,
                            lambda event: self.update_figure())
        self.channel_grid.Bind(wx.grid.EVT_GRID_CELL_CHANGE,
                               lambda event: self.update_figure())
        self.on_update()
        self.frame.Layout()
        
    def get_border_height(self):
        '''The border along the top of the plate'''
        return 20
    
    def get_border_width(self):
        return 30
    
    def on_plate_choice_evt(self, event):
        self.on_update()
        
    def on_plate_size(self, event):
        self.draw_plate()
        
    def on_plate_click(self, event):
        assert isinstance(event, wx.MouseEvent)
        x, y = event.GetPositionTuple()
        hit = self.plate_hit_test(x, y)
        if hit is None or self.plate_data is None:
            return
        row, col = hit
        if self.plate_data[row, col] is None:
            return
        self.set_display_well(self.plate_data[row, col])
            
    def on_plate_motion(self, event):
        assert isinstance(event, wx.MouseEvent)
        x, y = event.GetPositionTuple()
        hit = self.plate_hit_test(x, y)
        if hit is None or self.plate_data is None:
            self.plate_panel.SetToolTipString("")
        else:
            row, col = hit
            well_name = "%s%02d" % (chr(ord("A") + row), col+1)
            well = self.plate_data[row, col]
            if well is None:
                self.plate_panel.SetToolTipString("%s: no data" % well_name)
            else:
                text = "%s: %d files" % (
                    well_name,
                    sum([len(v) for v in well.values()]))
                self.plate_panel.SetToolTipString(text)
        
    def on_update(self):
        if (tuple(sorted(self.plate_choice.GetItems())) !=
            tuple(sorted(self.data.get_plate_names()))):
            plate_names = self.data.get_plate_names()
            self.plate_choice.SetItems(plate_names)
            if len(plate_names) > 0:
                self.plate_choice.SetSelection(0)
        self.plate_name = self.plate_choice.GetStringSelection()
        if self.plate_name in self.data.get_plate_names():
            self.plate_data = self.data.get_plate(self.plate_name)
        else:
            self.plate_data = None
        self.draw_plate()
        #
        # Set up the site grid size
        #
        if self.plate_data is not None:
            site_names = set()
            channel_names = set()
            for well in self.plate_data.flatten():
                if well is not None:
                    site_names.update(well.keys())
                    for sd in well.values():
                        channel_names.update(
                            [fd[PlateData.D_CHANNEL] 
                             if PlateData.D_CHANNEL in fd else str(i+1)
                             for i, fd in enumerate(sd)])
            update_values = self.site_grid.GetNumberRows() != len(site_names)
            if (self.site_grid.GetNumberRows() < len(site_names)):
                self.site_grid.AppendRows(
                    len(site_names) - self.site_grid.GetNumberRows())
            elif (self.site_grid.GetNumberRows() > len(site_names)):
                self.site_grid.DeleteRows(
                    numRows = self.site_grid.GetNumberRows() - len(site_names))
            side = int(np.ceil(np.sqrt(float(len(site_names)))))
            for i, site_name in enumerate(sorted(site_names)):
                self.site_grid.SetRowLabelValue(i, site_name)
                if update_values:
                    self.site_grid.SetCellValue(i, 0, str((i % side) + 1))
                    self.site_grid.SetCellValue(i, 1, str(int(i / side) + 1))
            update_values = self.channel_grid.GetNumberRows() != len(channel_names)
            if (self.channel_grid.GetNumberRows() < len(channel_names)):
                self.channel_grid.AppendRows(
                    len(channel_names) - self.channel_grid.GetNumberRows())
            elif (self.channel_grid.GetNumberRows() > len(channel_names)):
                self.channel_grid.DeleteRows(
                    numRows = self.channel_grid.GetNumberRows() - len(channel_names))
            for i, channel_name in enumerate(sorted(channel_names)):
                self.channel_grid.SetRowLabelValue(i, channel_name)
                if update_values:
                    for j in range(4):
                        self.channel_grid.SetCellValue(
                            i, j, 
                            str(255 if j == 3 or i == j else 0))
        
    def get_well_side(self):
        size = self.plate_panel.GetClientSizeTuple()
        size = (size[0] - self.get_border_width(),
                size[1] - self.get_border_height())
        w = size[0] / self.data.plate_layout[1]
        h = size[1] / self.data.plate_layout[0]
        return min(w, h)
    
    def get_center(self, row, column, side = None):
        if side is None:
            side = self.get_well_side()
        return (side * column + side / 2 + self.get_border_width(),
                side * row + side / 2 + self.get_border_height())
    
    def get_fill(self, well):
        n_files = sum([len(x) for x in well.values()])
        color = self.palette(float(n_files)/float(max(self.data.max_per_well, 1)),
                             bytes = True)
        color = wx.Colour(*color)
        return color
        
    def on_paint_plate(self, evt):
        assert isinstance(evt, wx.PaintEvent)
        if self.plate_bitmap == None:
            dc = wx.PaintDC(self.plate_panel)
            return
        else:
            dc = wx.BufferedPaintDC(self.plate_panel, self.plate_bitmap)
            
    def on_erase_background(self, evt):
        pass
    
    def get_radius(self):
        return max(self.get_well_side() / 2 - 1, 1)
    
    def plate_hit_test(self, x, y):
        '''Return the row and column of the well or None if not hit
        
        x, y - coordinates of pixel on plate panel surface
        '''
        side = self.get_well_side()
        col = (float(x) - self.get_border_width() - float(side) / 2) / side
        row = (float(y) - self.get_border_height() - float(side) / 2) / side
        irow, icol = [int(v + .5) for v in (row, col)]
        d = np.sqrt((row - irow) ** 2 + (col - icol) ** 2) * side
        if d > self.get_radius():
            return None
        if (irow < 0 or irow >= self.data.plate_layout[0] or
            icol < 0 or icol >= self.data.plate_layout[1]):
            return None
        return irow, icol
            
    def draw_plate(self):
        if self.plate_bitmap is not None:
            self.plate_bitmap.Destroy()
            self.plate_bitmap = None
        self.plate_panel.Refresh()
        width, height = [max(x, 1) for x in self.plate_panel.GetClientSize()]
        self.plate_bitmap = wx.EmptyBitmap(width, height, 32)
        dc = wx.MemoryDC(self.plate_bitmap)
        dc.SetBackground(wx.Brush(self.plate_panel.GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        gc.SetFont(self.plate_panel.GetFont())
        if self.plate_data is None:
            return
        side = self.get_well_side()
        radius = self.get_radius()
        gc.SetPen(wx.BLACK_PEN)
        for row in range(self.data.plate_layout[0]):
            text = chr(ord('A') + row)
            w, h = gc.GetTextExtent(text)
            y = self.get_center(row, 0, side)[1] - int(h / 2)
            gc.DrawText(text, 3, y)
            
        for col in range(self.data.plate_layout[1]):
            text = "%02d" % (col + 1)
            w, h, descent, leading = gc.GetFullTextExtent(text)
            x = self.get_center(0, col, side)[0] - w / 2
            gc.DrawText(text, x, 3)
            
        for row in range(self.data.plate_layout[0]):
            for col in range(self.data.plate_layout[1]):
                x, y = self.get_center(row, col, side)
                if (row < self.plate_data.shape[0] and
                    col < self.plate_data.shape[1]):
                    well = self.plate_data[row, col]
                    if well is None:
                        brush = wx.NullBrush
                    else:
                        brush = wx.Brush(self.get_fill(well))
                    gc.SetBrush(brush)
                    gc.DrawEllipse(x - radius, y - radius,
                                   radius * 2, radius * 2)
    def set_display_well(self, well):
        '''Set the display well and redraw the figure'''
        with self.image_dict_lock:
            self.image_dict = {}
            self.image_dict_generation += 1
        
        def fn():
            with self.image_dict_lock:
                generation = self.image_dict_generation
                
            for k, v in well.iteritems():
                sd = {}
                with self.image_dict_lock:
                    if self.image_dict_generation > generation:
                        return
                    self.image_dict[k] = sd
                for c, fd in enumerate(v):
                    if PlateData.D_CHANNEL in fd:
                        channel = fd[PlateData.D_CHANNEL]
                    else:
                        channel = str(c+1)
                    img = load_using_bioformats(fd[PlateData.D_FILENAME])
                    with self.image_dict_lock:
                        if self.image_dict_generation > generation:
                            return
                        sd[channel] = img
                wx.CallAfter(self.update_figure)
        t = threading.Thread(target = fn)
        t.setDaemon(True)
        t.start()
                
    def update_figure(self):
        if self.image_dict is None:
            return
        with self.image_dict_lock:
            image_dict = dict([(x, y.copy()) for x, y in self.image_dict.iteritems()])
        channel_dict = {}
        totals = np.zeros(4)
        for i in range(self.channel_grid.GetNumberRows()):
            channel_name = self.channel_grid.GetRowLabelValue(i)
            channel_dict[channel_name] = np.array([
                int(self.channel_grid.GetCellValue(i, j))
                for j in range(4)], float)
            totals += channel_dict[channel_name]
            
        site_dict = {}
        tile_dims = [0, 0]
        for i in range(self.site_grid.GetNumberRows()):
            site_name = self.site_grid.GetRowLabelValue(i)
            site_dict[site_name] = np.array([
                float(self.site_grid.GetCellValue(i, j)) - 1
                for j in range(2)])[::-1]
            tile_dims = [max(i0, i1) for i0, i1 in zip(
                site_dict[site_name], tile_dims)]
        img_size = [0, 0]
        for sd in image_dict.values():
            for channel in sd:
                img_size = [max(i0, i1) for i0, i1 in zip(
                    sd[channel].shape, img_size)]
        img_size = np.array(img_size)
        tile_dims = np.array(tile_dims)+1
        for k in site_dict:
            site_dict[k] *= img_size
        img_size = np.hstack([np.ceil(tile_dims * img_size).astype(int), [3]])
        megapicture = np.zeros(img_size, np.uint8)
        for site, sd in image_dict.iteritems():
            offs = site_dict[site].astype(int)
            # TO_DO - handle images that aren't scaled from 0 to 255
            for channel, image in sd.iteritems():
                imgmax = np.max(image)
                scale = 255 if imgmax < 256 else 4095 if imgmax < 4096 else 65535
                a = channel_dict[channel][3]
                rgb = channel_dict[channel][:3] / 255.
                image = image * a / scale
                if image.ndim < 3:
                    image = image[:, :, np.newaxis] * rgb[np.newaxis, np.newaxis, :]
                
                if image.shape[0] + offs[0] > megapicture.shape[0]:
                    image = image[:(megapicture.shape[0] - offs[0]), :, :]
                if image.shape[1] + offs[1] > megapicture.shape[1]:
                    image = image[:, :(megapicture.shape[1] - offs[1]), :]
                megapicture[offs[0]:(offs[0]+image.shape[0]),
                            offs[1]:(offs[1]+image.shape[1]), :] += image
        self.axes.cla()
        self.axes.imshow(megapicture)
        self.canvas.draw()
        self.toolbar.update()

if __name__=="__main__":
    import os
    import re
    import bioformats
    app = wx.PySimpleApp(True)
    dlg = wx.Dialog(None, size=(1024, 768), 
                    style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.THICK_FRAME)
    data = PlateData()
    root = r"\\iodine-cifs\imaging_analysis\2007_09_24_BBBC_ImagingPlatform\Fibroblasts"
    paths = [pathname2url(os.path.join(root, filename))
             for filename in os.listdir(root)
             if filename.startswith("plate")]
    filenames = []
    plates = []
    wells = []
    sites = []
    channels = []
    # example file name: HDFa030510P6hiP6loP20hiP20lo_A11_s1_w2E387A0AC-E9DE-42FA-8BBC-73F9BA938085.tif
    pattern = "^(?P<Plate>.+)_(?P<Well>[A-P][0-9]{2})_(?P<Site>s[0-9])_(?P<Channel>w[0-9])[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}.tif$"
    for path in paths:
        for filename in os.listdir(path):
            if filename.endswith(".tif"):
                m = re.match(pattern, filename)
                if m is not None:
                    d = m.groupdict()
                    filenames.append(os.path.join(path, filename))
                    plates.append(d["Plate"])
                    wells.append(d["Well"])
                    sites.append(d["Site"])
                    channels.append(d["Channel"])
    data.add_files(filenames, plates, wells, sites, channel_names = channels)
    viewer = PlateViewer(dlg, data)
    dlg.ShowModal()
    from cellprofiler.utilities.jutil import kill_vm
    kill_vm()
    os._exit(0)
    