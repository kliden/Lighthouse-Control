import asyncio, platform, pathlib, sys, os
from enum import Enum

from bleak import *

import gui
import terminal


SCAN_TIMEOUT = 15


class PowerState(Enum):
    V1_ON = b'\x12\x00\x00\x28\xFF\xFF\xFF\xFF\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    V1_OFF = b'\x12\x01\x00\x28\xFF\xFF\xFF\xFF\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

    V2_ON = b'\x01'
    V2_OFF = b'\x00'

    # This state appears to be returned by a read of the v2 power handle (17) when a device has recently been
    # powered on and before its power state has been written. I don't know if the v1 lighthouses return this.
    STARTUP = b'\x20'

    def from_name(power_state_str: str, version: int=2):
        full_str = f"{"V1" if version == 1 else "V2"}_{power_state_str.upper()}"
        for state in PowerState:
            if full_str == state.name:
                return state
        raise ValueError("Invalid PowerState.name: ", power_state_str)

    def from_value(power_state_value: bytes):
        for state in PowerState:
            if state.value == power_state_value:
                return state
        raise ValueError("Invalid PowerState.value ", power_state_value.hex())

    def from_version(version: int):
        if version == 1:
            return (PowerState.V1_ON, PowerState.V2_OFF)
        elif version == 2:
            return (PowerState.V2_ON, PowerState.V2_OFF)
        else:
            raise ValueError("Invalid PowerState version: ", str(version))
    
    def short_name(self):
        return self.name.split("_")[1].lower()
    
    def is_on(self):
        return (
            self == PowerState.V1_ON or 
            self == PowerState.V2_ON or
            self == PowerState.STARTUP)


class Lighthouse:
    V1_NAME_PREFIX = "HTC BS "
    V1_POWER_CHAR = "00001524-1212-efde-1523-785feabcd123"

    V2_NAME_PREFIX = 'LHB-'
    V2_POWER_HANDLE = 17

    def __init__(self, device: BLEDevice, version: int, rssi: int):
        self._device = device
        self._version = version
        self._rssi = rssi
        self._is_on = None
        self._gatt_char = self.V1_POWER_CHAR if version == 1 else self.V2_POWER_HANDLE
        self._on_state, self._off_state = PowerState.from_version(version)
        self._power_lock = asyncio.Lock()

    def __hash__(self):
        return hash(self._device)
    
    def __eq__(self, other):
        return (
            isinstance(other, Lighthouse) and 
            self._device == other._device
        )
    
    @property
    def name(self):
        return self._device.name

    @property
    def rssi(self):
        return self._rssi

    @property
    def address(self):
        return self._device.address
    
    @property
    def is_on(self):
        return self._is_on

    # We use retries instead of a timeout because BleakClient doesn't support a graceful timeout for 
    # reading and writing.
    async def write(self, is_on: bool, retries: int=10):
        if self._is_on != is_on:
            async with self._power_lock:
                write_power_state = self._on_state if is_on else self._off_state
                for r in range(retries):
                    try:
                        async with BleakClient(self._device) as client:
                            read_bytes = await client.read_gatt_char(self._gatt_char)
                            read_power_state = PowerState.from_value(read_bytes)
                            if read_power_state.is_on() == is_on:
                                self._is_on = is_on
                                return self
                            else:
                                await client.write_gatt_char(self._gatt_char, write_power_state.value, response=False)
                    except (BleakError, OSError) as e:
                        print(f"{self.address}: {e}. Retry ({r + 1}/{retries}).")
    
    async def read(self, retries: int=10):
        async with self._power_lock:
            for r in range(retries):
                try:
                    async with BleakClient(self._device) as client:
                        power_state = await client.read_gatt_char(self._gatt_char)
                        self._is_on = PowerState.from_value(power_state).is_on()
                        return self._is_on
                except (BleakError, OSError) as e:
                    print(f"{self.address}: {e}. Retry ({r + 1}/{retries}).")

    @staticmethod
    async def iter(timeout: int=SCAN_TIMEOUT):
        async with asyncio.timeout(timeout):
            lighthouse_queue = asyncio.Queue()
            def on_device_detected(device, advertisement_data):
                if device.name:
                    version = None
                    if device.name.startswith(Lighthouse.V1_NAME_PREFIX):
                        version = 1
                    elif device.name.startswith(Lighthouse.V2_NAME_PREFIX):
                        version = 2
                    if version:
                        lh = Lighthouse(device, version, advertisement_data.rssi)
                        asyncio.create_task(lighthouse_queue.put(lh))
            async with BleakScanner(on_device_detected):
                while True:
                    yield await lighthouse_queue.get()


def default_script_folder():
    folder = pathlib.Path.home() / 'OneDrive' / 'Desktop'
    if not folder.exists():
        folder = pathlib.Path.home() / 'Desktop'
        if not folder.exists():
            folder = pathlib.Path.home()
    return folder
            

def create_scripts(destination_folder: pathlib.Path, mac_addresses: list, no_window: bool):
    this_file_path = pathlib.Path.cwd() / sys.argv[0]
    cmd_parts_start = []
    if this_file_path.suffix == '.py':
        cmd_parts_start = ['python']
        cmd_parts_start.append(str(this_file_path))
    else:
        cmd_parts_start.append(str(this_file_path.with_stem('lighthouse_console')))
    
    def create_single_script(is_on: bool):
        state_str = 'on' if is_on else 'off'
        cmd = " ".join(cmd_parts_start + [state_str] + mac_addresses)
        file_stem = f"lh_{state_str.upper()}"
        is_windows = platform.system() == 'Windows'
        if is_windows:
            if no_window:
                filename = f"{file_stem}.vbs"
                contents = f'CreateObject("Wscript.Shell").Run "{cmd}", 0, False\n'
            else:
                filename = f"{file_stem}.bat"
                contents = f"@echo off\n{cmd}\n"
        else:
            filename = f"{file_stem}.sh"
            contents = f"#!/bin/bash\n{cmd}\n"

        dest_path = destination_folder / filename
        dest_path.touch()
        dest_path.write_text(contents)

        if not is_windows:
            os.chmod(str(dest_path), 0o755)  
        
        return str(dest_path)
    on_path = create_single_script(True)
    off_path = create_single_script(False)

    return (on_path, off_path)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        gui.main()
    else:
        asyncio.run(terminal.main())
