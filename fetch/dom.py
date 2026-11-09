"""A tiny, forgiving HTML tree builder (standard library only).

The sites we read are ordinary server-rendered pages. This builds a small
tree we can search by tag, class and attribute, without needing
BeautifulSoup or any other package on the GitHub runner.
"""
from html.parser import HTMLParser
import re

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "source", "track", "wbr"}
SKIP_TEXT = {"script", "style", "noscript", "template"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children = []
        self.parent = parent

    # --- attributes -------------------------------------------------------
    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def has_class(self, name):
        return name in self.classes

    def get(self, key, default=""):
        v = self.attrs.get(key)
        return default if v is None else v

    # --- traversal --------------------------------------------------------
    def iter(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.iter()

    def _matches(self, tag=None, cls=None, pred=None):
        return (n for n in self.iter()
                if (not tag or n.tag == tag) and (not cls or cls in n.classes) and (not pred or pred(n)))

    def find_all(self, tag=None, cls=None, pred=None):
        return list(self._matches(tag, cls, pred))

    def find(self, tag=None, cls=None, pred=None):
        return next(self._matches(tag, cls, pred), None)

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    @property
    def text(self):
        parts = []

        def walk(n):
            for c in n.children:
                if isinstance(c, str):
                    parts.append(c)
                elif c.tag not in SKIP_TEXT:
                    walk(c)
                    if c.tag in ("br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4"):
                        parts.append(" ")
        walk(self)
        return re.sub(r"\s+", " ", "".join(parts).replace("\xa0", " ")).strip()

    def links(self):
        return [a for a in self.find_all("a") if a.get("href")]

    def __repr__(self):
        return f"<{self.tag} {self.attrs.get('class', '')}>"


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    @property
    def cur(self):
        return self.stack[-1]

    def _close_until(self, tags, stop=("table",)):
        """Implicitly close the nearest open element in `tags`, without
        crossing an element in `stop`."""
        for i in range(len(self.stack) - 1, 0, -1):
            t = self.stack[i].tag
            if t in tags:
                del self.stack[i:]
                return
            if t in stop:
                return

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self._close_until({"td", "th"}, stop=("tr", "table"))
        elif tag == "tr":
            self._close_until({"tr"}, stop=("table", "thead", "tbody", "tfoot"))
        elif tag == "li":
            self._close_until({"li"}, stop=("ul", "ol"))
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data:
            self.cur.children.append(data)


def parse(html):
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def rows(table):
    """Rows of a table, including those inside thead/tbody/tfoot, in order."""
    return [r for r in table.find_all("tr")
            if next((a for a in r.ancestors() if a.tag == "table"), None) is table]


def cells(row):
    return [c for c in row.children if isinstance(c, Node) and c.tag in ("td", "th")]
