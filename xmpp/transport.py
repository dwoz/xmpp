"""
A transport handles connecting to a remote server and provides the
mechanisms to establish an XML Stream and then send and receive messages
over that stream.
"""
import time
import sys
import httplib
import select
import gzip
import random

# This is only for exceptions
import socket

from urlparse import urlparse

from agent.xmpp.ns import NS_STREAMS, NS_HTTP_BIND
from agent.xmpp.xmlutil import Node
from agent.util import (
    M, tcp_socket, resolve_host, HTTPConnection, HTTPSConnection, StringIO
)

_CS_IDLE = httplib._CS_IDLE
_CS_REQ_SENT = httplib._CS_REQ_SENT
POST='POST'
OK = 200
BAD_REQUEST = 400
FORBIDDEN = 403
NOT_FOUND = 404
BUFLEN = 1024
BadStatusLine = httplib.BadStatusLine

import logging
log = logging.getLogger(__name__)

class TransportError(Exception):
    """
    Raise for errors while transporting xml streams
    """

class Tcp(object):
    """
    TCP connection transport.
    """

    def __init__(self, server=None, port=5222, use_srv=True):
        """
        Cache connection point 'server'. 'server' is the tuple of (host, port)
        absolutely the same as standard tcp socket uses. However library will lookup for
        ('_xmpp-client._tcp.' + host) SRV record in DNS and connect to the found (if it is)
        server instead
        """
        self._server = server
        self._port = port
        self._ip = None
        self.use_srv = use_srv
        self.buffer = ''

    def srv_lookup(self, server):
        """
        SRV resolver. Takes server=(host, port) as argument. Returns new (host, port) pair
        """
        if HAVE_DNSPYTHON or HAVE_PYDNS:
            host, port = server
            possible_queries = ['_xmpp-client._tcp.' + host]

            for query in possible_queries:
                try:
                    if HAVE_DNSPYTHON:
                        answers = [x for x in dns.resolver.query(query, 'SRV')]
                        # Sort by priority, according to RFC 2782.
                        answers.sort(key=lambda a: a.priority)
                        if answers:
                            host = str(answers[0].target)
                            port = int(answers[0].port)
                            break
                    elif HAVE_PYDNS:
                        # ensure we haven't cached an old configuration
                        DNS.DiscoverNameServers()
                        response = DNS.Request().req(query, qtype='SRV')
                        # Sort by priority, according to RFC 2782.
                        answers = sorted(response.answers, key=lambda a: a['data'][0])
                        if len(answers) > 0:
                            # ignore the priority and weight for now
                            _, _, port, host = answers[0]['data']
                            del _
                            port = int(port)
                            break
                except:
                    log.debug(M('An error occurred while looking up {0}', query))
            server = (host, port)
        else:
            log.debug(
                "Could not load one of the supported DNS libraries "
                "(dnspython or pydns). SRV records will not be queried "
                "and you may need to set custom hostname/port for some "
                "servers to be accessible",
            )
        # end of SRV resolver
        return server

    def connect(self, server=None, port=None, resolvehost=resolve_host,
        socket_maker=tcp_socket):
        """
        Try to connect to the given host/port.
        """
        if not server:
            server = self._server
        if not port:
            port = self._port
        if not self._ip:
            self._ip = resolvehost(server)
        self._sock = socket_maker(self._ip, self._port)
        self._sock.connect(self._ip, self._port)
        log.debug(M("Successfully connected to remote host: {0}", self._server))

    def recv(self, size=1024):
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def rawrecv(self, size=1024):
        data = []
        while True:
            a = self._sock.recv(size)
            if a:
                data.append(a)
            if not a or len(a) < size:
                break
            yield
        if not data:
            raise TransportError('dead socket')
        log.debug(M('Adding data to buffer: {}', ''.join(data)))
        self.buffer += ''.join(data)

    def send(self, data):
        return self._sock.send(data)

    def pending_data(self, timeout=0):
        return self._sock.pending_data(timeout=timeout)

    def disconnect(self):
        """ Closes the socket. """
        self._sock.close()

    def starttls(self):
        from agent.util import ssl_wrapper
        self._sock = ssl_wrapper(self._sock)

    def fileno(self):
        return self._sock.fileno()

    @property
    def readywrite(self):
        return self._sock.readywrite

    @property
    def readyread(self):
        return self.buffer != ''

class Bosh(object):
    """
    Bosh connection transport
    """

    connection_cls = {
        'http': HTTPConnection,
        'https': HTTPSConnection,
    }

    default_headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'Connection': 'Keep-Alive',
    }
    xml_lang = 'en'

    @property
    def readyread(self):
        return self.buffer != ''

    @property
    def readywrite(self):
        return self._connection.sock.readywrite

    def __init__(self, endpoint, server=None, port=None, wait=80,
            hold=4, requests=5, polling=10, headers={}, GZIP=True, bound=False,
            pipeline=False):
        url = urlparse(endpoint)
        self._http_host = url.hostname
        self._http_path = url.path
        if url.port:
            self._http_port = url.port
        elif url.scheme == 'https':
            self._http_port = 443
        else:
            self._http_port = 80
        self._http_proto = url.scheme
        self._port = port
        self._sid = None
        self._rid = 0 # Will get set to random number
        self.wait = wait
        self.hold = hold
        self.requests = requests
        self.polling = polling
        self._connections = [] # Will be http or https connection
        self._respobjs = {}
        self.headers = self.default_headers.copy()
        self.headers.update(headers)
        self.GZIP = GZIP
        self._server = None
        self.bound = False
        self.buffer = ''
        self.t = None
        self.pipeline = pipeline

    def connect(self):
        connection = self._connection()
        self._connections.append(connection)

    def connection(self):
        reuse = None
        if self.pipeline and self._connections:
            c = self._connections[0]
            c._HTTPConnection__state = _CS_IDLE
            return c
        for con in self._connections:
            if con._HTTPConnection__state == _CS_IDLE:
                log.debug("REUSING CONNECTION")
                return con
        log.debug("NEW CONNECTION")
        con = self._connection()
        self._connections.append(con)
        return con

    def _connection(self):
        cls = self.connection_cls[self._http_proto]
        log.debug(M("using class {0} for {1}", cls, self._http_proto))
        connection = cls(self._http_host, self._http_port)
        connection.connect()
        return connection

    def reconnect(self, sock):
        for i in list(self._connections):
            if i.sock.fileno() == sock:
                try:
                    i.sock.shutdown(socket.SHUT_RDWR)
                    i.sock.close()
                finally:
                    self._connections.remove(i)

#    def disconnect(self):
#        log.debug("Closing socket")
#        if self._connection and self._connection.sock:
#            self._connection.sock.shutdown()
#            self._connection.close()

    def recv(self, size=1024):
        data = ''
        if self.buffer:
            data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def rawrecv(self, size=1024):
        resp = ''
        sock = self.pending_data(queue=False)[0]
        if not self._respobjs:
            raise TransportError("Disconnected from server", 'error')
        try:
            res, data = self._respobjs[sock].pop(0)
        except IndexError:
            log.debug(M("DEAD CONNECTION"))
            self.reconnect(sock)
            self._respobjs.pop(sock)
            raise StopIteration
        sock = res.socket
        log.debug(M("PROCESSING {} {}", sock.fileno(), self._respobjs))
        try:
            res.begin()
        except BadStatusLine as e:
            resp = sock.recv(size)
            if len(resp) == 0:
                # The TCP Connection has been dropped, Resend the
                # request.
                log.debug('Detected dead http connection reconnecting')
                fno = sock.fileno()
                self.reconnect(fno)
                log.debug(
                    M(
                        "removing response objects for socket {0} {1}",
                        fno,
                        self._respobjs[fno]
                    )
                )
                piped = self._respobjs.pop(fno)
                node = Node.from_string(data)
                self.rid = node.get_attr('rid')
                log.debug(M("resend data: {0}", data))
                self.send(data)
                for resp, data in piped:
                    log.debug(M("resend data: {0}", data))
                    self.send(data)
                raise StopIteration
            else:
                # The server sent some data but it was a legit bad
                # status line.
                reraise(e)
        except Exception as e:
            log.error(M("EXCEPTION READIANG BODY {}", e))
            reraise(e)
        if res.status == OK:
            # Response to valid client request.
            headers = dict(res.getheaders())
            raw_data = []
            # Read the raw data off the line, yielding for each chunk received
            while True:
                a = res.read(size)
                if a:
                    raw_data.append(a)
                if not a or len(a) < size:
                    break
                yield
            if headers.get('content-encoding', None) == 'gzip':
                a = StringIO()
                a.write(''.join(raw_data))
                a.seek(0)
                gz = gzip.GzipFile(fileobj=a)
                data = gz.read()
            else:
                data = ''.join(raw_data)
            log.debug(M('got raw bosh data: {0}', data))
        elif res.status == BAD_REQUEST:
            # Inform client that the format of an HTTP header or binding
            # element is unacceptable.
            log.error("The server did not undertand the request")
            raise TransportError("Disconnected from server", 'error')
        elif res.status == FORBIDDEN:
            # Inform the client that it bas borken the session rules
            # (polling too frequently, requesting too frequently, too
            # many simultanious requests.
            log.error("Forbidden due to policy-violation")
            raise TransportError("Disconnected from server")
        elif res.status == NOT_FOUND:
            # Inform the client that (1) 'sid' is not valid, (2) 'stream' is
            # not valid, (3) 'rid' is larger than the upper limit of the
            # expected window, (4) connection manager is unable to resend
            # respons (5) 'key' sequence if invalid.
            log.error("Invalid/Corrupt Stream")
            raise TransportError("Disconnected from server")
        else:
            log.error(M("Recieved status not defined in XEP-1204: {0}", res.status))
            raise TransportError("Disconnected from server")
        node = Node.from_string(data)
        if node.tag != 'body':
            raise TransportError("Disconnected from server")
        if node.get_attr('type') == 'terminate':
            log.debug(M("Connection manager terminated stream: {0}", node.get_attr('condition')))
            self._owner.connected = ''
            raise TransportError("Disconnected from server")
        resp = self.bosh_to_xmlstream(node)
        res.conn._HTTPConnection__state = _CS_IDLE
        if resp:
            #self._owner.Dispatcher.Event('', DATA_RECEIVED, resp)
            log.debug(M('Add Received Data: {0}', resp))
        else:
            log.debug(M('Resend data: {0}', resp))
            self.send(resp)

        #if self.accepts_more_requests():
        #    log.info(M("SEND EXTRA REQUEST"))
        #    self.send('')
        self.buffer += resp
        raise StopIteration

    def send(self, raw_data, headers={}):
        if type(raw_data) != type('') or type(raw_data) != type(u''):
            raw_data = str(raw_data)
        log.debug(M('send raw data {}', raw_data))
        bosh_data = self.xmlstream_to_bosh(raw_data)
        default = dict(self.headers)
        default['Host'] = self._http_host
        default['Content-Length'] = len(bosh_data)
        if self.GZIP:
            default['Accept-Encoding'] = 'gzip, deflate'
        headers = dict(default, **headers)
        conn = self.connection()
        conn.request(POST, self._http_path, bosh_data, headers)
        self.t = time.time()
        respobj = conn.response_class(
                conn.sock, strict=conn.strict, method=conn._method,
        )
        log.debug(M("CON STATE {}", conn._HTTPConnection__state))
        respobj.socket = conn.sock
        respobj.conn = conn
        log.debug(M('send raw data {0}', bosh_data))
        log.debug(M("SET {} {}", conn.sock.fileno(), respobj))
        self._respobjs.setdefault(conn.sock.fileno(), []).append((respobj, bosh_data))
        return len(raw_data)

    def pending_data(self, timeout=.001, queue=True):
        log.debug('pending data select')
        pending = select.select(self.fileno(), [], [], timeout)[0]
#        if not pending and self.accepts_more_requests():
#            self.send('')
        return pending

    def accepts_more_requests(self):
        if self.t and time.time() - self.t < self.polling:
            return False
        respobjs = []
        for i in self._respobjs:
            respobjs.extend(self._respobjs[i])
        log.debug(M('ACCEPTS {} {} {}', len(respobjs), self.requests, self.hold))
        if not self.bound:
            # XXX This should depend more on the stream being
            # 'negotiated' or not.
            return False
        if not respobjs:
            return True
        return len(respobjs) < self.requests - 1

    @property
    def rid(self):
        """
        An auto incrementing response id.
        """
        if not self._rid:
            self._rid = random.randint(0, 10000000)
        else:
            self._rid += 1
        return str(self._rid)

    @rid.setter
    def rid(self, i):
        """
        Set the rid's next value
        """
        self._rid = int(i) - 1

    def bind(self, rid, sid, hold, wait, requests, polling):
        self._rid = rid
        self._sid = sid
        self.hold = hold
        self.wait = wait
        self.requests = requests
        self.polling = polling
        self.restart = True
        self.bound = True

    def fileno(self):
        log.debug(
            M(
                "The status of the current http requests are {}",
                [i._HTTPConnection__state for i in self._connections],
            )
        )
        log.debug(M("The respobjs object looks like {}",self._respobjs))
        filenos = [i.sock.fileno() for i in self._connections]
        assert filenos
        return filenos

    def bosh_to_xmlstream(self, node):
        if 'sid' in node.attrs:
            self._sid = node.get_attr('sid')
            self.AuthId = node.get_attr('authid')
            self.wait = int(node.get_attr('wait') or self.wait)
            self.hold = int(node.get_attr('hold') or self.hold)
            self.polling = int(node.get_attr('polling') or self.hold)
            self.requests = int(node.get_attr('requests') or self.requests)
            stream=Node('stream:stream', payload=node.payload)
            stream.namespace = 'jabber:client'
            stream.set_attr('version','1.0')
            stream.set_attr('from', 'dev.az.h4.cx')
            stream.set_attr('id', node.get_attr('sid'))
            data = stream.to_string()[:-len('</stream:stream>')]
            resp = "<?xml version='1.0'?>{0}".format(data)
        elif node.get_children():
            resp = ''.join(i.to_string() for i in node.get_children())
        else:
            resp = ''
        return resp

    def xmlstream_to_bosh(self, stream):
        if stream.startswith("<?xml version='1.0'?>"):
            # Sanitize stream tag so that it is suitable for parsing.
            stream = stream.split('>', 1)[1]
            stream = stream.replace('>', '/>')
            stream = Node.from_string(stream)
            if 'id' in stream.attrs:
                # Send restart after authentication.
                body = Node('body')
                body.set_attr('xmpp:restart', 'true')
                body.set_attr('xmlns:xmpp', 'urn:xmpp:xbosh')
            else:
                # Opening a new BOSH session.
                body = Node('body')
                body.namespace = NS_HTTP_BIND
                body.set_attr('hold', self.hold)
                body.set_attr('wait', self.wait)
                body.set_attr('ver', '1.6')
                body.set_attr('xmpp:version', stream.get_attr('version'))
                body.set_attr('to', stream.get_attr('to'))
                body.set_attr('xmlns:xmpp', 'urn:xmpp:xbosh')
                # XXX Ack support for request acknowledgements.
                if self._server and  self._server != self._http_host:
                    if self._port:
                        route = '%s:%s' % self._server, self._port
                    else:
                        route = self._server
                    body.set_attr('route', route)
        else:
            # Mid stream, wrap the xml stanza in a BOSH body wrapper
            if stream:
                if type(stream) == type('') or type(stream) == type(u''):
                    stream = Node.from_string(stream)
                stream = [stream]
            else:
                stream = []
            body = Node('body', payload=stream)
        body.namespace = 'http://jabber.org/protocol/httpbind'
        body.set_attr('content', 'text/xml; charset=utf-8')
        body.set_attr('xml:lang', self.xml_lang)
        body.set_attr('rid', self.rid)
        if self._sid:
            body.set_attr('sid', self._sid)
        return body.to_string()

