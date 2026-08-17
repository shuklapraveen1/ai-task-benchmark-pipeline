# Golden Solution

## Provenance

Source: history-derived
Parent commit: `4060fa593a2d8e024d526746450833322547f604`
Fixing commit: `efddd66371d14bace5dba919232cd809c1d83163`

## Reference Diff

```diff
diff --git a/docs/api.rst b/docs/api.rst
index 1bd35ae..90eb3f2 100644
--- a/docs/api.rst
+++ b/docs/api.rst
@@ -44,7 +44,7 @@ types that can be used with the basic set of Python builtins.
 
 
 .. autoclass:: glom.Path
-.. autoclass:: glom.Literal
+.. autoclass:: glom.Val
 .. autoclass:: glom.Spec
 
 .. _advanced-specifiers:
@@ -183,7 +183,6 @@ shortcut::
 **A** enables a shorthand which assigns the current target to a
 location in the scope.
 
-```
 
 Sensible saving - ``Vars`` & ``S.globals``
 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
diff --git a/docs/snippets.rst b/docs/snippets.rst
index 2db872b..02de050 100644
--- a/docs/snippets.rst
+++ b/docs/snippets.rst
@@ -244,7 +244,7 @@ simply:
 
 .. code-block:: python
 
-    glom(range(10), [(M < 7) | Literal(7)])
+    glom(range(10), [(M < 7) | Val(7)])
     # [0, 1, 2, 3, 4, 5, 6, 7, 7, 7]
 
 
@@ -252,7 +252,7 @@ What if you want to drop rather than clamp out-of-range values?
 
 .. code-block:: python
 
-    glom(range(10), [(M < 7) | Literal(SKIP)])
+    glom(range(10), [(M < 7) | Val(SKIP)])
     # [0, 1, 2, 3, 4, 5, 6]
 
 
diff --git a/glom/__init__.py b/glom/__init__.py
index 53569a4..801dbed 100644
--- a/glom/__init__.py
+++ b/glom/__init__.py
@@ -18,7 +18,7 @@ from glom.core import (glom,
                        Let,
                        Vars,
                        Val,
-                       Literal,
+                       Literal,  # backwards compat
                        Let,
                        Coalesce,
                        Inspect,
diff --git a/glom/core.py b/glom/core.py
index b640166..e9ae345 100644
--- a/glom/core.py
+++ b/glom/core.py
@@ -58,7 +58,7 @@ _MISSING = make_sentinel('_MISSING')
 SKIP =  make_sentinel('SKIP')
 SKIP.__doc__ = """
 The ``SKIP`` singleton can be returned from a function or included
-via a :class:`~glom.Literal` to cancel assignment into the output
+via a :class:`~glom.Val` to cancel assignment into the output
 object.
 
 >>> target = {'a': 'b'}
@@ -679,40 +679,6 @@ def _format_path(t_path):
     return _format_t(cur_t_path)
 
 
-class Literal(object):
-    """Literal objects specify literal values in rare cases when part of
-    the spec should not be interpreted as a glommable
-    subspec. Wherever a Literal object is encountered in a spec, it is
-    replaced with its wrapped *value* in the output.
-
-    >>> target = {'a': {'b': 'c'}}
-    >>> spec = {'a': 'a.b', 'readability': Literal('counts')}
-    >>> pprint(glom(target, spec))
-    {'a': 'c', 'readability': 'counts'}
-
-    Instead of accessing ``'counts'`` as a key like it did with
-    ``'a.b'``, :func:`~glom.glom` just unwrapped the literal and
-    included the value.
-
-    :class:`~glom.Literal` takes one argument, the literal value that should appear
-    in the glom output.
-
-    This could also be achieved with a callable, e.g., ``lambda x:
-    'literal_string'`` in the spec, but using a :class:`~glom.Literal`
-    object adds explicitness, code clarity, and a clean :func:`repr`.
-
-    """
-    def __init__(self, value):
-        self.value = value
-
-    def glomit(self, target, scope):
-        return self.value
-
-    def __repr__(self):
-        cn = self.__class__.__name__
-        return '%s(%s)' % (cn, bbrepr(self.value))
-
-
 class Spec(object):
     """Spec objects serve three purposes, here they are, roughly ordered
     by utility:
@@ -724,7 +690,7 @@ class Spec(object):
       3. A way to update the scope within another Spec.
 
     In the second usage, Spec objects are the complement to
-    :class:`~glom.Literal`, wrapping a value and marking that it
+    :class:`~glom.Val`, wrapping a value and marking that it
     should be interpreted as a glom spec, rather than a literal value.
     This is useful in places where it would be interpreted as a value
     by default. (Such as T[key], Call(func) where key and func are
@@ -1425,7 +1391,7 @@ def _t_eval(target, _t, scope):
     pae = None
     while i < fetch_till:
         op, arg = t_path[i], t_path[i + 1]
-        if type(arg) in (Spec, TType, Literal):
+        if type(arg) in (Spec, TType, Val):
             arg = scope[glom](target, arg, scope)
         if op == '.':
             try:
@@ -1519,7 +1485,7 @@ def _format_t(path, root=T):
 
 
 class Val(object):
-    """Val objects are specs which evaluate to the wrapped value.
+    """Val objects are specs which evaluate to the wrapped *value*.
 
     >>> target = {'a': {'b': 'c'}}
     >>> spec = {'a': 'a.b', 'readability': Val('counts')}
@@ -1531,16 +1497,26 @@ class Val(object):
     included the value.
 
     :class:`~glom.Val` takes one argument, the value to be returned.
+
+    .. note::
+
+       :class:`Val` was named ``Literal`` in versions of glom before
+       20.7.0. An alias has been preserved for backwards
+       compatibility, but reprs have changed.
+
     """
-    def __init__(self, val):
-        self.val = val
+    def __init__(self, value):
+        self.value = value
 
     def glomit(self, target, scope):
-        return self.val
+        return self.value
 
     def __repr__(self):
         cn = self.__class__.__name__
-        return '%s(%s)' % (cn, bbrepr(self.val))
+        return '%s(%s)' % (cn, bbrepr(self.value))
+
+
+Literal = Val  # backwards compat for pre-20.7.0
 
 
 class ScopeVars(object):
diff --git a/glom/matching.py b/glom/matching.py
index 3a3a1bd..448802f 100644
--- a/glom/matching.py
+++ b/glom/matching.py
@@ -14,7 +14,7 @@ from pprint import pprint
 from boltons.iterutils import is_iterable
 from boltons.typeutils import make_sentinel
 
-from .core import GlomError, glom, T, MODE, bbrepr, bbformat, format_invocation, Path, LAST_CHILD_SCOPE, Literal
+from .core import GlomError, glom, T, MODE, bbrepr, bbformat, format_invocation, Path, LAST_CHILD_SCOPE, Val
 
 
 _MISSING = make_sentinel('_MISSING')
@@ -484,10 +484,10 @@ class _MType(object):
     True
 
     :attr:`~glom.M` by itself evaluates the current target for truthiness.
-    For example, `M | Literal(None)` is a simple idiom for normalizing all falsey values to None:
+    For example, `M | Val(None)` is a simple idiom for normalizing all falsey values to None:
 
-    >>> from glom import Literal
-    >>> glom([0, False, "", None], [M | Literal(None)])
+    >>> from glom import Val
+    >>> glom([0, False, "", None], [M | Val(None)])
     [None, None, None, None]
 
     For convenience, ``&`` and ``|`` operators are overloaded to
@@ -765,8 +765,8 @@ class Switch(object):
     Here is a spec which differentiates between lowercase English
     vowel and consonant characters:
 
-      >>> switch_spec = Match(Switch([(Or('a', 'e', 'i', 'o', 'u'), Literal('vowel')),
-      ...                             (And(str, M, M(T[2:]) == ''), Literal('consonant'))]))
+      >>> switch_spec = Match(Switch([(Or('a', 'e', 'i', 'o', 'u'), Val('vowel')),
+      ...                             (And(str, M, M(T[2:]) == ''), Val('consonant'))]))
 
     The constructor accepts a :class:`dict` of ``{keyspec: valspec}``
     or a list of items, ``[(keyspec, valspec)]``. Keys are tried
@@ -790,8 +790,8 @@ class Switch(object):
       MatchError: error raised while processing, details below.
        Target-spec trace (most recent last):
        - Target: 3
-       - Spec: Match(Switch([(Or('a', 'e', 'i', 'o', 'u'), Literal('vowel')), (An...
-       - Spec: Switch([(Or('a', 'e', 'i', 'o', 'u'), Literal('vowel')), (And(str,...
+       - Spec: Match(Switch([(Or('a', 'e', 'i', 'o', 'u'), Val('vowel')), (An...
+       - Spec: Switch([(Or('a', 'e', 'i', 'o', 'u'), Val('vowel')), (And(str,...
        - Spec: Or('a', 'e', 'i', 'o', 'u')
        - Spec: 'a'
       MatchError: no matches for target in Switch
diff --git a/glom/test/test_basic.py b/glom/test/test_basic.py
index 6841931..a7b87f9 100644
--- a/glom/test/test_basic.py
+++ b/glom/test/test_basic.py
@@ -4,8 +4,8 @@ from xml.etree import cElementTree as ElementTree
 
 import pytest
 
-from glom import glom, SKIP, STOP, Path, Inspect, Coalesce, CoalesceError, Literal, Call, T, S, Invoke, Spec, Ref
-from glom import Auto, Fill, Iter, Let, A, Vars, Val, GlomError
+from glom import glom, SKIP, STOP, Path, Inspect, Coalesce, CoalesceError, Val, Call, T, S, Invoke, Spec, Ref
+from glom import Auto, Fill, Iter, Let, A, Vars, Val, Literal, GlomError
 
 import glom.core as glom_core
 from glom.core import UP, ROOT, Let, bbformat, bbrepr
@@ -173,17 +173,18 @@ def test_top_level_default():
     return
 
 
-def test_literal():
+def test_val():
+    assert Literal is Val
     expected = {'value': 'c',
                 'type': 'a.b'}
     target = {'a': {'b': 'c'}}
     val = glom(target, {'value': 'a.b',
-                        'type': Literal('a.b')})
+                        'type': Val('a.b')})
 
     assert val == expected
 
-    assert glom(None, Literal('success')) == 'success'
-    assert repr(Literal(3.14)) == 'Literal(3.14)'
+    assert glom(None, Val('success')) == 'success'
+    assert repr(Val(3.14)) == 'Val(3.14)'
     assert repr(Val(3.14)) == 'Val(3.14)'
 
 
@@ -215,8 +216,8 @@ def test_call_and_target():
     assert glom([1], Call(F, args=T)).a == 1
     assert glom(F, T(T)).a == F
     assert glom([F, 1], T[0](T[1]).a) == 1
-    assert glom([[1]], S[UP][Literal(T)][0][0]) == 1
-    assert glom([[1]], S[UP][UP][UP][Literal(T)]) == [[1]]  # tops out
+    assert glom([[1]], S[UP][Val(T)][0][0]) == 1
+    assert glom([[1]], S[UP][UP][UP][Val(T)]) == [[1]]  # tops out
 
     assert list(glom({'a': 'b'}, Call(T.values))) == ['b']
 
diff --git a/glom/test/test_let_vars.py b/glom/test/test_let_vars.py
index ef7cede..52ae474 100644
--- a/glom/test/test_let_vars.py
+++ b/glom/test/test_let_vars.py
@@ -1,7 +1,7 @@
 
 import pytest
 
-from glom import glom, Path, T, S, Literal, Let, A, Vars, Val, GlomError, M, Or, SKIP, Coalesce
+from glom import glom, Path, T, S, Val, Let, A, Vars, Val, GlomError, M, Or, SKIP, Coalesce
 
 from glom.core import ROOT
 from glom.mutation import PathAssignError
@@ -10,7 +10,7 @@ def test_let():
     data = {'a': 1, 'b': [{'c': 2}, {'c': 3}]}
     output = [{'a': 1, 'c': 2}, {'a': 1, 'c': 3}]
     assert glom(data, (Let(a='a'), ('b', [{'a': S['a'], 'c': 'c'}]))) == output
-    assert glom(data, ('b', [{'a': S[ROOT][Literal(T)]['a'], 'c': 'c'}])) == output
+    assert glom(data, ('b', [{'a': S[ROOT][Val(T)]['a'], 'c': 'c'}])) == output
 
     with pytest.raises(TypeError):
         Let('posarg')
diff --git a/glom/test/test_match.py b/glom/test/test_match.py
index d520286..fed13d5 100644
--- a/glom/test/test_match.py
+++ b/glom/test/test_match.py
@@ -4,7 +4,7 @@ import json
 
 import pytest
 
-from glom import glom, S, Literal, T, Merge, Fill, Let, Ref, Coalesce, STOP, Switch, GlomError
+from glom import glom, S, Val, T, Merge, Fill, Let, Ref, Coalesce, STOP, Switch, GlomError
 from glom.matching import (
     Match, M, MatchError, TypeMatchError, And, Or, Not,
     Optional, Required, Regex)
@@ -166,9 +166,9 @@ def test_precedence():
     """test corner cases of dict key precedence"""
     glom({(0, 1): 3},
         Match({
-            (0, 1): Literal(1),  # this should match
-            (0, int): Literal(2),  # optional
-            (0, M == 1): Literal(3),  # optional
+            (0, 1): Val(1),  # this should match
+            (0, int): Val(2),  # optional
+            (0, M == 1): Val(3),  # optional
         })
     )
     with pytest.raises(ValueError):
@@ -191,9 +191,9 @@ def test_cruddy_json():
 
 def test_pattern_matching():
     pattern_matcher = Or(
-        And(Match(1), Literal('one')),
-        And(Match(2), Literal('two')),
-        And(Match(float), Literal('float'))
+        And(Match(1), Val('one')),
+        And(Match(2), Val('two')),
+        And(Match(float), Val('float'))
         )
     assert glom(1, pattern_matcher) == 'one'
     assert glom(1.1, pattern_matcher) == 'float'
@@ -215,9 +215,9 @@ def test_pattern_matching():
 
 
 def test_examples():
-    assert glom(8, (M > 7) & Literal(7)) == 7
-    assert glom(range(10), [(M > 7) & Literal(7) | T]) == [0, 1, 2, 3, 4, 5, 6, 7, 7, 7]
-    assert glom(range(10), [(M > 7) & Literal(SKIP) | T]) == [0, 1, 2, 3, 4, 5, 6, 7]
+    assert glom(8, (M > 7) & Val(7)) == 7
+    assert glom(range(10), [(M > 7) & Val(7) | T]) == [0, 1, 2, 3, 4, 5, 6, 7, 7, 7]
+    assert glom(range(10), [(M > 7) & Val(SKIP) | T]) == [0, 1, 2, 3, 4, 5, 6, 7]
 
 
 def test_reprs():
@@ -368,8 +368,8 @@ def test_sky():
 
 
 def test_clamp():
-    assert glom(range(10), [(M < 7) | Literal(7)]) == [0, 1, 2, 3, 4, 5, 6, 7, 7, 7]
-    assert glom(range(10), [(M < 7) | Literal(SKIP)]) == [0, 1, 2, 3, 4, 5, 6]
+    assert glom(range(10), [(M < 7) | Val(7)]) == [0, 1, 2, 3, 4, 5, 6, 7, 7, 7]
+    assert glom(range(10), [(M < 7) | Val(SKIP)]) == [0, 1, 2, 3, 4, 5, 6]
 
 
 def test_json_ref():
@@ -379,7 +379,7 @@ def test_json_ref():
             Match(Or(
                 And(dict, {Ref('json'): Ref('json')}),
                 And(list, [Ref('json')]),
-                And(0, Literal(None)),
+                And(0, Val(None)),
                 object)))) == {'a': {'b': [None, 1]}}
 
 
@@ -441,7 +441,7 @@ def test_check_ported_tests():
     assert glom(target, [Match({'id': And(int, M <= 1)}, default=STOP)]) == [{'id': 0}, {'id': 1}]
 
     # check that stopping chain execution on non-passing values works
-    spec = (Or(Match(len), Literal(STOP)), T[0])
+    spec = (Or(Match(len), Val(STOP)), T[0])
     assert glom('hello', spec, glom_debug=True) == 'h'
     assert glom('', spec) == ''  # would fail with IndexError if STOP didn't work
```

## Why this is correct

The reference solution is the actual change introduced by the fixing commit. The input state is the parent commit, while the solution state is the post-fix commit, so this diff captures the repository's real historical behavioral correction.

## Validation

The task was accepted only after the strict verifier completed its required validation state machine. The machine-generated verification result is recorded below.

```json
{
  "deterministic_verified": true,
  "fail_before_verified": true,
  "pass_after_verified": true,
  "reasons": [],
  "validation_passed": true
}
```
