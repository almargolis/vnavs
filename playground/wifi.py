# PyObjC - the Python to Objective-C bridge 
# CWNetwork is a NSSet network descriptor
# NSSet is an Objective-C set

# Really helpful Python example:
#		https://clburlison.com/macos-wifi-scanning/
# Apple Objective-C library documentation:
#		https://developer.apple.com/documentation/corewlan/cwinterface
#
# I will need a corresponding library for Linux. This seems like the best bet:
#		https://github.com/digidotcom/python-wpa-supplicant

import objc

n1 = 'VnavsControl_5G'
n2 = 'NSA-Node1_5G'

objc.loadBundle('CoreWLAN',
                bundle_path = '/System/Library/Frameworks/CoreWLAN.framework',
                module_globals = globals())

iface = CWInterface.interface()

networks, error = iface.scanForNetworksWithName_error_(None, None)
print("ERR", error)
#print(networks)

for ix, this_net in enumerate(networks):
    #print(type(this_net))
    #print(help(this_net))
    #print(this_net.__class__.__name__)
    print(this_net.ssid())

iface = CWInterface.interface()
iface.disassociate()

networks, error = iface.scanForNetworksWithName_error_(n1, None)
network = networks.anyObject()
success, error = iface.associateToNetwork_password_error_(network, '<Password Of Network>', None)
