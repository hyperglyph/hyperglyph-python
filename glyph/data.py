from urlparse import urljoin
import datetime
import io


from pytz import utc

from .encoding import Encoder, CONTENT_TYPE, Blob


def utcnow():
    return datetime.datetime.utcnow().replace(tzinfo=utc)


def node(name, attributes, content=None):
    return Node(unicode(name), attributes, content)

def robj(obj, contents):
    return Extension.__make__(u'resource', {u'name':unicode(obj.__class__.__name__), u'url': obj}, contents)

def form(url, method=u'POST',values=None):
    if values is None:
        if ismethod(url):
            values = methodargs(url)
        elif isinstance(url, type):
            values = methodargs(url.__init__)
        elif callable(url):
            values = funcargs(url)

    if values is not None:
        values = [unicode(v) for v in values]

    return Extension.__make__(u'form', {u'method':method, u'url':url, u'values':values}, None)

def link(url, method='GET'):
    return Extension.__make__(u'link', {u'method':method, u'url':url}, None)

def embedlink(url, content, method=u'GET'):
    return Extension.__make__(u'link', {u'method':method, u'url':url, u'inline':True}, content)

def error(reference, message):
    return Extension.__make__(u'error', {u'logref':reference, u'message':message}, {})


# move to inspect ?

def ismethod(m, cls=None):
    return callable(m) and hasattr(m,'im_self') and (cls is None or isinstance(m.im_self, cls))

def methodargs(m):
    if ismethod(m):
        return m.func_code.co_varnames[1:]

def funcargs(m):
    return m.func_code.co_varnames[:]

def get(url, args=None, headers=None):
    if hasattr(url, u'url'):
        url = url.url()
    return fetch('GET', url, args, None, headers)


HEADERS={'Accept': CONTENT_TYPE, 'Content-Type': CONTENT_TYPE}
try:
    import requests
    session = requests.session()
except:
    import urllib2, urllib, collections
    Result = collections. namedtuple('Result', 'url, status_code, content,  headers,  raise_for_status') 
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    class session(object):
        @staticmethod

        def request(method, url, params, data, headers, allow_redirects):
            url = "%s?%s" % (url, urllib.urlencode(params)) if params else url

            if data:
                req = urllib2.Request(url, data)
            else:
                req = urllib2.Request(url)

            for header, value in headers.items():
                req.add_header(header, value)
            req.get_method = lambda: method
            try:
                result = opener.open(req)

                return Result(result.geturl(), result.code, result.read(), result.info(), lambda: None)
            except StopIteration: # In 2.7 this does not derive from Exception
                raise
            except StandardError as e:
                import traceback
                traceback.print_exc()
                raise StandardError(e)


class IteratorFile(object):
    
    def __init__(self, iterator, chunked=False):
        self.iterator = iterator
        self.chunked = chunked
        self.eof = False
    
    def read(self, n=None):
        if n is None:
            return "".join(self.iterator)
        data = next(self.iterator, "")
        if self.chunked:
            chunk = "".join(("%X\r\n" % len(data), data, "\r\n"))
        else:
            chunk = data
        ret = None if self.eof else chunk
        if not data:
            self.eof = True
        return ret


def fetch(method, url, args=None, data=None, headers=None, chunked=False):
    if headers is None:
        headers = {}
    headers.update(HEADERS)
    if args is None:
        args = {}
    if data is not None:
        data = IteratorFile(dump_iter(data, chunk_size=4096), chunked=chunked)
        if data.chunked:
            headers["Transfer-Encoding"] = "chunked"
        else:
            data = data.read()
    result = session.request(method, url, params=args, data=data, headers=headers, allow_redirects=False)
    def join(u):
        return urljoin(result.url, u)
    if result.status_code == 303: # See Other
        return get(join(result.headers['Location']))
    elif result.status_code == 204: # No Content
        return None
    elif result.status_code == 201: # 
        # never called
        return link(join(result.headers['Location']))

    result.raise_for_status()
    data = result.content
    if result.headers['Content-Type'].startswith(CONTENT_TYPE):
        data = parse(data, join)
    return data


class BaseNode(object):
    def __init__(self, name, attributes, content):
        self._name = name
        self._attributes = attributes
        self._content = content
    def __getstate__(self):
        return self._name, self._attributes, self._content

    def __setstate__(self, state):
        self._name = state[0]
        self._attributes = state[1]
        self._content = state[2]

    def __eq__(self, other):
        return self._name == other._name and self._attributes == other._attributes and self._content == other._content

    @classmethod
    def __make__(cls, name, attributes, content):
        return cls(name,attributes, content)

class Node(BaseNode):
    def __getattr__(self, name):
        try:
            return self._content[name]
        except KeyError:
            raise AttributeError(name)

    def __getitem__(self, name):
        return self._content[name]

    def __repr__(self):
        return '<node:%s %s %s>'%(self._name, repr(self._attributes), repr(self._content))

class Extension(BaseNode):
    _exts = {}
    @classmethod
    def __make__(cls, name, attributes, content):
        ext = cls._exts.get(name, node)
        return ext(name,attributes, content)
    
    @classmethod
    def register(cls, name):
        def _decorator(fn):
            cls._exts[name] = fn
            return fn
        return _decorator

    def __eq__(self, other):
        return isinstance(other, Extension) and BaseNode.__eq__(self, other)

    def __repr__(self):
        return '<ext:%s %s %s>'%(self._name, repr(self._attributes), repr(self._content))

    def __resolve__(self, resolver):
        pass

@Extension.register('form')
class Form(Extension):
    def __call__(self, *args, **kwargs):
        url = self._attributes[u'url']
        data = []
        names = self._attributes[u'values']
        if names:
            for n,v in zip(names, args):
                data.append((n,v))
        elif args:
            raise StandardError('no unamed arguments')

        for k,v in kwargs.items():
            if k in names:
                data.append((k,v))
            else:
                raise StandardError('unknown argument')

        chunked = getattr(self, "chunked", any([isinstance(v, Blob) for k, v in data]))

        return fetch(self._attributes.get(u'method',u'POST'), url, data=data, chunked=chunked)

    def __resolve__(self, resolver):
        self._attributes[u'url'] = unicode(resolver(self._attributes[u'url']))

@Extension.register('link')
class Link(Extension):
    def __call__(self, *args, **kwargs):
        if self._attributes.get(u'inline', False):
            return self._content
        else:
            url = self._attributes[u'url']
            return fetch(self._attributes.get(u'method',u'GET'),url)

    def url(self):
        return self._attributes[u'url']
        
    def __resolve__(self, resolver):
        self._attributes[u'url'] = unicode(resolver(self._attributes[u'url']))

@Extension.register('resource')
class Resource(Extension):
        
    def __resolve__(self, resolver):
        self._attributes[u'url'] = unicode(resolver(self._attributes[u'url']))

    def __getattr__(self, name):
        try:
            return self._content[name]
        except KeyError:
            raise AttributeError(name)

@Extension.register('error')
class Error(Extension):
    @property
    def message(self):
        return self._attributes[u'message']

    @property
    def logref(self):
        return self._attributes[u'logref']


_encoder = Encoder(node=Node, extension=Extension)

dump = _encoder.dump
dump_iter = _encoder.dump_iter
parse = _encoder.parse
read = _encoder.read
