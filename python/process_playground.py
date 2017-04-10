import psutil, subprocess
import time

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

if StartProcess('nfs-kernel-server'):
    print("TRUE")
else:
    print("FALSE")
