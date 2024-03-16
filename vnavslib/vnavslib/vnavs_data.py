import json
import os

#
# This is a standardized data dictionary for vnavs.
# The base was developed for the filter parms in darkroom and then
# opticchiasm. It was then used to replace the simple dictionary
# for cameraman orders and the goal is for it to eventually support
# all vnavs messages. This will be used for message validation and
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

class DataAttribIntList(DataAttrib):
    def GetValue(self, raw_value):
        import opticchiasm as oc
        r = []
        parts = raw_value.split(',')
        for this in parts:
            s = this.strip()
            if s[:3] == 'oc.':
                property_name = s[3:]
                s2 = getattr(oc, property_name)
                i = int(s2)
            else:
                i = int(s)
            r.append(i)
        return r

class DataAttribFloat(DataAttrib):
    def GetValue(self, raw_value):
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
        return str(float(raw_value))

    def Transform(self, value):
        return bool(value)

class DataAttribBoolean(DataAttrib):
    def GetValue(self, raw_value):
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            raw_value = raw_value.strip().lower()
            if raw_value in ['t', 'true']:
                return True
            else:
                return False
        return str(raw_value)

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

dkey_field_name = '_dkey_'
dgroup_field_name = '_dgrp_'
dclass_field_name = '_class_'
dfqn_field_name = '_dfqn_'
dpayload_field_name = '_payload_'
dprimitive_field_name = '_v_'

class PersistentClass(object):
    def __init__(self, class_object, factory_function, payload_function=None):
        self.class_object = class_object
        self.factory_function = factory_function
        self.payload_function = payload_function

KnownClasses = {}

def RegisterClass(registration):
    global KnownClasses
    KnownClasses[registration.class_object.__name__] = registration

def StringFactory(payload):
    return str(payload[dprimitive_field_name])

def PrimitivePayload(ddata):
    payload = {}
    payload[dprimitive_field_name] = ddata
    return payload

def SlotsPayload(ddata):
    payload = {}
    for this in ddata.__slots__:
        payload[this] = getattr(ddata, this)
    return payload

def MakeRegistrations():
    # This is a function instead of in-line so it has its own address space for imports.
    # Otherwise we get import cycles since most modules use this.
    from vnavsrun import engineer_1
    RegisterClass(PersistentClass(str, StringFactory, PrimitivePayload))
    RegisterClass(PersistentClass(engineer_1.Position, engineer_1.PositionFactory, SlotsPayload))
MakeRegistrations()

class PersistentData(object):
    def __init__(self):
        self.persistent_data = None
        self.key_group = None

    def SetDefaultKeyGroup(self, key_group):
        self.key_group = key_group

    def Save(self):
        if self.persistent_data is None:
            return					# its was never loaded

        path = os.path.expanduser('~/vnavs.data')
        d = json.dumps(self.persistent_data)
        f = open(path, 'w')
        #f.write(d.decode("utf-8"))
        f.write(d)
        f.close()

    def Load(self):
        if self.persistent_data is not None:
            return					# its already loaded
        path = os.path.expanduser('~/vnavs.data')
        try:
            f = open(path, 'r')
        except IOError as e:
            # IOError: [Errno 2] No such file or directory: '/bot1/images/R20170513114208_0_11202.jpeg'
            if e.errno == 2:
                self.persistent_data = {}
                return
            else:
                raise

        d = f.read()
        f.close()
        if d == "":
            self.persistent_data = {}
        else:
            self.persistent_data = json.loads(d)

    def MakeFqnKey(self, key, key_group=None):
        if key_group is None:
            key_group = self.key_group
        if (key_group is None) or (key_group == '/'):
            fqn_key = key
        else:
            fqn_key = key_group + '.' + key
        return fqn_key

    def Get(self, key, key_group=None):
        self.Load()
        fqn_key = self.MakeFqnKey(key, key_group=key_group)
        pdata = self.persistent_data.get(fqn_key, None)
        if pdata is None:
            return None
        payload = pdata[dpayload_field_name]
        class_name = pdata[dclass_field_name]
        class_registration = KnownClasses[class_name]
        object_instance = class_registration.factory_function(payload)
        return object_instance

    def GetPdata(self, key, key_group=None):
        self.Load()
        fqn_key = self.MakeFqnKey(key, key_group=key_group)
        pdata = self.persistent_data.get(fqn_key, None)
        return pdata

    def PutPayload(self, key, class_name, payload, key_group=None):
        self.Load()
        fqn_key = self.MakeFqnKey(key, key_group=key_group)
        pdata = {}
        pdata[dkey_field_name] = key
        pdata[dgroup_field_name] = key_group
        pdata[dfqn_field_name] = fqn_key
        pdata[dclass_field_name] = class_name
        pdata[dpayload_field_name] = payload
        self.persistent_data[fqn_key] = pdata
        self.Save()

    def PutPdata(self, pdata):
        # assume pdata is properly formatted ready to store
        self.Load()
        fqn_key = pdata[dfqn_field_name]
        self.persistent_data[fqn_key] = pdata
        self.Save()

    def Put(self, key, value, key_group=None):
        # value must be register in KnownClasses
        self.Load()
        class_name = value.__class__.__name__
        class_registration = KnownClasses[class_name]
        payload = class_registration.payload_function(value)
           # raise TypeError('Object of type % is not JSON serialiazable.'.format(value.__class__.__name__))
        self.PutPayload(key, class_name, payload, key_group=key_group)

    def Transform(self, payload):
        if (payload is None) or (not (vconst.dtype_field_name in payload)):
            return payload
        dtype = payload[vconst.dtype_field_name]
        if dtype == 'object':
            transform = object()
            for key, value in payload.items():
                setattr(transform, key, value)
            return transform
        return payload

