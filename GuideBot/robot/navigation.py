"""Single-owner G1 high-level velocity sink. Never changes gait, FSM or balance."""
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import time

from GuideBot.navigation.velocity import CommandLease, RPC_DURATION, ZERO, body_velocity, bounded_velocity, hardware_profile


def run(endpoint, directory, profile, token, interface='eth0', client=None):
    """A supplied fake client exercises the full watchdog without importing DDS."""
    profile=hardware_profile(profile)
    directory=Path(directory)
    lease_path=Path.home()/'.local/state/guidebot/navigation/velocity.lock'
    lease_path.parent.mkdir(parents=True,exist_ok=True)
    with lease_path.open('a') as owner:
        fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        hardware=client is None;waist=[None,0.];subscriber=None
        if hardware:
            from GuideBot.robot.audio.runtime import load_audio_sdk
            load_audio_sdk()
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
            ChannelFactoryInitialize(0, interface)
            client=LocoClient();client.SetTimeout(.15);client.Init()
            from unitree_sdk2py.core.channel import ChannelSubscriber
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
            def lowstate(message):
                try:
                    values=[float(message.motor_state[index].q) for index in (12,13,14)]
                    waist[:]=[values,time.monotonic()]
                except (IndexError,AttributeError,ValueError):waist[:]=[None,0.]
            subscriber=ChannelSubscriber('rt/lowstate',LowState_);subscriber.Init(lowstate,1)
        running=[True];parent_pid=os.getppid()
        def stop(signum,frame):running[0]=False
        old={sig:signal.signal(sig,stop) for sig in (signal.SIGINT,signal.SIGTERM)}
        lease=CommandLease(token)
        state=dict(motion_enabled=True, last_velocity=list(ZERO), calls=0, error=None,
                   watchdog_s=.25, robot_command_duration_s=RPC_DURATION)
        fsm_ok=False;last_fsm=0.;last_send=0.;last_report=0.
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as channel:
                channel.bind(str(endpoint));os.chmod(str(endpoint),0o600)
                channel.settimeout(.02)
                (directory/'velocity.ready').touch()
                while running[0] and os.getppid()==parent_pid:
                    now=time.monotonic()
                    try:
                        raw=channel.recv(4096)
                        lease.accept(json.loads(raw),time.monotonic())
                    except socket.timeout:pass
                    except (ValueError,TypeError,AttributeError) as error:
                        state['packet_error']=str(error);lease.deadline=0.
                    now=time.monotonic()
                    if now-last_fsm>=.5:
                        code,fsm=client.GetFsmId()
                        fsm_ok=code==0 and fsm==500
                        state.update(fsm=fsm,fsm_ok=fsm_ok);last_fsm=time.monotonic()
                    waist_ok=(not hardware or (waist[0] is not None and time.monotonic()-waist[1]<.3 and
                        all(abs(q-reference)<=.03 for q,reference in zip(waist[0],profile['waist_reference_rad']))))
                    state.update(fsm_ok=fsm_ok and waist_ok,waist_ok=waist_ok,waist_rad=waist[0])
                    velocity=lease.current(time.monotonic()) if running[0] and fsm_ok and waist_ok else ZERO
                    velocity=bounded_velocity(body_velocity(velocity,profile))
                    if now-last_send>=.08:
                        code=client.SetVelocity(*velocity,duration=RPC_DURATION)
                        if code!=0:raise RuntimeError('G1 SetVelocity rejected: '+str(code))
                        state.update(last_velocity=list(velocity),calls=state['calls']+1)
                        last_send=time.monotonic()
                    if now-last_report>.2:
                        state['updated_at']=time.monotonic()
                        tmp=directory/'velocity-status.tmp';tmp.write_text(json.dumps(state));tmp.replace(directory/'velocity-status.json')
                        last_report=now
        except Exception as error:
            state['error']=type(error).__name__+': '+str(error)
            raise
        finally:
            # Short robot-side duration also bounds motion if this process is killed.
            try:state['stop_return_code']=client.SetVelocity(*ZERO,duration=RPC_DURATION)
            finally:
                state.update(stopped=True,last_velocity=list(ZERO),updated_at=time.monotonic())
                (directory/'velocity-status.json').write_text(json.dumps(state,indent=2))
                Path(endpoint).unlink(missing_ok=True)
                for sig,handler in old.items():signal.signal(sig,handler)


if __name__=='__main__':
    import argparse
    import yaml
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--endpoint',required=True);p.add_argument('--directory',required=True,type=Path)
    p.add_argument('--hardware',required=True,type=Path);p.add_argument('--interface',default='eth0')
    p.add_argument('--token-file',required=True,type=Path)
    a=p.parse_args()
    run(a.endpoint,a.directory,yaml.safe_load(a.hardware.read_text()),a.token_file.read_text().strip(),a.interface)
