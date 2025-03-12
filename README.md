# Switch---Python-Implementation
## Overview

This switch emulates the behavior of a network switch using Python. It supports VLAN tagging, BPDU processing for Spanning Tree Protocol (STP), and manages both trunk and access port states.

### Main While Loop Functions

In the `main()` function, the code enters a `while True` loop where it continuously listens for data frames on each interface, processes them, and makes forwarding decisions. Here are some of the functions within the loop and their roles:

1. **`is_broadcast(dest_mac)` and `is_unicast(dest_mac)`**:  
   These helper functions determine whether the frame is a broadcast or unicast message, so it knows whether to forward the frame to all interfaces or only the target one.

2. **`create_bpdu(interface)`**:  
   To support Spanning Tree Protocol (STP), this function creates a BPDU packet that contains bridge ID, root bridge ID, root path cost, and other STP-specific fields:
   - **Destination MAC**: Set to `01:80:c2:00:00:00`, the reserved MAC address for STP.
   - **Source MAC**: Obtained from the switch.
   - **LLC and BPDU Headers**: Include identifiers and flags to define the packet as a BPDU.
   - **Root and Bridge IDs**: Unique identifiers for the root bridge and the sending bridge.
   - **Path Cost**: The cost to reach the root bridge.
 This packet is then sent out by `send_bdpu_every_sec()` and processed in `process_bpdu()` when received by other switches.

3. **`process_bpdu(data, interface)`**:  
   If the destination MAC matches the BPDU multicast address (`01:80:c2:00:00:00`), this function handles Spanning Tree Protocol (STP) by processing BPDUs as the presented pseudocode explained it:
   - Updates the root bridge ID if a lower priority bridge is detected.
   - Adjusts `root_path_cost` and sets the root port accordingly.
   - Updates trunk port states to `BLOCKING` or `LISTENING` based on the new topology.


## Implementation

The main loop continuously listens and processes incoming frames, updating port as needed. This implementation uses BPDU to ensure loop-free paths, unicast and broadcast forwarding rules to efficiently manage frame delivery, and VLAN tagging to handle network segmentation. The VLAN configuration is read from a config file, `using the get_vlan_interfaces()` function 

#### **`MAC Table`**: 
For the switch to "learn" the location of each device in the topology, it records the source MAC address and associates it with one of its interfaces *whenever it receives a packet*. Later, when it receives a packet destined for a previously learned MAC address, it will forward it directly through that specific interface.

#### **`VLAN`**:
For implementing VLAN functionality, I considered two options:

1.When a packet is received on a regular access interface, if it needs to be sent through a trunk port, I will add the VLAN tag corresponding to the VLAN of the access interface that received the packet. If it’s being forwarded to another access interface, I’ll simply send it directly to that interface.

2.If a packet is received on a trunk interface, I’ll send it out as it is if it’s going through another trunk, without making any changes. However, if it’s sent through an access interface, I will remove the VLAN tag added by the switch that sent it through the trunk interface.

#### **`The Spanning Tree Protocol`**:
To implement the STP protocol, I made the `create_bpdu()` function, which generates a packet specific to this protocol. Then, in the main() function, whenever such a packet is received, it is processed using the `process_bpdu()` function, which follows the pseudocode provided in the assignment.