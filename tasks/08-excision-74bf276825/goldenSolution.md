# Golden Solution

## Provenance

Source: excision (red → green)
Target module: `glom.reduction`
Target: `function:glom.reduction.flatten`

## Reference Diff

```diff
diff --git "a/tasks\\08-excision-74bf276825\\input/glom/reduction.py" "b/tasks\\08-excision-74bf276825\\solution/glom/reduction.py"
index 05fa6b8..b400ce0 100644
--- "a/tasks\\08-excision-74bf276825\\input/glom/reduction.py"
+++ "b/tasks\\08-excision-74bf276825\\solution/glom/reduction.py"
@@ -187,7 +187,80 @@ class Flatten(Fold):
 
 
 def flatten(target, **kwargs):
-    return None
+    """At its most basic, ``flatten()`` turns an iterable of iterables
+    into a single list. But it has a few arguments which give it more
+    power:
+
+    Args:
+
+       init (callable): A function or type which gives the initial
+          value of the return. The value must support addition. Common
+          values might be :class:`list` (the default), :class:`tuple`,
+          or even :class:`int`. You can also pass ``init="lazy"`` to
+          get a generator.
+       levels (int): A positive integer representing the number of
+          nested levels to flatten. Defaults to 1.
+       spec: The glomspec to fetch before flattening. This defaults to the
+          the root level of the object.
+
+    Usage is straightforward.
+
+      >>> target = [[1, 2], [3], [4]]
+      >>> flatten(target)
+      [1, 2, 3, 4]
+
+    Because integers themselves support addition, we actually have two
+    levels of flattening possible, to get back a single integer sum:
+
+      >>> flatten(target, init=int, levels=2)
+      10
+
+    However, flattening a non-iterable like an integer will raise an
+    exception:
+
+      >>> target = 10
+      >>> flatten(target)
+      Traceback (most recent call last):
+      ...
+      FoldError: can only Flatten on iterable targets, not int type (...)
+
+    By default, ``flatten()`` will add a mix of iterables together,
+    making it a more-robust alternative to the built-in
+    ``sum(list_of_lists, list())`` trick most experienced Python
+    programmers are familiar with using:
+
+      >>> list_of_iterables = [range(2), [2, 3], (4, 5)]
+      >>> sum(list_of_iterables, [])
+      Traceback (most recent call last):
+      ...
+      TypeError: can only concatenate list (not "tuple") to list
+
+    Whereas flatten() handles this just fine:
+
+      >>> flatten(list_of_iterables)
+      [0, 1, 2, 3, 4, 5]
+
+    The ``flatten()`` function is a convenient wrapper around the
+    :class:`Flatten` specifier type. For embedding in larger specs,
+    and more involved flattening, see :class:`Flatten` and its base,
+    :class:`Fold`.
+
+    """
+    subspec = kwargs.pop('spec', T)
+    init = kwargs.pop('init', list)
+    levels = kwargs.pop('levels', 1)
+    if kwargs:
+        raise TypeError('unexpected keyword args: %r' % sorted(kwargs.keys()))
+
+    if levels == 0:
+        return target
+    if levels < 0:
+        raise ValueError('expected levels >= 0, not %r' % levels)
+    spec = (subspec,)
+    spec += (Flatten(init="lazy"),) * (levels - 1)
+    spec += (Flatten(init=init),)
+
+    return glom(target, spec)
 
 
 class Merge(Fold):
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
