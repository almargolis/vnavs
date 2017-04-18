from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import psutil
import subprocess
import time

import vnavs_mqtt

SYSTEMCTL = '/bin/systemctl'

def RunCommand(cmd):
    start_time = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        proc.poll()
        if p.returncode is None:
            print("Process is still running")
            time.sleep(10)
        else:
            return proc

def CheckSystemctlState(service_name):
    cmd = [SYSTEMCTL, 'is-active', service_name]
    proc = RunCommand(cmd)
    r = proc.stdout.read()
    if r == 'active\n':
        return True
    else:
        return False

def StartSystemctl(service_name):
    cmd = ['sudo', SYSTEMCTL, 'start', service_name]
    proc = RunCommand(cmd)
    # we might want to log stdout result r
    print("result code:", p.returncode)
    r = proc.stdout.read()
    print("***********")
    print(r)
    print("***********")
    return CheckSystemctlState(service_name)

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

    def DoLoop(self):
        for pname, pspec in self.process_specs:
            parts = pspec.split(':')
            if parts[0] == 's':
                service = parts[1]
                if not CheckSystemctlState(service):
                    StartSystemctl(service)
        time.sleep(60)

if StartProcess('nfs-kernel-server'):
    print("TRUE")
else:
    print("FALSE")

def Run():
    p = process()
    p.Loop()
    p.Disconnect()

if __name__ == '__main__':
    if sys.argv[1] == 'run':
        Run()
