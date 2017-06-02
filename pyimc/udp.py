import socket, struct, asyncio
from warnings import warn
import pyimc
from pyimc.common import multicast_ip


class IMCSenderUDP:
    def __init__(self, ip_dst, local_port=None):
        self.dst = ip_dst
        self.local_port = local_port

    def __enter__(self):
        # Set up socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Enable multicast, TTL should be <32 (local network)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 5)
        # Allow reuse of addresses
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if self.local_port:
            # Bind the socket to a local interface
            self.sock.bind(('', self.local_port))

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.sock.close()

    def send(self, message, port):
        if message.__module__ == 'imc':
            b = pyimc.Packet.serialize(message)
            self.sock.sendto(b, (self.dst, port))
        else:
            raise TypeError('Unknown message passed ({})'.format(type(message)))


class IMCProtocolUDP(asyncio.DatagramProtocol):
    def __init__(self, instance):
        self.transport = None
        self.parser = pyimc.Parser()
        self.instance = instance

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.parser.reset()
        p = self.parser.parse(data)
        if pyimc.Message in type(p).__bases__:
            try:
                for fn in self.instance._subs[type(p)]:
                    fn(self.instance, p)
            except KeyError:
                pass
        elif type(p) is pyimc.Message:
            # Subscriptions to pyimc.Message receives all messages
            try:
                for fn in self.instance._subs[pyimc.Message]:
                    fn(self.instance, p)
            except KeyError:
                pass
        else:
            warn('Received IMC message that was not a subclass of Message c')

    def error_received(self, exc):
        print('Error received:', exc)

    def connection_lost(self, exc):
        # TODO: Reestablish connection?
        print("Socket closed")


def get_multicast_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.001)

    # set multicast interface to any local interface
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('0.0.0.0'))

    # Enable multicast, TTL should be <32 (local network)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    # Allow reuse of addresses
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Allow receiving multicast broadcasts (subscribe to multicast group)
    mreq = struct.pack('4sL', socket.inet_aton(multicast_ip), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    # Do not loop back own messages
    sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_LOOP, 0)

    port = None
    for i in range(30100, 30105):
        try:
            # Binding to 0.0.0.0 results in multiple messages if there is multiple interfaces available
            # Kept as-is to avoid losing messages
            sock.bind(('0.0.0.0', i))
            port = i
            break
        except OSError as e:
            # Socket already in use without SO_REUSEADDR enabled
            continue

    if not port:
        raise RuntimeError('No IMC multicast ports free on local interface.')

    return sock


def get_imc_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.001)

    port = None
    for i in range(6000, 6030):
        try:
            sock.bind(('0.0.0.0', i))
            port = i
            break
        except OSError as e:
            # Socket already in use without SO_REUSEADDR enabled
            continue

    if not port:
        raise RuntimeError('No IMC ports free on local interface.')

    return sock