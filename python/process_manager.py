from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import psutil
import subprocess
import time

import vnavs_mqtt

SYSTEMCTL = '/bin/systemctl'

def CheckProcessState(process_name):
    p = [SYSTEMCTL, 'is-active', process_name]
    with psutil.Popen(p, stdout=subprocess.PIPE) as proc:
        r = proc.stdout.read()
        if r == 'active\n':
            return True
        else:
            return False

def StartProcess(process_name):
    cmd = ['sudo', SYSTEMCTL, 'start', process_name]
    start_time = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        p.poll()
        if p.returncode is None:
            print("Process is still running")
            time.sleep(10)
        else:
            # we might want to log stdout result r
            print("result code:", p.returncode)
            r = p.stdout.read()
            print("***********")
            print(r)
            print("***********")
            return CheckProcessState(process_name)

def PiShutdown():
    command = "/usr/bin/sudo /sbin/shutdown -h now"
    process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
    output = process.communicate()[0]
    print(output)

class process(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=['process/orders'],
					Readers=[],
					Blocking=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.process_specs = self.config.items("ProcessMonitor")
        self.startTime = time.time()

if StartProcess('nfs-kernel-server'):
    print("TRUE")
else:
    print("FALSE")

def Run():
    p = process()
    p.Connect()
    p.Loop()
    p.Disconnect()

if __name__ == '__main__':
    Run()
