from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

#
# This is a standarrdarized data diction for vnavs.
# The base was developed for the filteer parms in darkroom and then
# OpticChiasm. It was then used to replace the simple dictionary
# for cameraman orders and the goal is for it to eventually support
# all vnavs messages. This will be sued for message validation and
# to provide mission_control with click-box selection of properties
# to display.
#
class Dict(object):
    __slots__ = ('attribs')

    def __init__(self):
        self.attribs = {}

    def AddAttrib(self, attrib):
        self.attribs[attrib.name] = attrib

    def ValidatePayload(self, payload, target=None):
        for this_attrib in self.attribs.values():
            key = this_attrib.name
            if key in payload:
                value = payload[key]
                value, fld_valid = this_attrib.Validate(value)
                if fld_valid and (target is not None):
                    setattr(target, key, value)

#
# DataAttrib.GetValue() must be exception-safe.
# The application runs in multiple threads (tkinter, vnavs_mqtt and main().
# Step execution may be called while the user is editing, so a partially edited
# value may be picked up.
#
# This is probably a bug, not a feature. Execution should be orderly and only
# in the main() thread. But maintining this rule keeps the system as user friendly
# as possible in the event of errors and doesn't really have a downside except
# perhaps a flash of odd results if the step is executed while the user is editing.
#
class DataAttrib(object):
    __slots__ = ('caption', 'default', 'name', 'max_value', 'min_value',
                        'use_slider', 'values')
    def __init__(self, name, default, click_point=False,
				min_value=None, max_value=None, use_slider=False):
        self.name = name
        self.default = default
        self.click_point = click_point
        self.min_value = min_value
        self.max_value = max_value
        self.use_slider = use_slider
        self.values = []                    # a list of valid values for field
        if self.click_point:
            self.caption = self.name + ' (PP)'
        else:
            self.caption = self.name

    def Transform(self, value):
        return value

    def Validate(self, value):
        try:
            value = self.Transform(value)
        except:
            return value, False
        if self.min_value is not None:
            if value < self.min_value:
                return value, False
        if self.max_value is not None:
            if value > self.min_value:
                return value, False
        if len(self.values) > 0:
            if not (value in self.values):
                return value, False
        return value, True

class DataAttribFloat(DataAttrib):
    def GetValue(self, raw_value):
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
        return str(float(raw_value))

    def Transform(self, value):
        return float(value)

class DataAttribInt(DataAttrib):
    def GetValue(self, raw_value):
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
        try:
            i = int(raw_value)
        except:
            i = 0
        return str(i)

    def Transform(self, value):
        return int(value)

class DataAttribStr(DataAttrib):
    def __init__(self, name, default, values=[]):
        super().__init__(name, default)
        self.values = values

    def GetValue(self, raw_value):
        if raw_value is None:
            raw_value = ''
        v = raw_value.strip()
        if '"' in v:
            v = ''
        if "'" in v:
            v = ''
        return v

class DataAttribPoint(DataAttrib):
    # This is a numpy / mathematical point

    def GetValue(self, raw_value):
        v = raw_value.split(',')
        if len(v) != 2:
            return None
        try:
            x = int(v[0].strip())
            y = int(v[1].strip())
        except ValueError:
            # not a valid integer string
            return None
        return "({},{})".format(x, y)

class DataAttribPointSym(DataAttrib):
    def __init__(self, name, default, click_point=True):
        super().__init__(name, default, click_point=click_point)

    def GetValue(self, raw_value):
        # The defaults of 'b' and 'e' works well for ranges like CropYX.
        # Not so much for points like CropPP.
        v = raw_value.split(',')
        x = ''
        y = ''
        if len(v) >= 1:
            x = v[0].strip()
        if len(v) >= 2:
            y = v[1].strip()

        if x == '':
            x = 'b'
        if y == '':
            y = 'e'
        return "('{}','{}')".format(x, y)
