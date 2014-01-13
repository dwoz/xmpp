from agent.xmpp.transport import *
import unittest
from mock import Mock

import agent.logger
agent.logger.logger_agent.setLevel(agent.logger.CRITICAL)

def mock_socket():
    class MockSocket(object):
        connect = Mock()
        close = Mock()
        send = Mock()
        recv = Mock()
    return MockSocket

def mock_getaddrinfo():
    ADDRINFO = [
        (2, 1, 6, '', ('69.160.46.73', 5222)),
        (2, 2, 17, '', ('69.160.46.73', 5222)),
        (2, 3, 0, '', ('69.160.46.73', 5222)),
    ]
    mock_getaddrinfo = Mock()
    mock_getaddrinfo.return_value = ADDRINFO
    return mock_getaddrinfo

mock_resolvehost = Mock()
mock_resolvehost.return_value = '69.160.46.73'
class MockSelect(object):
    def __init__(self, num=1):
        self.num = 1
        self.calls = 0

    def __call__(self, *l, **d):
        if self.calls >= self.num:
            return [], [], []
        self.calls += 1
        return l[0], l[1], l[2]

class TestTcp(unittest.TestCase):

    def test_tcp_init(self):
        t = Tcp('orvant.com')
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        assert t.use_srv == True, t.use_srv
        t = Tcp('www.orvant.com', 5223)
        assert t._server == 'www.orvant.com', t._server
        assert t._port == 5223, t._port
        assert t.use_srv == True, t.use_srv
        t = Tcp('orvant.net', use_srv=False)
        assert t._server == 'orvant.net', t._server
        assert t._port == 5222, t._port
        assert t.use_srv == False, t.use_srv

    def test_tcp_connect(self):
        sock = mock_socket()
        tsocket = Mock()
        tsocket.return_value = sock
        t = Tcp('orvant.com')
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        t.connect(resolvehost=mock_resolvehost, socket_maker=tsocket)
        tsocket.assert_called_with('69.160.46.73', 5222)
        sock.connect.assert_called_with('69.160.46.73', 5222)
        sock.close.assert_not_called()
        assert t._sock == sock

    def test_tcp_connect_errors(self):
        sock = mock_socket()
        sock.connect.side_effect = socket.error
        tsocket = Mock()
        tsocket.return_value = sock
        t = Tcp('orvant.com')
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        try:
            t.connect(resolvehost=mock_resolvehost, socket_maker=tsocket)
        except socket.error:
            pass
        else:
            assert False, "Error not raised as expected"
        tsocket.assert_called_with('69.160.46.73', 5222)
        sock.connect.assert_called_with('69.160.46.73', 5222)
        sock.close.asset_called()

    def test_tcp_receive(self):
        VAL = '<?xml version="1.0"?><stream:stream>'
        getaddrinfo = mock_getaddrinfo()
        sock = mock_socket()
        sock.recv.return_value = VAL
        tsocket = Mock()
        tsocket.return_value = sock
        t = Tcp('orvant.com')
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        t.connect(resolvehost=mock_resolvehost, socket_maker=tsocket)
        for i in t.rawrecv():
            pass
        rcv = t.recv()
        assert VAL == rcv, rcv

    def test_tcp_receive_errors(self):
        VAL = '<?xml version="1.0"?><stream:stream>'
        sock = mock_socket()
        sock.recv.return_value = VAL
        tsocket = Mock()
        tsocket.return_value = sock
        t = Tcp('orvant.com')
        t._select = MockSelect(num=1)
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        t.connect(resolvehost=mock_resolvehost, socket_maker=tsocket)
        sock.recv.side_effect = socket.error
        try:
            for i in t.rawrecv():
                pass
        except socket.error:
            pass
        else:
            assert False, 'Expected socket.error to be raised'

    def test_tcp_send(self):
        VAL = '<?xml version="1.0"?><stream:stream>'
        getaddrinfo = mock_getaddrinfo()
        sock = mock_socket()
        tsocket = Mock()
        tsocket.return_value = sock
        t = Tcp('orvant.com')
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        t.connect(resolvehost=mock_resolvehost, socket_maker=tsocket)
        t.send(VAL)
        sock.send.assert_called_with(VAL)

    def test_tcp_send_error(self):
        VAL = '<?xml version="1.0"?><stream:stream>'
        sock = mock_socket()
        tsocket = Mock()
        tsocket.return_value = sock
        t = Tcp('orvant.com')
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        t.connect(resolvehost=mock_resolvehost, socket_maker=tsocket)
        sock.send.side_effect = socket.error
        try:
            t.send(VAL)
        except socket.error:
            pass
        else:
            assert False, "Expected socket.error to be raised"

    def test_tcp_close(self):
        VAL = '<?xml version="1.0"?><stream:stream>'
        sock = mock_socket()
        tsocket = Mock()
        tsocket.return_value = sock
        t = Tcp('orvant.com')
        assert t._server == 'orvant.com', t._server
        assert t._port == 5222, t._port
        t.connect(resolvehost=mock_resolvehost, socket_maker=tsocket)
        t._sock.close.assert_not_called()
        t.disconnect()
        t._sock.close.assert_called()

class TestBosh(unittest.TestCase):
    https = Mock()
    http = Mock()
    Bosh.connection_cls['http'] = http
    Bosh.connection_cls['https'] = https

    def test_bosh_init(self):
        t = Bosh('http://www.orvant.com/http-bind')
        assert t._http_host == 'www.orvant.com'
        assert t._http_port == 80
        assert t._http_proto == 'http'
        assert t._sid == None
        assert t._rid == 0
        assert t.hold == 4
        assert t.wait == 80
        assert t.requests == 5
        assert t.polling == 10
        assert t.pipeline == False
        assert t.GZIP == True

    def test_bosh_rid(self):
        t = Bosh('http://www.orvant.com/http-bind')
        a = t.rid
        t = Bosh('http://www.orvant.com/http-bind')
        b = t.rid
        assert b != a
        assert int(b) != int(a) + 1
        c = t.rid
        assert int(c) == int(b) + 1
        t.rid = 15
        assert int(t.rid) == 15

    def test_bosh_connect_http(self):
        class http:
            def __init__(self, *args, **opts):
                pass
            connect = Mock()
        Bosh.connection_cls['http'] = http
        t = Bosh('http://www.orvant.com/http-bind')
        t.connect()
        assert isinstance(t._connections[0], http)
        assert t._connections[0].connect.called

    def test_bosh_connect_https(self):
        class https:
            def __init__(self, *args, **opts):
                pass
            connect = Mock()
        Bosh.connection_cls['https'] = https
        t = Bosh('https://www.orvant.com/http-bind')
        t.connect()
        assert isinstance(t._connections[0], https)
        assert t._connections[0].connect.called

    def test_bosh_xmlstream_to_bosh_start(self):
        """
        xmlstream to bosh when sending stream start
        """
        t = Bosh('https://www.orvant.com/http-bind')
        t.connect()
        stream = """<?xml version='1.0'?><stream:stream xmlns="jabber:client"
            from="dev.az.h4.cx"
            version="1.0"
            xmlns:stream="http://etherx.jabber.org/streams">
        """
        bosh = t.xmlstream_to_bosh(stream)
        body = Node.from_string(bosh)
        assert body.tag == 'body'
        assert body.attrs['xmpp:version'] == "1.0"
        assert body.attrs['wait'] == str(t.wait)
        assert body.attrs['hold'] == str(t.hold)
        assert body.attrs['xml:lang'] == t.xml_lang
        assert body.attrs['content'] == "text/xml; charset=utf-8"
        assert 'rid' in body.attrs

    def test_bosh_xmlstream_to_bosh_restart(self):
        """
        xmlstream to bosh when sending stream restart
        """
        t = Bosh('https://www.orvant.com/http-bind')
        t.connect()
        # xmlstream_to_bosh uses the stream id to know its a restart
        stream = """<?xml version='1.0'?><stream:stream xmlns="jabber:client"
            from="dev.az.h4.cx"
            version="1.0"
            xmlns:stream="http://etherx.jabber.org/streams"
            id="sdfij">
        """
        bosh = t.xmlstream_to_bosh(stream)
        body = Node.from_string(bosh)
        assert body.tag == 'body'
        assert body.attrs['xml:lang'] == t.xml_lang
        assert body.attrs['content'] == "text/xml; charset=utf-8"
        assert 'rid' in body.attrs
        assert 'xmpp:restart' in body.attrs and body.attrs['xmpp:restart']

    def test_bosh_bosh_to_xmlstream_start(self):
        t = Bosh('https://www.orvant.com/http-bind')
        t.connect()
        x = """<body xmlns='http://jabber.org/protocol/httpbind'
          sid='0209ce4ea1047184a8d1fe83e000e02d22f3f40c' wait='120' requests='4'
          inactivity='30' maxpause='120' polling='2' ver='1.8' from='dev.az.h4.cx'
          secure='true' authid='1049432245' xmlns:xmpp='urn:xmpp:xbosh' hold="5"
          xmlns:stream='http://etherx.jabber.org/streams'
          xmpp:version='1.0'>
            <stream:features xmlns:stream='http://etherx.jabber.org/streams'>
              <mechanisms xmlns='urn:ietf:params:xml:ns:xmpp-sasl'>
                <mechanism>SCRAM-SHA-1</mechanism><mechanism>DIGEST-MD5</mechanism>
                <mechanism>PLAIN</mechanism>
               </mechanisms>
            </stream:features>
          </body>
        """
        body = Node.from_string(x)
        stream = t.bosh_to_xmlstream(body)
        header = """<?xml version='1.0'?><stream:stream xmlns:stream="jabber:client" """
        assert stream.startswith(header)
        # Wait, Hold, and Requests Get Updated
        assert t.wait == 120
        assert t.requests == 4
        assert t.hold == 5
        assert t._sid == '0209ce4ea1047184a8d1fe83e000e02d22f3f40c'

