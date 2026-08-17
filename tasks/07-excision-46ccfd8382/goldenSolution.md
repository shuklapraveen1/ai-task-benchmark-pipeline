# Golden Solution

## Provenance

Source: excision (red → green)
Target module: `glom.mutation`
Target: `function:glom.mutation.assign`

## Reference Diff

```diff
diff --git "a/tasks\\07-excision-46ccfd8382\\input/glom/mutation.py" "b/tasks\\07-excision-46ccfd8382\\solution/glom/mutation.py"
index 7f0a17c..44ef45b 100644
--- "a/tasks\\07-excision-46ccfd8382\\input/glom/mutation.py"
+++ "b/tasks\\07-excision-46ccfd8382\\solution/glom/mutation.py"
@@ -196,7 +196,21 @@ class Assign:
 
 
 def assign(obj, path, val, missing=None):
-    return None
+    """*New in glom 18.3.0*
+
+    The ``assign()`` function provides convenient "deep set"
+    functionality, modifying nested data structures in-place::
+
+      >>> target = {'a': [{'b': 'c'}, {'d': None}]}
+      >>> _ = assign(target, 'a.1.d', 'e')  # let's give 'd' a value of 'e'
+      >>> pprint(target)
+      {'a': [{'b': 'c'}, {'d': 'e'}]}
+
+    Missing structures can also be automatically created with the
+    *missing* parameter. For more information and examples, see the
+    :class:`~glom.Assign` specifier type, which this function wraps.
+    """
+    return glom(obj, Assign(path, val, missing=missing))
 
 
 _ALL_BUILTIN_TYPES = [v for v in __builtins__.values() if isinstance(v, type)]
```

## Why this is correct

The input state contains the selected implementation removed from its original function, while solution/ preserves the working repository implementation. Therefore the input-to-solution diff is the original implementation that restores the behavior required by the verifier.

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
