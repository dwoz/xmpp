from agent.xmpp.xmlutil import *
import unittest
from mock import Mock

import agent.logger
agent.logger.logger_agent.setLevel(agent.logger.CRITICAL)

class TestXmlUtil(unittest.TestCase):
    stream = """<?xml version='1.0'?>
        <stream>
           this <i/> old thing <b> is a </b> test
        </stream>
    """

    def test_to_string(self):
        n = Node('stream',
                attrs={'foo':'bar'},
                payload=[
                    Node('message',
                        payload=[
                            Node('body',
                                payload=[
                                    'hi',
                                    Node('b',
                                        payload=[
                                            'my name is'
                                        ]
                                    ),
                                    'fred'
                                ]
                            )
                        ]
                    )
                ]
            )
        assert to_string(n) == \
            '<stream foo="bar"><message><body>hi<b>my name' + \
            ' is</b>fred</body></message></stream>', to_string(n)

    def test_to_pretty_string1(self):
        n = Node('stream',
                attrs={'foo':'bar'},
                payload=[
                    Node('message',
                        payload=[
                            Node('body',
                                payload=[
                                    'hi',
                                    Node('b',
                                        payload=[
                                            'my name is'
                                        ]
                                    ),
                                    'fred'
                                ]
                            )
                        ]
                    )
                ]
            )
        assert to_string(n, pretty=True) == \
            '<stream foo="bar">\n' + \
            '  <message>\n' + \
            '    <body>\n' + \
            '      hi\n' + \
            '      <b>\n' + \
            '        my name is\n' + \
            '      </b>\n' + \
            '      fred\n' + \
            '    </body>\n' + \
            '  </message>\n' + \
            '</stream>', to_string(n, pretty=True)

    def test_to_pretty_string2(self):
        parser = XmlParser()
        parser.parse(self.stream)
        assert to_string(parser.getroot(), pretty=True) ==  \
            '<stream>\n' + \
            '  this\n' + \
            '  <i/>\n' + \
            '  old thing\n' + \
            '  <b>\n' + \
            '    is a\n' + \
            '  </b>\n' + \
            '  test\n' + \
            '</stream>', to_string(parser.getroot(), pretty=True)

    def test_parser(self):
        parser = XmlParser()
        parser.parse(self.stream)
        assert len(parser.elements) == 1
        n = parser.getroot()
        assert n.tag == 'stream', n.tag
        assert len(n.payload) == 5
        assert len(n.get_children()) == 2, len(n.get_children())

    def test_escape(self):
        n = Node('message', attrs={'to': 'ol&ver@example.com'})
        assert to_string(n) == '<message to="ol&amp;ver@example.com"/>'
        n = Node('message', payload=["speak <b>out</b>"])
        assert to_string(n) == \
            '<message>speak &lt;b&gt;out&lt;/b&gt;</message>', to_string(n)

    def test_namespace(self):
        n = Node('stream', namespace='http://foo.com')
        assert n.to_string() == '<stream xmlns="http://foo.com"/>', \
            "'{}'".format(n.to_string())

    def test_parser_node_builder(self):
        node_builder = Mock()
        parser = XmlParser(node_builder=node_builder)
        parser.parse('<stream foo="bar" />')
        node_builder.assert_called_with(parser, 'stream', {'foo': 'bar'}, 1)

    def test_parser_node_start(self):
        node_start = Mock()
        n = Node('stream', attrs={u'foo': u'bar'})
        node_builder = Mock()
        node_builder.return_value = n
        parser = XmlParser(name='parser', node_builder=node_builder)
        parser.register_start_handler(node_start)
        parser.parse('<stream foo="bar" />')
        node_start.assert_called_with('parser', 1, n)

    def test_parser_node_end(self):
        node_end = Mock()
        n = Node('stream', attrs={u'foo': u'bar'})
        node_builder = Mock()
        node_builder.return_value = n
        parser = XmlParser(name='parser', node_builder=node_builder)
        parser.register_end_handler(node_end)
        parser.parse('<stream foo="bar" />')
        node_end.assert_called_with('parser', 1, n)

    def test_node_init1(self):
        n = Node('stream:stream')
        assert n.tag == 'stream'

    def test_isescaped(self):
        assert not isescaped('&fakuIw0nt)oWh4Ut331m3')
        assert isescaped('ok, its &lt; ok')

    def test_node_set_attr(self):
        n = Node()
        n.set_attr('foo', 'bar')
        assert 'foo' in n.attrs and n.attrs['foo'] == 'bar'

    def test_node_get_attr(self):
        n = Node(attrs={'foo':'bar'})
        assert n.get_attr('foo') == 'bar'

    def test_node_get_children(self):
        chld = Node('query')
        n = Node('iq',
            attrs={'type': 'get'},
            payload=[
                chld
            ],
        )
        assert n.get_children() == [chld]

    def test_node_add_child(self):
        chld = Node('query')
        n = Node('iq', attrs={'type': 'get'})
        n.add_child(chld)
        assert n.get_children() == [chld]
        assert n.payload == [chld]
        assert chld.parent == n

    def test_node_get_tags_tag_name(self):
        chlda = Node('query', namespace='bang')
        chldb = Node('query', attrs={'foo':'bar'})
        nodes = [chlda, chldb]
        n = Node('iq', payload=nodes)
        assert n.get_tags('query') == nodes

    def test_node_get_tags_namespaec(self):
        chlda = Node('query', namespace='a')
        chldb = Node('query', namespace='b')
        nodes = [chlda, chldb]
        n = Node('iq', payload=nodes)
        assert n.get_tags('query', namespace='a') == [chlda]

    def test_node_nsmap(self):
        n = Node('stream:stream', attrs={
            'xmlns': 'streams:client',
            'xmlns:stream': 'http://xmpp.org',
        })
        assert n.nsmap[None] == 'streams:client'
        assert n.nsmap['stream'] == 'http://xmpp.org'

    def test_node_nsmap_a(self):
        x = """
        <stream:stream xmlns="jabber:client"
            from="dev.az.h4.cx"
            version="1.0"
            xmlns:stream="http://etherx.jabber.org/streams"
            id="dad20c4ef1f849b7a49af25a65a0b5c2f9d029ed">
          <stream:features xmlns="http://etherx.jabber.org/streams">
            <mechanisms xmlns="urn:ietf:params:xml:ns:xmpp-sasl">
              <mechanism>SCRAM-SHA-1</mechanism>
              <mechanism>DIGEST-MD5</mechanism>
              <mechanism>PLAIN</mechanism>
            </mechanisms>
          </stream:features>
        </stream:stream>
        """
        n = Node.from_string(x)
        f = n.get_tags('features')[0]
        assert f.namespace == "http://etherx.jabber.org/streams"
        assert f.nsmap == {
            None: "http://etherx.jabber.org/streams",
            'stream':"http://etherx.jabber.org/streams",
        }, 'band nsmap'

