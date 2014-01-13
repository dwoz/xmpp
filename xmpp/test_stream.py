from agent.xmpp.stream import *
import unittest
from mock import Mock

import agent.logger
agent.logger.logger_agent.setLevel(agent.logger.CRITICAL)

class TestStream(unittest.TestCase):

    HEADER_OUT = (
        "<?xml version='1.0'?><stream:stream xmlns=\"jabber:client\" "
        "xmlns:stream=\"http://etherx.jabber.org/streams\" to=\"orvant.com\" "
        "from=\"agent@orvant.com\" version=\"1.0\" xml:lang=\"en\">"
        )
    HEADER_IN = (
        "<?xml version='1.0'?><stream:stream xmlns=\"jabber:client\" "
        "xmlns:stream=\"http://etherx.jabber.org/streams\" to=\"agent@orvant.com\" "
        "from=\"orvant.com\" version=\"1.0\" xml:lang=\"en\">"
        "<stream:features><starttls xmlns='urn:ietf:params:xml:ns:xmpp-tls' />"
        "</stream:features>"
        )

    def test_stream_start(self):
        "Stream start sends correct header"
        stream = Stream(
            to='orvant.com', frm='agent@orvant.com'
        )
        stream.start()
        assert stream.output_buffer == [self.HEADER_OUT]

    def test_stream_start_response(self):
        "Stream receives start response"
        transport = Mock()
        stream = Stream(
            to='orvant.com', frm='agent@orvant.com',
        )
        stream.start()
        stream.output_buffer.pop()

        stream.input_node_start = Mock()
        stream.input_node_end = Mock()
        # Register the mock handle_node start method on a new parser
        stream.configure_new_parsers()

        stream.parse(self.HEADER_IN)
        streamseen = False
        for call in stream.input_node_start.mock_calls:
            n = call[1][2]
            if n.tag == 'stream':
                streamseen = True
                assert n.attrs['from'] == 'orvant.com'
                assert n.attrs['to'] == 'agent@orvant.com'
        assert streamseen
        features_seen = False
        for call in stream.input_node_end.mock_calls:
            n = call[1][2]
            if n.tag == 'features':
                features_seen = True
                assert n.get_tags('starttls')
        assert features_seen

    def test_stream_input_node_start(self):
        "Stream input_node_start method"
        transport = Mock()
        parser = Mock()
        stream = Stream(
            to='orvant.com', frm='agent@orvant.com', parser_cls=parser,
        )
        SESSIONID = 'af2e9d4a'
        node = Node(
            tag='stream:stream',
            attrs={
                'to': 'agent@orvant.com',
                'from': 'orvant.com',
                'xmlns': 'jabber:client',
                'xmlns:stream': 'http://etherx.jabber.org/streams',
                'version' : '1.0',
                'xml:lang': 'en',
                'id': SESSIONID,
            },
        )
        stream.input_node_start('input', 1, node)
        assert stream.session_id == SESSIONID
        node.attrs['version'] = '1.1'
        self.assertRaises(StreamError, stream.input_node_start, 'input', 1, node)
        node = Node('body')
        self.assertRaises(StreamError, stream.input_node_start, 'input', 1, node)

    def test_stream_input_node_end(self):
        "Stream handle_node_end method"
        transport = Mock()
        parser = Mock()
        stream = Stream(
            to='orvant.com', frm='agent@orvant.com', parser_cls=parser,
        )
        stream.input_node_end('test', 1, 'foo')
        stream.input_node_end('test', 2, 'foo')
        assert len(stream.input_buffer) == 1
        assert stream.input_buffer[0] == 'foo'

    def test_stream_restart(self):
        "Stream restart method"
        # Parser will have a new Mock for each call to
        # Stream.configure_new_parser
        stream = Stream(
            to='orvant.com', frm='agent@orvant.com', session_id='sdf',
            parser_cls=Mock,
        )
        to, frm, session_id  = stream.to, stream.frm, stream.session_id 
        inparser = stream.input_parser
        outparser = stream.input_parser
        stream.restart()
        assert inparser != stream.input_parser
        assert outparser != stream.output_parser
        # RFC-6120 States that the session id should not be preserved on
        # restarts. The session_id should be left alone here though as a signal
        # to the transport (Bosh needs this) that the stream is beinge
        # re-started vs a brand new stream. The Stream class will then update
        # the session_id when it receives a response.
        assert (to, frm, session_id, ) == \
            (stream.to, stream.frm, stream.session_id, )

    def test_stream_message_id(self):
        "Steam message_id"
        transport = Mock()
        parser = Mock()
        stream1 = Stream(
            to='orvant.com', frm='agent@orvant.com', parser_cls=parser,
        )
        transport = Mock()
        parser = Mock()
        stream2 = Stream(
            to='orvant.com', frm='agent@orvant.com', parser_cls=parser,
        )
        assert stream1.message_id() == stream2.message_id() -1
