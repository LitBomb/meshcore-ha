#!/usr/bin/python
""" 
    mccli.py : CLI interface to MeschCore BLE companion app
"""
import asyncio
import serial_asyncio
import os
import sys
import getopt
import json
import datetime
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakDeviceNotFoundError

UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# default address is stored in a config file
MCCLI_CONFIG_DIR = str(Path.home()) + "/.config/mc-cli/"
MCCLI_ADDRESS = MCCLI_CONFIG_DIR + "default_address"

# Fallback address if config file not found
# if None or "" then a scan is performed
ADDRESS = ""

def printerr (s) :
    sys.stderr.write(str(s))
    sys.stderr.write("\n")
    sys.stderr.flush()

class SerialConnection:
    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.frame_started = False
        self.frame_size = 0
        self.header = b""
        self.inframe = b""

    class MCSerialClientProtocol(asyncio.Protocol):
        def __init__(self, cx):
            self.cx = cx

        def connection_made(self, transport):
            self.cx.transport = transport
#            printerr('port opened')
            transport.serial.rts = False  # You can manipulate Serial object via transport
    
        def data_received(self, data):
#            printerr('data received')
            self.cx.handle_rx(data)    
    
        def connection_lost(self, exc):
            printerr('port closed')
    
        def pause_writing(self):
            printerr('pause writing')
    
        def resume_writing(self):
            printerr('resume writing')

    async def connect(self):
        """
        Connects to the device
        """
        loop = asyncio.get_running_loop()
        await serial_asyncio.create_serial_connection(
                loop, lambda: self.MCSerialClientProtocol(self), 
                self.port, baudrate=self.baudrate)

        printerr("Serial Connexion started")
        return self.port

    def set_mc(self, mc) :
        self.mc = mc

    def handle_rx(self, data: bytearray):
        headerlen = len(self.header)
        framelen = len(self.inframe)
        if not self.frame_started : # wait start of frame
            if len(data) >= 3 - headerlen:
                self.header = self.header + data[:3-headerlen]
                self.frame_started = True
                self.frame_size = int.from_bytes(self.header[1:], byteorder='little')
                self.handle_rx(data[3-headerlen:])
            else:
                self.header = self.header + data
        else:
            if framelen + len(data) < self.frame_size:
                self.inframe = self.inframe + data
            else:
                self.inframe = self.inframe + data[:self.frame_size-framelen]
                if not self.mc is None:
                    self.mc.handle_rx(self.inframe)
                self.frame_started = False
                self.header = b""
                self.inframe = b""
                if framelen + len(data) > self.frame_size:
                    self.handle_rx(data[self.frame_size-framelen:])

    async def send(self, data):
        size = len(data)
        pkt = b"\x3c" + size.to_bytes(2, byteorder="little") + data
#        printerr(f"sending pkt : {pkt}")
        self.transport.write(pkt)

class TCPConnection:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.transport = None

    class MCClientProtocol:
        def __init__(self, cx):
            self.cx = cx

        def connection_made(self, transport):
            self.cx.transport = transport
    
        def data_received(self, data):
            self.cx.handle_rx(data)

        def error_received(self, exc):
            printerr(f'Error received: {exc}')
    
        def connection_lost(self, exc):
            printerr('The server closed the connection')

    async def connect(self):
        """
        Connects to the device
        """
        loop = asyncio.get_running_loop()
        await loop.create_connection(
                lambda: self.MCClientProtocol(self), 
                self.host, self.port)

        printerr("TCP Connexion started")
        return self.host

    def set_mc(self, mc) :
        self.mc = mc

    def handle_rx(self, data: bytearray):
        cur_data = data
        while (len(cur_data) > 0) :
            if cur_data[0] != 0x3E :
                printerr(f"Error with received frame trying anyway ... first byte is {cur_data[0]}")
        
            frame_size = int.from_bytes(cur_data[1:2], byteorder='little')
            frame = cur_data[3:3+frame_size]

            if not self.mc is None:
                self.mc.handle_rx(frame)
        
            cur_data = cur_data[3+frame_size:]

    async def send(self, data):
        size = len(data)
        pkt = b"\x3c" + size.to_bytes(2, byteorder="little") + data
        self.transport.write(pkt)

class BLEConnection:
    def __init__(self, address):
        """ Constructor : specify address """
        self.address = address
        self.client = None
        self.rx_char = None
        self.mc = None

    async def connect(self):
        """
        Connects to the device

        Returns : the address used for connection
        """
        def match_meshcore_device(_: BLEDevice, adv: AdvertisementData):
            """ Filter to mach MeshCore devices """
            if not adv.local_name is None\
                    and adv.local_name.startswith("MeshCore")\
                    and (self.address is None or self.address in adv.local_name) :
                return True
            return False

        if self.address is None or self.address == "" or len(self.address.split(":")) != 6 :
            scanner = BleakScanner()
            printerr("Scanning for devices")
            device = await scanner.find_device_by_filter(match_meshcore_device)
            if device is None :
                return None
            printerr(f"Found device : {device}")
            self.client = BleakClient(device)
            self.address = self.client.address
        else:
            self.client = BleakClient(self.address)

        try:
            await self.client.connect(disconnected_callback=self.handle_disconnect)
        except BleakDeviceNotFoundError:
            return None
        except TimeoutError:
            return None

        await self.client.start_notify(UART_TX_CHAR_UUID, self.handle_rx)

        nus = self.client.services.get_service(UART_SERVICE_UUID)
        self.rx_char = nus.get_characteristic(UART_RX_CHAR_UUID)

        printerr("BLE Connexion started")
        return self.address

    def handle_disconnect(self, _: BleakClient):
        """ Callback to handle disconnection """
        printerr ("Device was disconnected, goodbye.")
        # cancelling all tasks effectively ends the program
        for task in asyncio.all_tasks():
            task.cancel()

    def set_mc(self, mc) :
        self.mc = mc

    def handle_rx(self, _: BleakGATTCharacteristic, data: bytearray):
        if not self.mc is None:
            self.mc.handle_rx(data)

    async def send(self, data):
        await self.client.write_gatt_char(self.rx_char, bytes(data), response=False)

class MeshCore:
    """
    Interface to a BLE MeshCore device
    """
    self_info={}
    contacts={}

    def __init__(self, cx):
        """ Constructor : specify address """
        self.time = 0
        self.result = asyncio.Future()
        self.contact_nb = 0
        self.rx_sem = asyncio.Semaphore(0)
        self.ack_ev = asyncio.Event()
        self.login_resp = asyncio.Future()
        self.status_resp = asyncio.Future()

        self.cx = cx
        cx.set_mc(self)

    async def connect(self) :
        await self.send_appstart()

    def handle_rx(self, data: bytearray):
        """ Callback to handle received data """
        match data[0]:
            case 0: # ok
                if len(data) == 5 :  # an integer
                    self.result.set_result(int.from_bytes(data[1:5], byteorder='little'))
                else:
                    self.result.set_result(True)
            case 1: # error
                self.result.set_result(False)
            case 2: # contact start
                self.contact_nb = int.from_bytes(data[1:5], byteorder='little')
                self.contacts={}
            case 3: # contact
                c = {}
                c["public_key"] = data[1:33].hex()
                c["type"] = data[33]
                c["flags"] = data[34]
                c["out_path_len"] = int.from_bytes(data[35:36], signed=True)
                plen = int.from_bytes(data[35:36], signed=True)
                if plen == -1 : 
                    plen = 0
                c["out_path"] = data[36:36+plen].hex()
                c["adv_name"] = data[100:132].decode().replace("\0","")
                c["last_advert"] = int.from_bytes(data[132:136], byteorder='little')
                c["adv_lat"] = int.from_bytes(data[136:140], byteorder='little',signed=True)/1e6
                c["adv_lon"] = int.from_bytes(data[140:144], byteorder='little',signed=True)/1e6
                c["lastmod"] = int.from_bytes(data[144:148], byteorder='little')
                self.contacts[c["adv_name"]]=c
            case 4: # end of contacts
                self.result.set_result(self.contacts)
            case 5: # self info
                self.self_info["adv_type"] = data[1]
                self.self_info["tx_power"] = data[2]
                self.self_info["max_tx_power"] = data[3]
                self.self_info["public_key"] = data[4:36].hex()
                self.self_info["adv_lat"] = int.from_bytes(data[36:40], byteorder='little', signed=True)/1e6
                self.self_info["adv_lon"] = int.from_bytes(data[40:44], byteorder='little', signed=True)/1e6
                #self.self_info["reserved_44:48"] = data[44:48].hex()
                self.self_info["radio_freq"] = int.from_bytes(data[48:52], byteorder='little')
                self.self_info["radio_bw"] = int.from_bytes(data[52:56], byteorder='little')
                self.self_info["radio_sf"] = data[56]
                self.self_info["radio_cr"] = data[57]
                self.self_info["name"] = data[58:].decode()
                self.result.set_result(True)
            case 6: # msg sent
                res = {}
                res["type"] = data[1]
                res["expected_ack"] = bytes(data[2:6])
                res["suggested_timeout"] = int.from_bytes(data[6:10], byteorder='little')
                self.result.set_result(res)
            case 7: # contact msg recv
                res = {}
                res["type"] = "PRIV"
                res["pubkey_prefix"] = data[1:7].hex()
                res["path_len"] = data[7]
                res["txt_type"] = data[8]
                res["sender_timestamp"] = int.from_bytes(data[9:13], byteorder='little')
                if data[8] == 2 : # signed packet
                    res["signature"] = data[13:17].hex()
                    res["text"] = data[17:].decode()
                else :
                    res["text"] = data[13:].decode()
                self.result.set_result(res)
            case 8 : # chanel msg recv
                res = {}
                res["type"] = "CHAN"
                res["channel_idx"] = data[1]
                res["path_len"] = data[2]
                res["txt_type"] = data[3]
                res["sender_timestamp"] = int.from_bytes(data[4:8], byteorder='little')
                res["text"] = data[8:].decode()
                self.result.set_result(res)
            case 9: # current time
                self.result.set_result(int.from_bytes(data[1:5], byteorder='little'))
            case 10: # no more msgs
                self.result.set_result(False)
            case 11: # contact
                self.result.set_result("meshcore://" + data[1:].hex())
            case 12: # battery voltage
                self.result.set_result(int.from_bytes(data[1:2], byteorder='little'))
            # push notifications
            case 0x80:
                printerr ("Advertisment received")
            case 0x81:
                printerr ("Code path update")
            case 0x82:
                self.ack_ev.set()
                printerr ("Received ACK")
            case 0x83:
                self.rx_sem.release()
                printerr ("Msgs are waiting")
            case 0x84:
                printerr ("Received raw data")
                res = {}
                res["SNR"] = data[1] / 4
                res["RSSI"] = data[2]
                res["payload"] = data[4:].hex()
                print(res)
            case 0x85:
                self.login_resp.set_result(True)

                printerr ("Login success")
            case 0x86:
                self.login_resp.set_result(False)
                printerr ("Login failed")
            case 0x87:
                res = {}
                res["pubkey_pre"] = data[2:8].hex()
                res["bat"] = int.from_bytes(data[8:10], byteorder='little')
                res["tx_queue_len"] = int.from_bytes(data[10:12], byteorder='little')
                res["free_queue_len"] = int.from_bytes(data[12:14], byteorder='little')
                res["last_rssi"] = int.from_bytes(data[14:16], byteorder='little', signed=True)
                res["nb_recv"] = int.from_bytes(data[16:20], byteorder='little', signed=False)
                res["nb_sent"] = int.from_bytes(data[20:24], byteorder='little', signed=False)
                res["airtime"] = int.from_bytes(data[24:28], byteorder='little')
                res["uptime"] = int.from_bytes(data[28:32], byteorder='little')
                res["sent_flood"] = int.from_bytes(data[32:36], byteorder='little')
                res["sent_direct"] = int.from_bytes(data[36:40], byteorder='little')
                res["recv_flood"] = int.from_bytes(data[40:44], byteorder='little')
                res["recv_direct"] = int.from_bytes(data[44:48], byteorder='little')
                res["full_evts"] = int.from_bytes(data[48:50], byteorder='little')
                res["last_snr"] = int.from_bytes(data[50:52], byteorder='little', signed=True) / 4
                res["direct_dups"] = int.from_bytes(data[52:54], byteorder='little')
                res["flood_dups"] = int.from_bytes(data[54:56], byteorder='little')
                self.status_resp.set_result(res)
                data_hex = data[8:].hex()
                printerr (f"Status response: {data_hex}")
                #printerr(res)
            case 0x88:
                printerr ("Received log data")
            # unhandled
            case _:
                printerr (f"Unhandled data received {data}")

    async def send(self, data, timeout = 5):
        """ Helper function to synchronously send (and receive) data to the node """
        self.result = asyncio.Future()
        try:
            await self.cx.send(data)
            res = await asyncio.wait_for(self.result, timeout)
            return res
        except TimeoutError :
            printerr ("Timeout while sending message ...")
            return False

    async def send_only(self, data): # don't wait reply
        await self.cx.send(data)

    async def send_appstart(self):
        """ Send APPSTART to the node """
        b1 = bytearray(b'\x01\x03      mccli')
        return await self.send(b1)

    async def send_advert(self):
        """ Make the node send an advertisement """
        return await self.send(b"\x07")

    async def set_name(self, name):
        """ Changes the name of the node """
        return await self.send(b'\x08' + name.encode("ascii"))

    async def reboot(self):
        await self.send_only(b'\x13reboot')
        return True

    async def get_bat(self):
        return await self.send(b'\x14')

    async def get_time(self):
        """ Get the time (epoch) of the node """
        self.time = await self.send(b"\x05")
        return self.time

    async def set_time(self, val):
        """ Sets a new epoch """
        return await self.send(b"\x06" + int(val).to_bytes(4, 'little'))

    async def set_tx_power(self, val):
        """ Sets tx power """
        return await self.send(b"\x0c" + int(val).to_bytes(4, 'little'))

    async def set_radio (self, freq, bw, sf, cr):
        """ Sets radio params """
        return await self.send(b"\x0b" \
                + int(freq).to_bytes(4, 'little')\
                + int(bw).to_bytes(4, 'little')\
                + int(sf).to_bytes(1, 'little')\
                + int(cr).to_bytes(1, 'little'))

    async def set_tuning (self, rx_dly, af):
        """ Sets radio params """
        return await self.send(b"\x15" \
                + int(rx_dly).to_bytes(4, 'little')\
                + int(af).to_bytes(4, 'little')\
                + int(0).to_bytes(1, 'little')\
                + int(0).to_bytes(1, 'little'))

    async def get_contacts(self):
        """ Starts retreiving contacts """
        return await self.send(b"\x04")

    async def ensure_contacts(self):
        if len(self.contacts) == 0 :
            await self.get_contacts()

    async def reset_path(self, key):
        data = b"\x0D" + key
        return await self.send(data)

    async def share_contact(self, key):
        data = b"\x10" + key
        return await self.send(data)

    async def export_contact(self, key=b""):
        data = b"\x11" + key
        return await self.send(data)

    async def remove_contact(self, key):
        data = b"\x0f" + key
        return await self.send(data)

    async def set_out_path(self, contact, path):
        contact["out_path"] = path
        contact["out_path_len"] = -1
        contact["out_path_len"] = int(len(path) / 2)

    async def update_contact(self, contact):
        out_path_hex = contact["out_path"]
        out_path_hex = out_path_hex + (128-len(out_path_hex)) * "0" 
        adv_name_hex = contact["adv_name"].encode().hex()
        adv_name_hex = adv_name_hex + (64-len(adv_name_hex)) * "0"
        data = b"\x09" \
            + bytes.fromhex(contact["public_key"])\
            + contact["type"].to_bytes(1)\
            + contact["flags"].to_bytes(1)\
            + contact["out_path_len"].to_bytes(1, 'little', signed=True)\
            + bytes.fromhex(out_path_hex)\
            + bytes.fromhex(adv_name_hex)\
            + contact["last_advert"].to_bytes(4, 'little')\
            + int(contact["adv_lat"]*1e6).to_bytes(4, 'little', signed=True)\
            + int(contact["adv_lon"]*1e6).to_bytes(4, 'little', signed=True)
        return await self.send(data)

    async def send_login(self, dst, pwd):
        self.login_resp = asyncio.Future()
        data = b"\x1a" + dst + pwd.encode("ascii")
        return await self.send(data)

    async def wait_login(self, timeout = 5):
        try :
            return await asyncio.wait_for(self.login_resp, timeout)
        except TimeoutError :
            printerr ("Timeout ...")
            return False

    async def send_statusreq(self, dst):
        self.status_resp = asyncio.Future()
        data = b"\x1b" + dst
        return await self.send(data)

    async def wait_status(self, timeout = 5):
        try :
            return await asyncio.wait_for(self.status_resp, timeout)
        except TimeoutError :
            printerr ("Timeout...")
            return False

    async def send_cmd(self, dst, cmd):
        """ Send a cmd to a node """
        timestamp = (await self.get_time()).to_bytes(4, 'little')
        data = b"\x02\x01\x00" + timestamp + dst + cmd.encode("ascii")
        #self.ack_ev.clear() # no ack ?
        return await self.send(data)

    async def send_msg(self, dst, msg):
        """ Send a message to a node """
        timestamp = (await self.get_time()).to_bytes(4, 'little')
        data = b"\x02\x00\x00" + timestamp + dst + msg.encode("ascii")
        self.ack_ev.clear()
        return await self.send(data)

    async def send_chan_msg(self, chan, msg):
        """ Send a message to a public channel """
        timestamp = (await self.get_time()).to_bytes(4, 'little')
        data = b"\x03\x00" + chan.to_bytes(1, 'little') + timestamp + msg.encode("ascii")
        return await self.send(data)

    async def get_msg(self):
        """ Get message from the node (stored in queue) """
        res = await self.send(b"\x0A", 1)
        if res is False :
            self.rx_sem=asyncio.Semaphore(0) # reset semaphore as there are no msgs in queue
        return res

    async def wait_msg(self, timeout=-1):
        """ Wait for a message """
        if timeout == -1 :
            await self.rx_sem.acquire()
            return True

        try:
            await asyncio.wait_for(self.rx_sem.acquire(), timeout)
            return True
        except TimeoutError :
            printerr("Timeout waiting msg")
            return False

    async def wait_ack(self, timeout=6):
        """ Wait ack """
        try:
            await asyncio.wait_for(self.ack_ev.wait(), timeout)
            return True
        except TimeoutError :
            printerr("Timeout waiting ack")
            return False

async def next_cmd(mc, cmds):
    """ process next command """
    argnum = 0
    match cmds[0] :
        case "get_time" :
            timestamp = await mc.get_time()
            print('Current time :'
              f' {datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")}'
              f' ({timestamp})')
        case "sync_time" :
            print(await mc.set_time(int(time.time())))
        case "set_time" :
            argnum = 1
            print(await mc.set_time(cmds[1]))
        case "set_txpower"|"txp" :
            argnum = 1
            print(await mc.set_tx_power(cmds[1]))
        case "set_radio"|"rad" :
            argnum = 4
            print(await mc.set_radio(cmds[1], cmds[2], cmds[3], cmds[4]))
        case "set_tuning"|"tun" :
            argnum = 2
            print(await mc.set_tuning(cmds[1], cmds[2]))
        case "get_bat" | "b":
            print(await mc.get_bat())
        case "reboot" :
            print(await mc.reboot())
        case "send" :
            argnum = 2
            print(await mc.send_msg(bytes.fromhex(cmds[1]), cmds[2]))
        case "msg" | "sendto" | "m" | "{" : # sends to a contact from name
            argnum = 2
            await mc.ensure_contacts()
            print(await mc.send_msg(bytes.fromhex(mc.contacts[cmds[1]]["public_key"])[0:6],
                                    cmds[2]))
        case "chan_msg"|"ch" :
            argnum = 2
            print(await mc.send_chan_msg(cmds[1], cmds[2]))
        case "def_chan_msg"|"def_chan"|"dch" : # default chan
            argnum = 1
            print(await mc.send_chan_msg(0, cmds[1]))
        case "cmd" | "c" | "[" :
            argnum = 2
            await mc.ensure_contacts()
            print(await mc.send_cmd(bytes.fromhex(mc.contacts[cmds[1]]["public_key"])[0:6],
                                    cmds[2]))
        case "login" | "l" | "[[" :
            argnum = 2
            await mc.ensure_contacts()
            print(await mc.send_login(bytes.fromhex(mc.contacts[cmds[1]]["public_key"]),
                                    cmds[2]))
        case "wait_login" | "wl" | "]]":
            print(await mc.wait_login())
        case "req_status" | "rs" :
            argnum = 1
            await mc.ensure_contacts()
            print(await mc.send_statusreq(bytes.fromhex(mc.contacts[cmds[1]]["public_key"])))
        case "wait_status" | "ws" :
            print(await mc.wait_status())
        case "contacts" | "lc":
            print(json.dumps(await mc.get_contacts(),indent=4))
        case "change_path" | "cp":
            argnum = 2 
            await mc.ensure_contacts()
            await mc.set_out_path(mc.contacts[cmds[1]], cmds[2])
            print(await mc.update_contact(mc.contacts[cmds[1]]))
        case "reset_path" | "rp" :
            argnum = 1
            await mc.ensure_contacts()
            print(await mc.reset_path(bytes.fromhex(mc.contacts[cmds[1]]["public_key"])))
            await mc.get_contacts()
        case "share_contact" | "sc":
            argnum = 1
            await mc.ensure_contacts()
            print(await mc.share_contact(bytes.fromhex(mc.contacts[cmds[1]]["public_key"])))
        case "export_contact"|"ec":
            argnum = 1
            await mc.ensure_contacts()
            print(await mc.export_contact(bytes.fromhex(mc.contacts[cmds[1]]["public_key"])))
        case "export_myself"|"e":
            print(await mc.export_contact())
        case "remove_contact" :
            argnum = 1
            await mc.ensure_contacts()
            print(await mc.remove_contact(bytes.fromhex(mc.contacts[cmds[1]]["public_key"])))
        case "recv" | "r" :
            print(await mc.get_msg())
        case "sync_msgs" | "sm":
            res=True
            while res:
                res = await mc.get_msg()
                print (res)
        case "wait_msg" | "wm" :
            await mc.wait_msg()
            res = await mc.get_msg()
            print (res)
        case "trywait_msg" | "wmt" :
            argnum = 1
            if await mc.wait_msg(timeout=int(cmds[1])) :
                print (await mc.get_msg())
        case "wmt8"|"]":
            if await mc.wait_msg(timeout=8) :
               print (await mc.get_msg()) 
        case "wait_ack" | "wa" | "}":
            await mc.wait_ack()
        case "infos" | "i" :
            print(json.dumps(mc.self_info,indent=4))
        case "advert" | "a":
            print(await mc.send_advert())
        case "set_name" :
            argnum = 1
            print(await mc.set_name(cmds[1]))
        case "sleep" | "s" :
            argnum = 1
            await asyncio.sleep(int(cmds[1]))

    printerr (f"cmd {cmds[0:argnum+1]} processed ...")
    return cmds[argnum+1:]

def usage () :
    """ Prints some help """
    print("""mccli.py : CLI interface to MeschCore BLE companion app

   Usage : mccli.py <args> <commands>

 Arguments :
    -h : prints this help
    -a <address>    : specifies device address (can be a name)
    -d <name>       : filter meshcore devices with name or address
    -t <hostname>   : connects via tcp/ip
    -p <port>       : specifies tcp port (default 5000)
    -s <port>       : use serial port <port>
    -b <baudrate>   : specify baudrate

 Available Commands and shorcuts (can be chained) :
    infos                  : print informations about the node      i 
    reboot                 : reboots node                             
    send <key> <msg>       : sends msg to node using pubkey[0:6]
    sendto <name> <msg>    : sends msg to node with given name        
    msg <name> <msg>       : same as sendto                         m 
    wait_ack               : wait an ack for last sent msg          wa
    recv                   : reads next msg                         r 
    sync_msgs              : gets all unread msgs from the node     sm
    wait_msg               : wait for a message and read it         wm
    advert                 : sends advert                           a 
    contacts               : gets contact list                      lc
    share_contact <ct>     : share a contact with others            sc
    remove_contact <ct>    : removes a contact from this node         
    reset_path <ct>        : resets path to a contact to flood      rp
    change_path <ct> <path>: change the path to a contact           cp
    get_time               : gets current time                        
    set_time <epoch>       : sets time to given epoch                 
    sync_time              : sync time with system                    
    set_name <name>        : sets node name                           
    get_bat                : gets battery level                     b 
    login <name> <pwd>     : log into a node (rep) with given pwd   l 
    wait_login             : wait for login (timeouts after 5sec)   wl
    cmd <name> <cmd>       : sends a command to a repeater (no ack) c 
    req_status <name>      : requests status from a node            rs
    wait_status            : wait and print reply                   ws
    sleep <secs>           : sleeps for a given amount of secs      s""") 
                        
async def main(argv):   
    """ Do the job """  
    address = ADDRESS
    port = 5000
    hostname = None
    serial_port = None
    baudrate = 115200
    # If there is an address in config file, use it by default
    # unless an arg is explicitely given
    if os.path.exists(MCCLI_ADDRESS) :
        with open(MCCLI_ADDRESS, encoding="utf-8") as f :
            address = f.readline().strip()

    opts, args = getopt.getopt(argv, "a:d:s:ht:p:b:")
    for opt, arg in opts :
        match opt:
            case "-d" : # name specified on cmdline
                address = arg
            case "-a" : # address specified on cmdline
                address = arg
            case "-s" : # serial port
                serial_port = arg
            case "-b" :
                baudrate = int(arg)
            case "-t" : 
                hostname = arg
            case "-p" :
                port = int(arg)

    if len(args) == 0 : # no args, no action
        usage()
        return

    con = None
    if not hostname is None : # connect via tcp
        con = TCPConnection(hostname, port)
        await con.connect() 
    elif not serial_port is None : # connect via serial port
        con = SerialConnection(serial_port, baudrate)
        await con.connect()
        await asyncio.sleep(0.1)
    else : #connect via ble
        con = BLEConnection(address)
        address = await con.connect()
        if address is None or address == "" : # no device, no action
            printerr ("No device found, exiting ...")
            return

        # Store device address in configuration
        if os.path.isdir(MCCLI_CONFIG_DIR) :
            with open(MCCLI_ADDRESS, "w", encoding="utf-8") as f :
                f.write(address)

    mc = MeshCore(con)
    await mc.connect()

    cmds = args
    while len(cmds) > 0 :
        cmds = await next_cmd(mc, cmds)

asyncio.run(main(sys.argv[1:]))
