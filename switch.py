#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

own_bridge_ID = 0
root_bridge_ID = 0
root_path_cost = 0
root_port = -1
TRUNK_STATES = {}

VLAN_Table = {}
interfaces = range(0, 1)

def get_vlan_interfaces(switch_id,vlan_table):
    config_file = f"./configs/switch{switch_id}.cfg"
    FILE = open(config_file, "r")
    lines = FILE.readlines()
    FILE.close()
    counter = 0
    for line in lines:
        if line[0] >= '0' and line[0] <= '9':
            priority = (int)(line.split("\n")[0])
        else:
            split = line.split(" ")
            vlan_table[counter] = split[1].split("\n")[0]
            counter += 1

def get_priority(switch_id):
    config_file = f"./configs/switch{switch_id}.cfg"
    FILE = open(config_file, "r")
    lines = FILE.readlines()
    FILE.close()
    priority = int(lines[0].split("\n")[0])
    return priority

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def create_bpdu(interface):
    global root_bridge_ID
    global root_path_cost
    global own_bridge_ID

    dest_mac = b'\x01\x80\xC2\x00\x00\x00'
    src_mac = get_switch_mac()
    llc_length = int(38).to_bytes(2, byteorder='big')
    llc_header = b'\x42\x42\x03'
    bpdu_header = b'\x00\x00\x00\x00'
    bpdu_flags = b'\x00'
    bpdu_root_bridge_id = int(own_bridge_ID).to_bytes(8, byteorder='big')
    bpdu_root_path_cost = struct.pack('!I', int(root_path_cost))
    bpdu_bridge_id = int(own_bridge_ID).to_bytes(8, byteorder='big')
    bpdu_port_id = struct.pack('!H', interface)
    bpdu_message_age = struct.pack('!H', 0x00)
    bpdu_max_age = struct.pack('!H', 0x0F)
    bpdu_hello_time = struct.pack('!H', 0x02)
    bpdu_forward_delay = struct.pack('!H', 0x0F)
    
    frame = dest_mac + src_mac + llc_length + llc_header + bpdu_header +\
        bpdu_flags + bpdu_root_bridge_id + bpdu_root_path_cost +\
        bpdu_bridge_id + bpdu_port_id + bpdu_message_age + bpdu_max_age +\
        bpdu_hello_time + bpdu_forward_delay

    return frame

def send_bdpu_every_sec():
    global interfaces, VLAN_Table
    while True:
        if root_bridge_ID == own_bridge_ID:
            for i in interfaces:
                if VLAN_Table[i] == "T":
                    frame = create_bpdu(i)
                    send_to_link(i, 32, frame)
        time.sleep(1)

def is_broadcast(dest):
    return dest == b'\xFF\xFF\xFF\xFF\xFF\xFF'

def is_unicast(dest):
    return not is_broadcast(dest)

def process_bpdu(frame, interface):
    global root_bridge_ID
    global root_path_cost
    global own_bridge_ID
    global TRUNK_STATES, VLAN_Table, interfaces, root_port

    was_bridge = False
    if root_bridge_ID == own_bridge_ID:
        was_bridge = True
    
    frame_root_bridge_id = frame[22:30]
    frame_root_bridge_id = int.from_bytes(frame_root_bridge_id, byteorder='big')
    frame_root_path_cost = frame[30:34]
    frame_root_path_cost = int.from_bytes(frame_root_path_cost, byteorder='big')
    frame_bridge_id = frame[34:42]
    frame_bridge_id = int.from_bytes(frame_bridge_id, byteorder='big')

    if frame_root_bridge_id < root_bridge_ID:
        root_bridge_ID = frame_root_bridge_id
        root_path_cost = frame_root_path_cost + 10
        root_port = interface

        if was_bridge:
            for i in interfaces:
                if VLAN_Table[i] == "T" and i != root_port:
                    TRUNK_STATES[i] = "BLOCKING"

            if TRUNK_STATES[root_port] == "BLOCKING":
                TRUNK_STATES[root_port] = "LISTENING"

            UPDATED_FRAME = frame[0:30] + root_path_cost.to_bytes(4, byteorder='big') +\
                own_bridge_ID.to_bytes(8, byteorder='big') + frame[42:]

            for i in interfaces:
                if VLAN_Table[i] == "T" and i != root_port:
                    send_to_link(i, 32, create_bpdu(i))
    elif frame_root_bridge_id == root_bridge_ID:
        if interface == root_port and frame_root_path_cost + 10 < root_path_cost:
            root_path_cost = frame_root_path_cost + 10
        elif interface != root_port:
            if frame_root_path_cost > root_path_cost:
                if TRUNK_STATES[interface] == "BLOCKING":
                    TRUNK_STATES[interface] = "LISTENING"
    elif frame_root_bridge_id == own_bridge_ID:
            TRUNK_STATES[interface] = "BLOCKING"
    
    if root_bridge_ID == own_bridge_ID:
        for i in interfaces:
            if VLAN_Table[i] == "T":
                TRUNK_STATES[i] = "LISTENING"

def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]
    global interfaces, VLAN_Table, TRUNK_STATES
    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)
    MAC_Table = {}
    VLAN_Table = {}
    TRUNK_STATES = {}

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    get_vlan_interfaces(switch_id,VLAN_Table)
    switch_root_brigde_priority = get_priority(switch_id)

    global root_bridge_ID
    global root_path_cost
    global own_bridge_ID

    own_bridge_ID =  switch_root_brigde_priority
    root_bridge_ID = own_bridge_ID
    root_path_cost = 0

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec)
    t.start()

    for i in interfaces:
        print(get_interface_name(i))
        if VLAN_Table[i] == "T":
            TRUNK_STATES[i] = "BLOCKING"

    print(f"Switch prio : {switch_root_brigde_priority}")

    while True:
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(10) + data[12:]

        # print(f'Destination MAC: {dest_mac}')
        # print(f'Source MAC: {src_mac}')
        # print(f'EtherType: {ethertype}')

        print("Received frame of size {} on interface {} , {}".format(length, interface, VLAN_Table[interface]), flush=True)

        if not src_mac in MAC_Table:
            print("Updated MAC Table")
            MAC_Table[src_mac] = interface

        if dest_mac == "01:80:c2:00:00:00":
            process_bpdu(data, interface)
            continue

        if is_unicast(dest_mac):
                if dest_mac in MAC_Table:
                    # (CASE 1) I i got the message from a Trunk interface i forward it as the same if i sent to a trunk too, 
                    # else i send it without the tag
                    if VLAN_Table[interface] == "T":
                        if VLAN_Table[MAC_Table[dest_mac]] == "T":
                            send_to_link(MAC_Table[dest_mac], length, data)
                        elif int(VLAN_Table[MAC_Table[dest_mac]]) == vlan_id:
                            send_to_link(MAC_Table[dest_mac], length - 4, data[0:12] + data[16:])
                        continue
                    # (CASE 2) Got it from acces interface i send it with the tag for trunk interface, simple for acces ports
                    else:
                        if VLAN_Table[MAC_Table[dest_mac]] == "T":
                            tagged_frame = data[0:12] + create_vlan_tag(int(VLAN_Table[interface])) + data[12:]
                            send_to_link(MAC_Table[dest_mac], length+4, tagged_frame)
                        else:
                            send_to_link(MAC_Table[dest_mac], length, data)
                        continue
                else:
                    for i in interfaces:
                        if i != interface:
                            if VLAN_Table[interface] == "T":
                                if VLAN_Table[i] == "T":
                                    if TRUNK_STATES[i] == "BLOCKING":
                                        continue
                                    send_to_link(i, length, data)
                                elif int(VLAN_Table[i]) == vlan_id:
                                    send_to_link(i, length-4, data[0:12] + data[16:])
                                continue
                            else:
                                if VLAN_Table[i] == "T":
                                    if TRUNK_STATES[i] == "BLOCKING":
                                        continue
                                    tagged_frame = data[0:12] + create_vlan_tag(int(VLAN_Table[interface])) + data[12:]
                                    send_to_link(i, length+4, tagged_frame)
                                elif int(VLAN_Table[i]) == vlan_id:
                                    send_to_link(i, length, data)
                                continue
        else:
            for i in interfaces:
                if i != interface:
                    if VLAN_Table[interface] == "T":
                        if VLAN_Table[i] == "T":
                            if TRUNK_STATES[i] == "BLOCKING":
                                continue
                            send_to_link(i, length, data)
                        elif int(VLAN_Table[i]) == vlan_id:
                            send_to_link(i, length - 4, data[0:12] + data[16:])
                        continue
                    else:
                        if VLAN_Table[i] == "T":
                            if TRUNK_STATES[i] == "BLOCKING":
                                continue
                            tagged_frame = data[0:12] + create_vlan_tag(int(VLAN_Table[interface])) + data[12:]
                            send_to_link(i, length+4, tagged_frame)
                        else:
                            send_to_link(i, length, data)
                

if __name__ == "__main__":
    main()
