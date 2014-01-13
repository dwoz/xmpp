from agent.xmpp.xmlutil import Node, DOCHEAD, XmlParser
from ns import NS_STREAMS, NS_SASL, NS_TLS, NS_BIND, NS_CLIENT
import random
import bisect
import base64
import time
from agent.util import M, routine, IdGen


from Queue import Queue
import logging
log = logging.getLogger(__name__)



class StreamError(Exception): pass


def node_builder(parser, tag, attrs, level):
    return Node(tag, attrs)

message_id = IdGen()


class Stream(object):

    version = '1.0'

    def __init__(
            self, to=None, frm=None, session_id=None, xml_lang='en', attrs={},
            xmlns=NS_CLIENT, parser_cls=XmlParser, started=False):
        self.to = to
        self.frm = frm
        self.session_id = session_id
        self.xml_lang = xml_lang
        self.attrs = attrs or {}

        self.parser_cls = parser_cls
        self.input_buffer = []
        self.output_buffer = []
        self.configure_new_parsers()
        self.started = False # False, to, or frm
        self.xmlns = xmlns

    def configure_new_parsers(self):
        """
        Configure parsers for incoming and outgoing stream documents.
        Register two handlers on each parser.

        """
        self.input_parser = self.parser_cls()
        self.input_parser.register_start_handler(self.input_node_start)
        self.input_parser.register_end_handler(self.input_node_end)
        self.input_parser.set_node_builder(node_builder)

        self.output_parser = self.parser_cls()
        self.output_parser.register_start_handler(self.output_node_start)
        self.output_parser.register_end_handler(self.output_node_end)
        self.output_parser.set_node_builder(node_builder)

    def header(self):
        """
        Generate a string representation of a stream header which
        includes an XML document identifier an opening stream tag.

          <?XML version='1.0'?><stream:stream>

        """
        attrs = self.attrs.copy()
        if self.to:
            attrs['to'] = self.to
        if self.frm:
            attrs['from'] = self.frm
        if self.session_id:
            attrs['id'] = self.session_id
        attrs['xml:lang'] = self.xml_lang
        attrs['xmlns:stream'] = NS_STREAMS
        attrs['xmlns'] = 'jabber:client'
        attrs['version'] = '1.0'
        stream = Node(
            'stream:stream', attrs=attrs,
        )
        return DOCHEAD + stream.to_string().replace('/>', '>')

    # XXX Better name
    def parse(self, s):
        self.input_parser.parse(s)

    def recvnode(self):
        if self.input_buffer:
            data = self.input_buffer.pop(0)
            log.debug(M("Receive Node: {}", data.to_string()))
            return data

    def sendnode(self, node):
        msgid = None
        if node.tag in ('message', 'presence', 'iq',) \
            and 'id' not in node.attrs:
            node.attrs['id'] = self.message_id()
        if 'id' in node.attrs:
            msgid = node.attrs['id']
        data = node.to_string()
        log.debug(M("Send Node: {}", data))
        if node.tag == 'stream':
            data = data.replace('/>', '>')
        self.output_parser.parse(data)
        return msgid

    def getoutput(self):
        if self.output_buffer:
            return self.output_buffer.pop(0)

    def start(self):
        assert self.to
        attrs = self.attrs.copy()
        if self.to:
            attrs['to'] = self.to
        if self.frm:
            attrs['from'] = self.frm
        if self.session_id:
            attrs['id'] = self.session_id
        attrs['xml:lang'] = self.xml_lang
        attrs['xmlns:stream'] = NS_STREAMS
        attrs['xmlns'] = self.xmlns
        attrs['version'] = '1.0'
        stream = Node(
            'stream:stream', attrs=attrs,
        )
        self.sendnode(stream)

    def restart(self):
        log.debug('stream restart')
        self.configure_new_parsers()
        self.started = False
        self.start()

    def message_id(self, idgen=message_id):
        return idgen()

    def input_node_start(self, name, level, node):
        """
        """
        if level != 1:
            return
        if node.tag != 'stream':
            raise StreamError(
                'Unexpected stream start: {0}'.format(node.tag)
            )
        # Component streams will not have a version.
        if 'version' in node.attrs and node.attrs['version'] != self.version:
            raise StreamError(
                'Unexpected stream version: {0}'.format(node.attrs['version'])
            )
        if not self.started:
            if not self.to and 'from' in node.attrs:
                self.to = node.attrs['from']
            if not self.frm and 'to' in node.attrs:
                self.frm = node.attrs['to']
            if not self.session_id and 'id' in node.attrs:
                self.session_id = node.attrs['id']
            self.started = self.to
        else:
            if not self.session_id and 'id' in node.attrs:
                self.session_id = node.attrs['id']
            if not self.to == node.attrs['from']:
                log.warn(M("Stream header from does not match, expected {0}, got {1}",
                    self.to, node.attrs['from']))
            if 'to' in node.attrs and node.attrs['to'] != self.frm:
                log.warn(M("Stream header to does not match, expected {0}, got {1}",
                self.frm, node.attrs['to']))
        self.input_parser.unregister_start_handler(self.input_node_start)

    def output_node_start(self, name, level, node):
        """
        """
        if level != 1:
            return
        if node.tag != 'stream':
            raise StreamError(
                'Unexpected stream start: {0}'.format(node.tag)
            )
        if node.attrs['version'] != self.version:
            raise StreamError(
                'Unexpected stream version: {0}'.format(node.attrs['version'])
            )
        if not self.started:
            header = DOCHEAD + node.to_string().replace('/>', '>')
            self.output_buffer.append(header)
            self.started = self.frm
        else:
            if not self.session_id and 'id' in node.attrs:
                self.session_id = node.attrs['id']
            #if self.frm != node.attrs['from']:
            #    log.warn(M("Stream header from does not match, expected {0}, got {1}",
            #        self.frm, node.attrs['from']))
            #if self.to != node.attrs['to']:
            #    log.warn(M("Stream header to does not match, expected {0}, got {1}",
            #        self.to, node.attrs['to']))
        self.output_parser.unregister_start_handler(self.output_node_start)

    def input_node_end(self, name, level, node):
        if level != 2:
            return
        self.input_buffer.append(node)

    def output_node_end(self, name, level, node):
        if level != 2:
            return
        self.output_buffer.append(node.to_string())

    def bound(self):
        return self._features_handler not in list(self.handlers)

    def fileno(self):
        return self.transport.fileno()

