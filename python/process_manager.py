from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import subprocess
import sys
import time

import vnavs_mqtt

SYSTEMCTL = '/bin/systemctl'

def RunCommand(cmd, Shell=False):
    print("RUN COMMAND", cmd)
    start_time = time.time()
    proc = subprocess.Popen(cmd, shell=Shell, stdout=subprocess.PIPE)
    while True:
        proc.poll()
        if proc.returncode is None:
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
    PrintProcResult(proc)
    return CheckSystemctlState(service_name)

def PrintProcResult(proc):
    print("result code:", proc.returncode)
    r = proc.stdout.read()
    print("***********")
    print(r)
    print("***********")

def GetScreenList():
    screens = []
    proc = RunCommand(['screen', '-ls'])
    output = proc.stdout.readlines()
    for this in output:
        parts = this.split(' ')
        # ['\t794.webserver\t(04/21/2017', '03:29:34', 'AM)\t(Detached)\n']
        dot = parts[0].find('.')
        if dot >= 0:
            tab = parts[0].find('\t', dot+1)
            if tab >= 0:
                this_screen = parts[0][dot+1:tab]
                screens.append(this_screen)
    return screens

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
        self.loop_sleep = 60

    def DoLoop(self):
        screens = GetScreenList()
        for pname, pspec in self.process_specs:
            parts = pspec.split(':')
            if parts[0] == 's':
                service = parts[1]
                if not CheckSystemctlState(service):
                    StartSystemctl(service)
            elif parts[0] == 'm':
                mountpoint = parts[1]
                proc = RunCommand(['mountpoint', '-q', mountpoint])
                if proc.returncode != 0:
                    proc = RunCommand(['sudo', 'mount', mountpoint])
            elif parts[0] == 'v':
                vnavs_process = parts[1]
                if vnavs_process not in screens:
                    proc = RunCommand('screen -d -m -S %s /bin/bash ~/projects/vnavs/launch/run_%s' % (vnavs_process, vnavs_process), Shell=True)
                    PrintProcResult(proc)

def Run():
    p = process()
    p.Loop()
    p.Disconnect()

if __name__ == '__main__':
    if sys.argv[1] == 'run':
        Run()
