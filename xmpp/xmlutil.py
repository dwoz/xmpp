import xml.parsers.expat
from orvant.dna import DataDict
import sys, re
from agent.util import M

import logging
log = logging.getLogger(__name__)

DOCHEAD = """<?xml version='1.0'?>"""

ESCAPECHARS = [
    ('&', '&amp;'),
    ('<', '&lt;'),
    ('>', '&gt;'),
    ('"', '&quote;'),
    ("'", '&#39;'), # &apos; not in HTML 4
]

def xmlescape(s, chars=ESCAPECHARS):
    if isescaped(s):
        return s
    for a, b in chars:
        s = s.replace(a, b)
    return s

def isescaped(s):
    r = re.compile('(&amp;|&quote|&#39;|&gt;|&lt;|&#60;|&#62;|&#34;|&#38;|&apos;)')
    return r.search(s) is not None

def to_string(node, escape=xmlescape, level=0, pretty=False):
    if pretty:
        nlifp = '\n'
    else:
        nlifp = ''
    s = '  ' * level
    if node.prefix:
        s += '<{0}:{1}'.format(node.prefix, node.tag)
    else:
        s += '<{0}'.format(node.tag)
    for k in node._nsmap:
        if k:
            s += ' xmlns:{0}="{1}"'.format(k, node._nsmap[k])
        else:
            s += ' xmlns="{0}"'.format(node._nsmap[k])
    #if node.namespace:
    #    if not node.parent or node.parent.namespace != node.namespace:
    #        s = s + ' xmlns="{0}"'.format(node.namespace)
    for key in node.attrs:
        s += ' {0}="{1}"'.format(key, escape(str(node.attrs[key])))
    if node.payload:
        s += '>{0}'.format(nlifp)
        for i in node.payload:
            if isinstance(i, node.__class__):
                if pretty:
                    level += 1
                s += to_string(i, escape, level, pretty)
                if pretty:
                    level -= 1
            else:
                if pretty:
                    s += '  ' * (level + 1)
                s += '{0}{1}'.format(escape(i), nlifp)
        s += '  ' * level
        if node.prefix:
            s += '</{0}:{1}>{2}'.format(node.prefix, node.tag, nlifp)
        else:
            s += '</{0}>{1}'.format(node.tag, nlifp)
    else:
        s += '/>{0}'.format(nlifp)
    if level == 0:
        return s.strip()
    return s

def node_builder(parser, tag, attrs, level):
    return Node(tag, attrs)

class XmlParser(object):

    def __init__(self, name='', level=0, current_element=None, buffer_text=True,
            node_builder=node_builder):
        self.name = name
        self.level = level
        self.current_element = None
        self.elements = []
        self._configure_parser(buffer_text)
        self.node_builder = node_builder
        self.handlers = {'start':[], 'end':[]}

    def _configure_parser(self, buffer_text):
        self.parser = xml.parsers.expat.ParserCreate()
        self.parser.StartElementHandler = self.StartElementHandler
        self.parser.EndElementHandler = self.EndElementHandler
        self.parser.CharacterDataHandler = self.CharacterDataHandler
        self.parser.StartNamespaceDeclHandler = self.StartNamespaceDeclHandler
        self.parser.buffer_text = buffer_text

    def StartElementHandler(self, tag, attrs):
        self.level += 1
        e = self.node_builder(self, tag, attrs, self.level)
        if self.level > 1:
            p = self.current_element
            p.add_child(e)
        self.current_element = e
        for handler in self.handlers['start']:
            handler(self.name, self.level, e)
        log.debug(M('StartElementHandler: {0} {1}', tag, self.level))

    def EndElementHandler(self, tag):
        log.debug(M('EndElementHandler: {0} {1}', tag, self.level, self.current_element))
        for handler in self.handlers['end']:
            handler(self.name, self.level, self.current_element)
        if self.level > 1:
            self.current_element = self.current_element.parent
        if self.level == 1:
            self.elements.append(self.current_element)
        self.level -= 1

    def CharacterDataHandler(self, data):
        log.debug(M('CharachterDataHandler: {0}', data))
        self.current_element.add_child(data)

    def StartNamespaceDeclHandler(self, prefix, url):
        log.debug(M('StartNamespaceDeclHandler: {0} {1}', prefix, url))

    def parse(self, s):
        self.parser.Parse(s)
        return self

    def getroot(self):
        if len(self.elements) > 1:
            raise Exception("Multiple root elements")
        return self.elements[0]

    def register_start_handler(self, handler):
        self.handlers['start'].append(handler)

    def unregister_start_handler(self, handler):
        self.handlers['start'].remove(handler)

    def register_end_handler(self, handler):
        self.handlers['end'].append(handler)

    def unregister_end_handler(self, handler):
        self.handlers['end'].remove(handler)

    def set_node_builder(self, node_builder):
        self.node_builder = node_builder


def from_string(data, parser_cls=XmlParser):
    return parser_cls().parse(data).getroot()

class Node(object):

    _to_string = to_string
    _from_string = staticmethod(from_string)

    def __init__(self, tag=None, attrs={}, payload=[], parent=None, prefix=None, namespace=''):
        self._nsmap = {}
        self._attrs = {}
        self.attrs = dict(attrs)
        if tag and ':' in tag:
            prefix, tag = tag.split(':')
        self.tag = tag
        self.prefix = prefix # Namespace Prefix
        self.parent = parent
        if namespace:
            self.namespace = namespace # Namespace
        self.payload = []
        for a in payload:
            self.add_child(a)

    def set_attr(self, key, val):
        self.attrs[key] = val

    def get_attr(self, key):
        return self.attrs.get(key, None)

    def get_children(self):
        children = []
        for a in self.payload:
            if isinstance(a, Node):
                children.append(a)
        return children

    def add_child(self, a):
        if isinstance(a, Node):
            a.parent = self
        else:
            a = a.strip()
        self.payload.append(a)

    def get_tags(self, name=None, attrs={}, namespace=None, one=0):
        """
        Filters all child nodes using specified arguments as filter.
        Returns the list of nodes found.
        """
        nodes=[]
        for node in self.get_children():
            if not node:
                continue
            if namespace and namespace != node.namespace:
                log.debug(M('bad namespace: {0} {1}', namespace, node.namespace))
                continue
            if node.tag == name or name is None:
                if attrs:
                    for key in attrs.keys():
                        if key not in node.attrs or node.attrs[key] != attrs[key]:
                            break
                else:
                    nodes.append(node)
            if one and nodes:
                return nodes[0]
        if not one:
            return nodes

    def __repr__(self):
        return "<Node(tag='{0}', attrs={1}, ...)>".format(
            self.tag, str(self.attrs)
        )

    def to_string(self):
        return self._to_string()

    def to_pretty_string(self):
        return self._to_string(pretty=True)

    def set_ns(self, key, val):
        if ':' in key:
            _, key = key.split(':')
        else:
            key = None
        self._nsmap[key] = val

    @classmethod
    def from_string(cls, data):
        return cls._from_string(data)

    @property
    def attrs(self):
        return self._attrs

    @attrs.setter
    def attrs(self, attrs):
        for x in attrs.copy():
            if x.startswith('xmlns'):
                self.set_ns(x, attrs.pop(x))
        self._attrs = attrs

    @property
    def namespace(self):
        if self.prefix in self.nsmap:
            return self.nsmap[self.prefix]

    @namespace.setter
    def namespace(self, namespace):
        self._nsmap[self.prefix] = namespace

    @property
    def nsmap(self):
        nsmap = {}
        parents = self._get_parents()
        parents.reverse()
        for p in parents:
            nsmap.update(p._nsmap)
        nsmap.update(self._nsmap)
        return nsmap

    def get_root(self):
        return self._get_parents()[-1]

    def _get_parents(self):
        parents = []
        node = self
        while node.parent:
            parents.append(node.parent)
            node = node.parent
        return parents
