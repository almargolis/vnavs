import os
import platform
import subprocess
import sys
import time

import vnavs_const as vconst
import vnavs_comms as vcomms
import vnavs_mqtt as vmqtt

SYSTEMCTL = '/bin/systemctl'

class SystemProcess(object):
    def __init__(self):
        self.system_release = platform.release()

class LinuxProcess(SystemProcess):
    def __init__(self):
        super().__init__()

    def WirelessNetworks(self):
        cmd = ['sudo', '/sbin/iw', 'wlan0', 'scan']
        proc = RunCommand(cmd)
        for this in proc.stdout.readlines():
            t = this.strip()
            parts = t.split(':')
            if parts[0] in ['SSID', 'last seen']:
                print(parts)

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

class process(vmqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[vmqtt.Subscription(vconst.process_log_list_topic, async_delivery=True, handler=self.DoProcessLogList, LatestOnly=False)],
					SingleThreaded=False, BlockIfNotConnected=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.system =  platform.system()
        if self.system == 'Linux':
            self.system_process = LinuxProcess()
        else:
            self.system_process = None
        self.process_specs = self.config.items("ProcessMonitor")
        self.archive_dir = self.config.get(vcomms.FMQTT_INI_SECTION, vcomms.FMQTT_ARCHIVE_DIR)
        self.archive_dir = os.path.expanduser(self.archive_dir)               # this expands tilde in path

        self.startTime = time.time()
        self.loop_sleep = 60

    def DoProcessLogList(self, payload):
        print("DoProcessLogList()")
        fn = os.path.join(self.archive_dir, 'foo.txt')
        fd = os.open(fn, os.O_RDWR|os.O_CREAT )
        info = os.fstatvfs(fd)
        free_space = info.f_bfree
        os.close(fd)
        # os.remove()
        ext_len = len(vcomms.FMQTT_LOG_EXTENSION)
        flist = os.listdir(self.archive_dir)
        log_list = []
        for this in flist:
            if this[-ext_len:] == vcomms.FMQTT_LOG_EXTENSION:
                log_list.append(this)
        result_payload = vcomms.PrepareResponse(payload, ConfResponse=True)
        result_payload['log_list'] = log_list
        result_payload['free_space'] = free_space
        self.Publish(vconst.process_result_topic, result_payload)

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

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        vmqtt.LaunchNode(process)
    p = LinuxProcess()
    p.WirelessNetworks()
