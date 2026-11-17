"""The reader JavaScript and the Django views must agree on parameter names.

media/js/newsblur builds its ajax payloads by hand. When a view stops reading a
name that the JavaScript keeps sending, nothing fails: the browser pays for a
dead parameter on every request and a future rename has no test to catch it.
This walks every make_request() call whose payload is an object literal,
resolves the URL through the URLconf (a NEWSBLUR.URLs key is looked up in the
table apps/reader/url_map.py generates), and asserts the resolved view reads
every key the client sends.

Dynamic payloads (an identifier or an expression instead of an object literal)
are skipped because their keys are only known at runtime.
"""

import ast
import inspect
import os
import re
import textwrap
import unittest

from django.conf import settings
from django.urls import Resolver404, resolve

from apps.reader.url_map import build_url_map

JS_ROOT = os.path.join(settings.MEDIA_ROOT, "js", "newsblur")

# Keys that reach a view without the view reading them as a request parameter.
ALLOWED_KEYS = set()

PARAM_ATTRS = {"GET", "POST", "REQUEST", "data", "query_params"}

# Helpers that take the parameter name as a string: int_argument(request, "page").
ARGUMENT_HELPERS = {
    "get_argument_or_404",
    "int_argument",
    "int_or_default",
    "float_or_default",
    "bool_or_default",
}

# Sanity floors so a parser regression cannot turn this test into a no-op.
MIN_CALLS = 50
MIN_RESOLVED = 40


# ---------------------------------------------------------------------------
# JavaScript side: find make_request() calls and their top level object keys.
# ---------------------------------------------------------------------------


def find_calls(text, name):
    """Yield the index of the open paren for every call of name( in text."""
    out = []
    for match in re.finditer(re.escape(name) + r"\s*\(", text):
        # Skip the definition itself: "make_request: function (".
        prefix = text[max(0, match.start() - 12) : match.start()]
        if re.search(r"(function\s+|:\s*)$", prefix):
            continue
        out.append(match.end() - 1)
    return out


def split_args(text, open_paren):
    """Return (start, end) for each top level argument of the call at open_paren."""
    depth = 0
    index = open_paren
    args = []
    start = open_paren + 1
    length = len(text)
    while index < length:
        char = text[index]
        if char in "'\"":
            quote = char
            index += 1
            while index < length:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == quote:
                    break
                index += 1
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                args.append((start, index))
                return args
        elif char == "," and depth == 1:
            args.append((start, index))
            start = index + 1
        index += 1
    return args


def top_keys(object_text):
    """Top level keys of an object literal body (text between the braces)."""
    keys = []
    depth = 0
    index = 0
    length = len(object_text)
    segment_start = 0
    while index < length:
        char = object_text[index]
        if char in "'\"":
            quote = char
            end = index + 1
            while end < length:
                if object_text[end] == "\\":
                    end += 2
                    continue
                if object_text[end] == quote:
                    break
                end += 1
            after = end + 1
            while after < length and object_text[after] in " \t\n":
                after += 1
            if depth == 0 and after < length and object_text[after] == ":":
                keys.append(object_text[index + 1 : end])
            index = end + 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            match = re.match(r"\s*([A-Za-z_$][\w$]*)\s*:", object_text[segment_start:index])
            if match:
                keys.append(match.group(1))
            segment_start = index + 1
        index += 1
    match = re.match(r"\s*([A-Za-z_$][\w$]*)\s*:", object_text[segment_start:])
    if match:
        keys.append(match.group(1))
    return keys


# A route read from the generated table: NEWSBLUR.URLs['load-feeds'] or NEWSBLUR.URLs.domain.
URLS_KEY_RE = re.compile(r"""NEWSBLUR\.URLs\[['"]([^'"]+)['"]\]|NEWSBLUR\.URLs\.([A-Za-z_][A-Za-z0-9_]*)""")


def path_from_url(raw):
    """Turn a JavaScript URL expression into a path the URLconf can resolve."""
    match = URLS_KEY_RE.search(raw)
    if match:
        key = match.group(1) or match.group(2)
        template = build_url_map().get(key)
        if not template:
            return None
        # Fill {feed_id} style holes with a value the URL patterns accept.
        return re.sub(r"\{[a-z_]+\}", "12345", template)
    parts = [first or second for first, second in re.findall(r"'([^']*)'|\"([^\"]*)\"", raw)]
    if not parts:
        return None
    path = parts[0]
    if len(parts) > 1 or re.search(r"\+\s*\w", raw):
        path += "12345"
    return path


# ---------------------------------------------------------------------------
# Python side: which parameter names does the resolved view read?
# ---------------------------------------------------------------------------


def closure_funcs(func):
    found = []
    for cell in getattr(func, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if inspect.isfunction(value):
            found.append(value)
    return found


def real_view(func):
    """Walk json_view / required_params wrappers down to the function in apps."""
    seen = set()
    current = func
    while True:
        if id(current) in seen:
            return current
        seen.add(id(current))
        if (getattr(current, "__module__", "") or "").startswith("apps."):
            return current
        candidates = closure_funcs(current)
        pick = next(
            (c for c in candidates if (getattr(c, "__module__", "") or "").startswith("apps.")),
            None,
        )
        if pick is None and candidates:
            pick = candidates[0]
        following = getattr(current, "__wrapped__", None) or pick
        if following is None:
            return current
        current = following


MODULE_AST = {}


def module_ast(module):
    name = getattr(module, "__name__", "?")
    if name not in MODULE_AST:
        try:
            MODULE_AST[name] = ast.parse(textwrap.dedent(inspect.getsource(module)))
        except Exception:
            MODULE_AST[name] = None
    return MODULE_AST[name]


def node_for(func):
    """Find the AST node of func, including methods of classes."""
    module = inspect.getmodule(func)
    tree = module_ast(module) if module else None
    if tree is None:
        return module, None
    line = getattr(getattr(func, "__code__", None), "co_firstlineno", None)
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.__name__
    ]
    for candidate in candidates:
        if line is not None and candidate.lineno == line:
            return module, candidate
    return module, (candidates[0] if candidates else None)


def is_request_container(expr):
    if (
        isinstance(expr, ast.Attribute)
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "request"
        and expr.attr in PARAM_ATTRS
    ):
        return True
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "getattr":
        return bool(expr.args and isinstance(expr.args[0], ast.Name) and expr.args[0].id == "request")
    return False


def is_request_body(expr):
    """request.body, and request.body.decode("utf-8")."""
    if isinstance(expr, ast.Attribute) and expr.attr == "body":
        return isinstance(expr.value, ast.Name) and expr.value.id == "request"
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "decode":
        return is_request_body(expr.func.value)
    return False


def json_body_names(node):
    """Names holding a decoded JSON body, as in body = json.decode(request.body).

    Those views read their parameters from the JSON payload instead of request.POST,
    so the keys they pull out are parameters like any other.
    """
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Assign) or len(child.targets) != 1:
            continue
        target = child.targets[0]
        value = child.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            continue
        if not isinstance(value.func, ast.Attribute) or value.func.attr not in ("decode", "loads"):
            continue
        if value.args and is_request_body(value.args[0]):
            names.add(target.id)
    return names


def local_containers(node):
    """Names assigned from a request container inside this function.

    get_post = getattr(request, request.method) is the usual one in reader views.
    """
    names = {}
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Assign)
            and len(child.targets) == 1
            and isinstance(child.targets[0], ast.Name)
            and is_request_container(child.value)
        ):
            names[child.targets[0].id] = "container"
    return names


def literal_string(node):
    """The value of a string literal node, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def is_local_container(expr, containers):
    """request.POST, or a name holding request.POST or a decoded JSON body."""
    if is_request_container(expr):
        return True
    return isinstance(expr, ast.Name) and expr.id in containers


def reads_in(node, containers):
    out = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if child.func.attr in ("get", "getlist", "pop", "setdefault"):
                if is_local_container(child.func.value, containers) and child.args:
                    out.append(literal_string(child.args[0]))
            if child.func.attr in ARGUMENT_HELPERS:
                out.extend(literal_string(arg) for arg in child.args[0:1])
        if isinstance(child, ast.Subscript) and is_local_container(child.value, containers):
            out.append(literal_string(child.slice))
        if isinstance(child, ast.Compare) and isinstance(child.left, ast.Constant):
            if isinstance(child.left.value, str):
                for comparator in child.comparators:
                    if is_local_container(comparator, containers):
                        out.append(child.left.value)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id in ARGUMENT_HELPERS:
                out.extend(literal_string(arg) for arg in child.args[1:2])
    return [key for key in out if key]


def collect_reads(func, depth=0, seen=None):
    """Parameter names read by func and the request helpers it calls."""
    seen = seen or set()
    key = (getattr(func, "__name__", ""), id(func))
    if key in seen:
        return []
    seen.add(key)
    module, node = node_for(func)
    if node is None:
        return []
    containers = local_containers(node)
    containers.update({name: "json_body" for name in json_body_names(node)})
    found = reads_in(node, containers)
    if depth >= 2:
        return found
    called = {
        child.func.id
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }
    for name in sorted(called):
        helper = getattr(module, name, None) if module else None
        if not inspect.isfunction(helper):
            continue
        try:
            parameters = list(inspect.signature(helper).parameters)
        except (ValueError, TypeError):
            continue
        if not parameters or parameters[0] not in ("request", "req", "r", "get_post"):
            continue
        found += collect_reads(helper, depth + 1, seen)
    return found


def view_reads(view):
    if hasattr(view, "view_class"):
        found = []
        for method in ("get", "post", "put", "delete"):
            handler = getattr(view.view_class, method, None)
            if handler:
                found += collect_reads(handler)
        return set(found)
    return set(collect_reads(view))


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


class Test_ParamContract(unittest.TestCase):
    def scan_calls(self):
        calls = []
        for dirpath, _, filenames in os.walk(JS_ROOT):
            for filename in filenames:
                if not filename.endswith(".js"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                for open_paren in find_calls(text, "make_request"):
                    args = split_args(text, open_paren)
                    if len(args) < 2:
                        continue
                    url_raw = text[args[0][0] : args[0][1]].strip()
                    data_raw = text[args[1][0] : args[1][1]].strip()
                    if not data_raw.startswith("{"):
                        continue
                    calls.append(
                        {
                            "file": os.path.relpath(path, settings.BASE_DIR),
                            "line": text.count("\n", 0, open_paren) + 1,
                            "url": url_raw,
                            "keys": top_keys(data_raw[1 : data_raw.rfind("}")]),
                        }
                    )
        return calls

    def test_analyzer_sees_parameters_read_from_request_bodies(self):
        """Pin the three shapes of read that the scan depends on."""
        json_body_view = real_view(resolve("/classifier/save_all").func)
        self.assertIn("classifiers", view_reads(json_body_view))

        post_view = real_view(resolve("/profile/set_collapsed_folders").func)
        self.assertIn("collapsed_folders", view_reads(post_view))
        self.assertNotIn("bogus_parameter", view_reads(post_view))

    def test_every_sent_parameter_is_read_by_its_view(self):
        calls = self.scan_calls()
        self.assertGreaterEqual(len(calls), MIN_CALLS, "the make_request scan stopped finding calls")

        resolved = 0
        violations = []
        for call in calls:
            path = path_from_url(call["url"])
            if not path:
                continue
            try:
                match = resolve(path)
            except Resolver404:
                continue
            resolved += 1
            view = real_view(match.func)
            reads = view_reads(view)
            unread = sorted({key for key in call["keys"] if key not in reads and key not in ALLOWED_KEYS})
            if unread:
                name = f"{getattr(view, '__module__', '?')}.{getattr(view, '__name__', '?')}"
                violations.append(
                    f"{call['file']}:{call['line']} {path} -> {name} sends {unread}, reads {sorted(reads)}"
                )

        self.assertGreaterEqual(resolved, MIN_RESOLVED, "the URL resolution stopped matching endpoints")
        self.assertEqual(
            violations,
            [],
            "JavaScript sends parameters the views never read:\n" + "\n".join(violations),
        )
