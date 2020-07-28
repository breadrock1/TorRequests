import os
import sys
import socket
import logging
import requests
import argparse
from threading import Event
from selectors import EVENT_READ

from torpy import TorClient
from torpy.stream import TorStream
from torpy.http.adapter import TorHttpAdapter

__prog__ = os.path.basename(sys.argv[0])


class TorConnection:
    def __init__(self, host, port, hops, type, data, agent=None):
        self.host = host
        self.port = port
        self.hops = hops
        self.type = type
        self.data = data
        self.agent = agent
        self.tor = TorClient()

        logging.getLogger('requests').setLevel(logging.CRITICAL)
        logging.basicConfig(format='[%(asctime)s] [%(threadName)-16s] %(message)s', level=logging.DEBUG)
        self.logger = logging.getLogger(__name__)

    def test_request(self):
        if type is "GET":
            request_data = b'GET / HTTP/1.0\r\nHost: %s\r\n\r\n' % self.host.encode()
        else:
            request_data = b'POST / HTTP/1.0\r\nHost: %s\r\n\r\n%s\r\n' % (self.host.encode(), self.data.encode())

        with self.tor.create_circuit(self.hops) as circuit:
            with circuit.create_stream((self.host, self.port)) as stream:
                stream.send(request_data)
                recv = stream.recv(1024)
                print(recv)

    def test_session(self):
        with self.tor.get_guard() as guard:
            adapter = TorHttpAdapter(guard, 3)

            with requests.Session() as s:
                s.headers.update({'User-Agent': self.agent})
                s.mount('http://', adapter)
                s.mount('https://', adapter)

                r = s.get(self.host, timeout=30)
                self.logger.warning(r)
                self.logger.warning(r.text)
                assert r.text.rstrip().endswith('</html>')

                r = s.get(self.host)
                assert r.text.rstrip().endswith('</html>')
                self.logger.warning(r)
                self.logger.warning(r.text)

    def test_select(self):
        sock_r, sock_w = socket.socketpair()

        events = {TorStream: {'data': Event(), 'close': Event()},
                  socket.socket: {'data': Event(), 'close': Event()}}

        with self.tor.get_guard() as guard:

            def recv_callback(sock_or_stream, mask):
                kind = type(sock_or_stream)
                data = sock_or_stream.recv(1024)
                self.logger.info('%s: %r', kind.__name__, data.decode())
                if data:
                    events[kind]['data'].set()
                else:
                    self.logger.debug('closing')
                    guard.unregister(sock_or_stream)
                    events[kind]['close'].set()

            with guard.create_circuit(3) as circuit:
                with circuit.create_stream((self.host, self.port)) as stream:
                    guard.register(sock_r, EVENT_READ, recv_callback)
                    guard.register(stream, EVENT_READ, recv_callback)

                    stream.send(b'GET / HTTP/1.0\r\nHost: %s\r\n\r\n' % self.host.encode())
                    sock_w.send(b'some data')

                    assert events[socket.socket]['data'].wait(10), 'no sock data received'
                    assert events[TorStream]['data'].wait(30), 'no stream data received'

                    sock_w.close()
                    assert events[socket.socket]['close'].wait(10), 'no sock close received'
                    assert events[TorStream]['close'].wait(10), 'no stream close received'


if __name__ == '__main__':
    def buildSession(args):
        torConnection = TorConnection(args.u, args.p, args.c, args.x, args.d, args.a)
        torConnection.test_session()

    def sendRequest(args):
        torConnection = TorConnection(args.u, args.p, args.c, args.x, args.d)
        torConnection.test_request()
        torConnection.test_select()

    argumentParser = argparse.ArgumentParser(
        prog=__prog__,
        description="This instrument is simple example of Tor connection implementation by torpy library Python3."
    )

    argumentSubParser = argumentParser.add_subparsers(title="Subcommands", description="Choose mode")

    request = argumentSubParser.add_parser("request", help="This command send request")
    request.add_argument('-x', choices=["GET", "POST"], default="GET", type=str, help="Type request")
    request.add_argument('-d', type=str, help="Data to send")
    request.set_defaults(func=sendRequest)

    session = argumentSubParser.add_parser("session", help="This command build session")
    session.add_argument('-a', type=str, default="Mozilla/5.0", help="Specify User-Agent")
    session.set_defaults(func=buildSession)

    argumentParser.add_argument('u', metavar='URL', type=str, help="Specify URL address of onion site")
    argumentParser.add_argument('-p', metavar='Port', default=80, type=int, help="Specify port to connect")
    argumentParser.add_argument('-c', metavar='Circuits', default=3, type=int, help="Specify num of circuits/hops")

    arguments = argumentParser.parse_args()
    arguments.func(arguments)
