# Golden Solution

## Provenance

Source: history-derived
Parent commit: `0899ffe23b5bb5dec34893df9175504f543f6c5a`
Fixing commit: `062b0894d19faf2bf295cfc6812dd9ce268d55ff`

## Reference Diff

```diff
diff --git a/glom/core.py b/glom/core.py
index af57d28..fb9365b 100644
--- a/glom/core.py
+++ b/glom/core.py
@@ -138,10 +138,15 @@ class GlomError(Exception):
         bases = (GlomError,) if issubclass(GlomError, exc_type) else (exc_type, GlomError)
         exc_wrapper_type = type("GlomError.wrap({})".format(exc_type.__name__), bases, {})
         try:
-            return exc_wrapper_type(*exc.args)
+            wrapper = exc_wrapper_type(*exc.args)
+            wrapper.__wrapped = exc
+            return wrapper
         except Exception:  # maybe exception can't be re-created
             return exc
 
+    def _set_wrapped(self, exc):
+        self.__wrapped = exc
+
     def _finalize(self, scope):
         # careful when changing how this functionality works; pytest seems to mess with
         # the traceback module or sys.exc_info(). we saw different stacks when originally
@@ -161,7 +166,7 @@ class GlomError(Exception):
         if getattr(self, '_finalized_str', None):
             return self._finalized_str
         elif getattr(self, '_scope', None) is not None:
-            self._target_spec_trace = format_target_spec_trace(self._scope)
+            self._target_spec_trace = format_target_spec_trace(self._scope, self.__wrapped)
             parts = ["error raised while processing, details below.",
                      " Target-spec trace (most recent last):",
                      self._target_spec_trace]
@@ -215,7 +220,7 @@ def _format_trace_value(value, maxlen):
     return s
 
 
-def format_target_spec_trace(scope, width=TRACE_WIDTH, depth=0, prev_target=_MISSING):
+def format_target_spec_trace(scope, root_error, width=TRACE_WIDTH, depth=0, prev_target=_MISSING):
     """
     unpack a scope into a multi-line but short summary
     """
@@ -227,7 +232,7 @@ def format_target_spec_trace(scope, width=TRACE_WIDTH, depth=0, prev_target=_MIS
         return lambda v: pre + _format_trace_value(v, fmt_width)
     fmt_t = mk_fmt("Target")
     fmt_s = mk_fmt("Spec")
-    recurse = lambda s: format_target_spec_trace(s, width, depth + 1, prev_target)
+    recurse = lambda s: format_target_spec_trace(s, root_error, width, depth + 1, prev_target)
     tb_exc_line = lambda e: "".join(traceback.format_exception_only(type(e), e))[:-1]
     fmt_e = lambda e: indent + " - " + tb_exc_line(e)
     if depth:
@@ -237,8 +242,10 @@ def format_target_spec_trace(scope, width=TRACE_WIDTH, depth=0, prev_target=_MIS
             segments.append(fmt_t(target))
         prev_target = target
         segments.append(fmt_s(spec))
-        if error is not None and depth:
+        if error is not None and error is not root_error:
             segments.append(fmt_e(error))
+            print(error.__class__.__name__, str(error), " is not ", root_error.__class__.__name__)
+            print(id(error) % 1000, "is not", id(root_error) % 1000)
         segments.extend([recurse(s) for s in branches])
     return "\n".join(segments)
 
@@ -1855,6 +1862,7 @@ def glom(target, spec, **kwargs):
             # need to change id or else py3 seems to not let us truncate the
             # stack trace with the explicit "raise err" below
             err = copy.copy(e)
+            err._set_wrapped(e)
         else:
             err = GlomError.wrap(e)
         if isinstance(err, GlomError):
@@ -1877,8 +1885,7 @@ def chain_child(scope):
 
     scope[glom](target, spec, chain_child(scope))
     """
-    cur_vars = scope.maps[0]
-    if LAST_CHILD_SCOPE not in cur_vars:
+    if LAST_CHILD_SCOPE not in scope.maps[0]:
         return scope  # no children yet, nothing to do
     nxt_in_chain = scope[LAST_CHILD_SCOPE]
     nxt_in_chain.maps[0][NO_PYFRAME] = True
diff --git a/glom/test/test_error.py b/glom/test/test_error.py
index 6474274..37d05c8 100644
--- a/glom/test/test_error.py
+++ b/glom/test/test_error.py
@@ -48,7 +48,7 @@ def test_line_trace():
 def test_short_trace():
     stacklifier = ([{'data': S}],)
     scope = glom([1], stacklifier)[0]['data'][ROOT][LAST_CHILD_SCOPE]
-    fmtd_stack = format_target_spec_trace(scope)
+    fmtd_stack = format_target_spec_trace(scope, None)
     exp_lines = [
         " - Target: [1]",
         " - Spec: ([{'data': S}],)",
@@ -280,7 +280,6 @@ glom.core.PathAccessError: error raised while processing, details below.
   Failed Branch:
    - Spec: [None]
    - Spec: T.a
-   - glom.core.PathAccessError: could not access 'a', part 0 of T.a, got error: AttributeError("'list' object has no attribute 'a'")
 glom.core.PathAccessError: could not access 'a', part 0 of T.a, got error: AttributeError("'list' object has no attribute 'a'")
 """
     # branch and another branch
@@ -306,7 +305,6 @@ glom.core.PathAccessError: error raised while processing, details below.
   Failed Branch:
    - Spec: [None]
    - Spec: Switch([(1, 1), ('a', 'a'), ([None], T.a)])
-   - glom.core.PathAccessError: could not access 'a', part 0 of T.a, got error: AttributeError("'list' object has no attribute 'a'")
     Failed Branch:
      - Spec: 1
      - glom.matching.MatchError: [None] does not match 1
@@ -316,7 +314,6 @@ glom.core.PathAccessError: error raised while processing, details below.
     Failed Branch:
      - Spec: [None]
      - Spec: T.a
-     - glom.core.PathAccessError: could not access 'a', part 0 of T.a, got error: AttributeError("'list' object has no attribute 'a'")
 glom.core.PathAccessError: could not access 'a', part 0 of T.a, got error: AttributeError("'list' object has no attribute 'a'")
 """
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
