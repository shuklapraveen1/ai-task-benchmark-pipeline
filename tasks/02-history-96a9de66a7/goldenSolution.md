# Golden Solution

## Provenance

Source: history-derived
Parent commit: `28138de1da9e7c29a32368c39d2c48e79bfc369a`
Fixing commit: `d1c84d2e27f2a5216564414bb7fe06417af54547`

## Reference Diff

```diff
diff --git a/docs/api.rst b/docs/api.rst
index ec713d3..5733730 100644
--- a/docs/api.rst
+++ b/docs/api.rst
@@ -1,8 +1,25 @@
-``glom`` API reference
-======================
+Core ``glom`` API
+=================
 
 .. automodule:: glom.core
 
+.. seealso::
+
+   As the glom API grows, we've refactored the docs into separate
+   domains. The core API is below. More specialized types can also be
+   found in the following docs:
+
+   .. hlist::
+      :columns: 2
+
+      * :doc:`mutation`
+      * :doc:`streaming`
+      * :doc:`grouping`
+      * :doc:`matching`
+
+   Longtime glom docs readers: thanks in advance for reporting/fixing
+   any broken links you may find.
+
 .. contents:: Contents
    :local:
 
@@ -12,7 +29,8 @@
 The ``glom`` Function
 ---------------------
 
-Where it all happens. The reason for the season. The eponymous function, ``glom``.
+Where it all happens. The reason for the season. The eponymous
+function, :func:`~glom.glom`.
 
 .. autofunction:: glom.glom
 
@@ -25,97 +43,50 @@ Basic glom specifications consist of ``dict``, ``list``, ``tuple``,
 complicated interactions, ``glom`` provides specialized specifier
 types that can be used with the basic set of Python builtins.
 
+Basic Specifiers
+^^^^^^^^^^^^^^^^
+
 .. autoclass:: glom.Path
 .. autoclass:: glom.Literal
 .. autoclass:: glom.Spec
 
-Advanced Specifiers
--------------------
-
-The specification techniques detailed above allow you to do pretty
-much everything glom is designed to do. After all, you can always
-define and insert a function or ``lambda`` into almost anywhere in the
-spec?
-
-Still, for even more specification readability and improved error
-reporting, glom has a few more tricks up its sleeve.
-
-Conditional access and defaults with Coalesce
-^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
-
-Data isn't always where or what you want it to be. Use these
-specifiers to declare away overly branchy procedural code.
-
-.. autoclass:: glom.Coalesce
-
-.. autodata:: glom.SKIP
-.. autodata:: glom.STOP
-
-Stream processing iterables with Iter
-^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
-
-*New in glom 19.10.0*
-
-.. autoclass:: glom.Iter
-
-   .. automethod:: map
-   .. automethod:: filter
-   .. automethod:: chunked
-   .. automethod:: split
-   .. automethod:: flatten
-   .. automethod:: unique
-   .. automethod:: limit
-   .. automethod:: slice
-   .. automethod:: takewhile
-   .. automethod:: dropwhile
-   .. automethod:: all
-   .. automethod:: first
+.. _advanced-specifiers:
 
+.. seealso::
 
-Combining iterables with Flatten and friends
-^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
+   Note that many of the Specifier types previously mentioned here
+   have moved into their own docs, among them:
 
-.. versionadded:: 19.1.0
+   .. hlist::
+      :columns: 2
 
-Got lists of lists? Sets of tuples? A sequence of dicts (but only want
-one)? Do you find yourself reaching for Python's builtin :func:`sum`
-and :func:`reduce`? To handle these situations and more, glom has five
-specifier types and two convenience functions:
+      * :doc:`mutation`
+      * :doc:`streaming`
+      * :doc:`grouping`
+      * :doc:`matching`
 
-.. autofunction:: glom.flatten
-
-.. autoclass:: glom.Flatten
-
-.. autofunction:: glom.merge
-
-.. autoclass:: glom.Merge
-
-.. autoclass:: glom.Sum
-
-.. autoclass:: glom.Fold
+Object-oriented access and method calls with ``T``
+^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
 
+glom's shortest-named feature may be its most powerful.
 
-Target mutation with Assign and friends
-^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
+.. autodata:: glom.T
 
-Most of glom's API design defaults to safely copying your data. But
-such caution isn't always justified.
 
-When you already have a large or complex bit of nested data that you
-are sure you want to modify in-place, glom has you covered, with the
-:func:`~glom.assign` function, and the :func:`~glom.Assign` specifier
-type.
+Defaults with Coalesce
+^^^^^^^^^^^^^^^^^^^^^^
 
-.. autofunction:: glom.assign
+Data isn't always where or what you want it to be. Use these
+specifiers to declare away overly branchy procedural code.
 
-.. autoclass:: glom.Assign
+.. autoclass:: glom.Coalesce
 
-.. autofunction:: glom.delete
+.. autodata:: glom.SKIP
+.. autodata:: glom.STOP
 
-.. autoclass:: glom.Delete
 
-Wrapping callables with Invoke
-^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
+Calling callables with Invoke
+^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
 
 .. versionadded:: 19.10.0
 
@@ -148,105 +119,16 @@ specifier type.
 .. autoclass:: glom.Call
 
 
-Object-oriented access and method calls with ``T``
-^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
-
-glom's shortest-named feature may be its most powerful.
-
-.. autodata:: glom.T
-
-Validation with Match and ``M``
-^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
-
-.. versionadded:: 20.6.0
-
-Sometimes you want to confirm that your target data matches your
-code's assumptions. With glom, you don't need a separate validation
-step, you can do these checks inline with your glom spec, using
-``~glom.Match`` and friends.
-
-.. autoclass:: glom.Match
-   :members:
-
-
-Wildcard ``dict`` and optional key matching
-~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-
-Note that our four :class:`~glom.Match` rules above imply that
-:class:`object` is a match-anything pattern.  Because
-``isinstance(val, object)`` is true for all values in Python,
-``object`` is a useful stopping case. For instance, if we wanted to
-extend an example above to allow additional keys and values in the
-user dict above we could add :class:`object` as a generic pass through::
-
-  >>> target = [{'id': 1, 'email': 'alice@example.com', 'extra': 'val'}]
-  >>> spec = Match([{'id': int, 'email': str, object: object}]))
-  >>> assert glom(target, spec) == \\
-      ... [{'id': 1, 'email': 'alice@example.com', 'extra': 'val'}]
-  True
-
-The fact that ``{object: object}`` will match any dictionary exposes
-the subtlety in :class:`~glom.Match` dictionary evaluation.
-
-By default, value match keys are required, and other keys are
-optional.  For example, ``'id'`` and ``'email'`` above are required
-because they are matched via ``==``.  If either was not present, it
-would raise class:`~glom.MatchError`.  class:`object` however is matched
-with func:`isinstance()`. Since it is not an value-match comparison,
-it is not required.
-
-This default behavior can be modified with :class:`~glom.Required`
-and :class:`~glom.Optional`.
-
-.. autoclass:: glom.Optional
-
-.. autoclass:: glom.Required
-
-``M`` Expressions
-~~~~~~~~~~~~~~~~~
-
-The most concise way to express validation and guards.
-
-.. autodata:: glom.M
-
-Boolean operators and matching
-~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-
-While ``M`` is an easy way to construct expressions, sometimes a more
-object-oriented approach can be more suitable.
-
-.. autoclass:: glom.Or
-
-.. autoclass:: glom.And
-
-.. autoclass:: glom.Not
-
-
-String matching
-~~~~~~~~~~~~~~~
-
-.. autoclass:: glom.Regex
-
-.. _check-specifier:
-
-
-Validation with Check
-~~~~~~~~~~~~~~~~~~~~~
-
-.. warning::
+Self-referential specs
+^^^^^^^^^^^^^^^^^^^^^^
 
-   Given the suite of tools introduced with :class:`~glom.Match`, the
-   :class:`Check` specifier type may be deprecated in a future
-   release.
+Sometimes nested data repeats itself, either recursive structure or
+just through redundancy.
 
-.. autoclass:: glom.Check
+.. autoclass:: glom.Ref
 
 .. _exceptions:
 
-Self-referential specs
-^^^^^^^^^^^^^^^^^^^^^^
-
-.. autoclass:: glom.Ref
 
 Exceptions
 ----------
@@ -262,17 +144,22 @@ other standard Python exceptions as appropriate.
 
 .. autoclass:: glom.CoalesceError
 
+.. autoclass:: glom.UnregisteredTarget
+
 .. autoclass:: glom.MatchError
+   :noindex:
 
 .. autoclass:: glom.TypeMatchError
+   :noindex:
 
 .. autoclass:: glom.CheckError
-
-.. autoclass:: glom.UnregisteredTarget
+   :noindex:
 
 .. autoclass:: glom.PathAssignError
+   :noindex:
 
 .. autoclass:: glom.PathDeleteError
+   :noindex:
 
 .. autoclass:: glom.GlomError
 
@@ -293,9 +180,9 @@ that's where **Inspect** comes in.
 Setup and Registration
 ----------------------
 
-For the vast majority of objects and types out there in Python-land,
-:func:`~glom.glom()` will just work. However, for that very special
-remainder, glom is ready and extensible!
+When it comes to targets, :func:`~glom.glom()` will operate on the
+vast majority of objects out there in Python-land. However, for that
+very special remainder, glom is readily extensible!
 
 .. autofunction:: glom.register
 .. autoclass:: glom.Glommer
diff --git a/docs/extensions.rst b/docs/custom_spec_types.rst
similarity index 77%
rename from docs/extensions.rst
rename to docs/custom_spec_types.rst
index f3c31cb..fad3951 100644
--- a/docs/extensions.rst
+++ b/docs/custom_spec_types.rst
@@ -1,43 +1,43 @@
-``glom`` Extensions
-===================
+Writing a custom Specifier Type
+===============================
 
 While glom comes with a lot of built-in features, no library can ever
 encompass all data manipulation operations.
 
 To cover every case out there, glom provides a way to extend its
 functionality with your own data handling hooks. This document
-explains glom's execution model and how to integrate with it using
-glom's Extension API.
+explains glom's execution model and how to integrate with it when
+writing a custom Specifier Type.
 
-When to make an extension
--------------------------
+When to write a Specifier Type
+------------------------------
 
-From day one, ``glom`` has had built-in support for arbitrary callables, like so:
+``glom`` has always supported arbitrary callables, like so:
 
 .. code::
 
    glom({'nums': range(5)}, ('nums', sum))
    # 10
 
-With this built-in extensibility, what does a glom extension add?
+With this built-in extensibility, what does a glom specifier type add?
 
-Glom extensions are useful when you want to:
+Custom specifier types are useful when you want to:
 
-  * Perform validation at spec construction time
-  * Enable users to interact with new target types and operations
-  * Improve readability and reusability of your data transformations
-  * Temporarily change the glom runtime behavior
+  1. Perform validation at spec construction time
+  2. Enable users to interact with new target types and operations
+  3. Improve readability and reusability of your data transformations
+  4. Temporarily change the glom runtime behavior
 
 If you're just building a one-off spec for transforming your own data,
 there's no reason to reach for an extension. ``glom``'s extension API
 is easy, but a good old Python ``lambda`` is even easier.
 
-Making a Specifier Type
------------------------
+Building your Specifier Type
+----------------------------
 
 Any object instance with a ``glomit`` method can participate in a glom
 call. By way of example, here is a programming clichÃ© implemented as a
-glom extension type, with comments referencing notes below.
+glom specifier type, with comments referencing notes below.
 
 .. code::
 
@@ -68,11 +68,12 @@ There are a few things to note from this example:
   3. By convention, instances are used in specs passed to
      :func:`~glom.glom` calls, not the types themselves.
 
+.. _glom_scope:
 
 The glom Scope
 --------------
 
-The glom scope exposes glom-internal state to the extension. Let's take a look inside a scope:
+The glom scope exposes runtime state to the specifier type. Let's take a look inside a scope:
 
 .. code::
 
@@ -108,7 +109,7 @@ As you can see, all glom's core workings are present, all under familiar keys:
 To learn how to use the scope's powerful features idiomatically, let's
 reimplement at one of glom's standard specifier types.
 
-Extensions by example
+Specifiers by example
 ---------------------
 
 While we've technically created a couple of extensions above, let's
@@ -119,7 +120,7 @@ it works like this:
 
 .. code::
 
-   from glom import glom
+   from glom import glom, Sum
 
    glom([1, 2, 3], Sum())
    # 6
@@ -168,7 +169,7 @@ contains comments with references to explanatory notes below.
 
 Now, let's take a look at the interesting parts, referencing the comments above:
 
-  1. Extensions often reference the TargetRegistry, which is not part
+  1. Specifier types often reference the TargetRegistry, which is not part
      of the top-level ``glom`` API, and must be imported from
      ``glom.core``. More on this in #4.
   2. Specifier type ``__init__`` methods may take as many or as few
@@ -177,7 +178,7 @@ Now, let's take a look at the interesting parts, referencing the comments above:
      actual specifier's operation. This helps readability of
      glomspecs. See :class:`~glom.Coalesce` for an example of this
      idiom.
-  3. Extension specifiers should not reference the
+  3. Specifier types should not reference the
      :func:`~glom.glom()` function directly, instead use the
      :func:`~glom.glom` function as a key to the ``scope`` map to get the
      currently active ``glom()``. This ensures that the extension type is
@@ -185,32 +186,31 @@ Now, let's take a look at the interesting parts, referencing the comments above:
      ``glom()`` function.
   4. To maximize compatiblity with new target types, ``glom`` allows
      :ref:`new types and operations to be registered
-     <setup-and-registration>` with the ``TargetRegistry``. Extensions
+     <setup-and-registration>` with the ``TargetRegistry``. Specifier types
      should respect this by contextually fetching these standard
      operators as demonstrated above. At the time of writing, three
      primary operators are used by glom itself, ``"get"``,
      ``"iterate"``, and ``"assign"``.
   5. In the event that the current target does not support your
-     extension's desired operation, it's customary to raise a helpful
+     Specifier type's desired operation, it's customary to raise a helpful
      error. Consider creating your own exception type and inheriting
      from :class:`~glom.GlomError`.
-  6. Extension types may have other methods and members in addition to
+  6. Specifier types may have other methods and members in addition to
      the primary ``glomit()`` method. This ``_sum()`` method
-     implements most of the core of our custom extension.
+     implements most of the core of our custom specifier type.
 
 Check out the implementation of the real :class:`glom.Sum()` specifier for more details.
 
 Summing up
 ----------
 
-``glom`` extensions are more than just add-ons; the extension
+``glom`` Specifier Types are more than just add-ons; the extension
 architecture is how most of ``glom`` itself is implemented. Build
-knowing that the paradigm is powerful enough to achieve your data
-transformation requirements.
+knowing that the paradigm is as powerful as anything built-in.
 
-If you need more examples, a simple one can be found in :ref:`this snippet
-<lisp-style-if>`, and ``glom`` itself contains many specifiers more
-advanced than the above. Simply search the codebase for ``glomit()``
-methods and you will find no shortage.
+If you need more examples, another simple one can be found in
+:ref:`this snippet <lisp-style-if>`. ``glom``'s source code itself
+contains many specifiers more advanced than the above. Simply search
+the codebase for ``glomit()`` methods and you will find no shortage.
 
 Happy extending!
diff --git a/docs/grouping.rst b/docs/grouping.rst
new file mode 100644
index 0000000..a61d602
--- /dev/null
+++ b/docs/grouping.rst
@@ -0,0 +1,28 @@
+Reduction & Grouping
+====================
+
+This document contains glom techniques for transforming a collection
+of data to a smaller set, otherwise known as "grouping" or
+"reduction".
+
+Combining iterables with Flatten and Merge
+^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
+
+.. versionadded:: 19.1.0
+
+Got lists of lists? Sets of tuples? A sequence of dicts (but only want
+one)? Do you find yourself reaching for Python's builtin :func:`sum`
+and :func:`reduce`? To handle these situations and more, glom has five
+specifier types and two convenience functions:
+
+.. autofunction:: glom.flatten
+
+.. autoclass:: glom.Flatten
+
+.. autofunction:: glom.merge
+
+.. autoclass:: glom.Merge
+
+.. autoclass:: glom.Sum
+
+.. autoclass:: glom.Fold
diff --git a/docs/index.rst b/docs/index.rst
index a40ed20..0e02d20 100644
--- a/docs/index.rst
+++ b/docs/index.rst
@@ -51,12 +51,28 @@ There's much, much more to glom, check out the :doc:`tutorial` and :doc:`API ref
 
 
 .. toctree::
-   :maxdepth: 2
+   :maxdepth: 1
+   :caption: Learning glom
 
    tutorial
-   api
-   cli
    faq
    by_analogy
    snippets
-   extensions
+   cli
+
+.. toctree::
+   :maxdepth: 2
+   :caption: API Reference
+
+   api
+   mutation
+   streaming
+   grouping
+   matching
+
+.. toctree::
+   :maxdepth: 1
+   :caption: Extending glom
+
+   custom_spec_types
+   modes
diff --git a/docs/matching.rst b/docs/matching.rst
new file mode 100644
index 0000000..69682c5
--- /dev/null
+++ b/docs/matching.rst
@@ -0,0 +1,93 @@
+Matching & Validation
+=====================
+
+.. automodule:: glom.matching
+
+.. contents:: Contents
+   :local:
+
+Validation with Match
+~~~~~~~~~~~~~~~~~~~~~
+
+For matching whole data structures, use a :class:`~glom.Match` spec.
+
+.. autoclass:: glom.Match
+   :members:
+
+Optional and required ``dict`` key matching
+~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
+
+Note that our four :class:`~glom.Match` rules above imply that
+:class:`object` is a match-anything pattern.  Because
+``isinstance(val, object)`` is true for all values in Python,
+``object`` is a useful stopping case. For instance, if we wanted to
+extend an example above to allow additional keys and values in the
+user dict above we could add :class:`object` as a generic pass through::
+
+  >>> target = [{'id': 1, 'email': 'alice@example.com', 'extra': 'val'}]
+  >>> spec = Match([{'id': int, 'email': str, object: object}]))
+  >>> assert glom(target, spec) == \\
+      ... [{'id': 1, 'email': 'alice@example.com', 'extra': 'val'}]
+  True
+
+The fact that ``{object: object}`` will match any dictionary exposes
+the subtlety in :class:`~glom.Match` dictionary evaluation.
+
+By default, value match keys are required, and other keys are
+optional.  For example, ``'id'`` and ``'email'`` above are required
+because they are matched via ``==``.  If either was not present, it
+would raise class:`~glom.MatchError`.  class:`object` however is matched
+with func:`isinstance()`. Since it is not an value-match comparison,
+it is not required.
+
+This default behavior can be modified with :class:`~glom.Required`
+and :class:`~glom.Optional`.
+
+.. autoclass:: glom.Optional
+
+.. autoclass:: glom.Required
+
+``M`` Expressions
+~~~~~~~~~~~~~~~~~
+
+The most concise way to express validation and guards.
+
+.. autodata:: glom.M
+
+Boolean operators and matching
+~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
+
+While ``M`` is an easy way to construct expressions, sometimes a more
+object-oriented approach can be more suitable.
+
+.. autoclass:: glom.Or
+
+.. autoclass:: glom.And
+
+.. autoclass:: glom.Not
+
+
+String matching
+~~~~~~~~~~~~~~~
+
+.. autoclass:: glom.Regex
+
+Exceptions
+~~~~~~~~~~
+
+.. autoclass:: glom.MatchError
+
+.. autoclass:: glom.TypeMatchError
+
+Validation with Check
+~~~~~~~~~~~~~~~~~~~~~
+
+.. warning::
+
+   Given the suite of tools introduced with :class:`~glom.Match`, the
+   :class:`Check` specifier type may be deprecated in a future
+   release.
+
+.. autoclass:: glom.Check
+
+.. autoclass:: glom.CheckError
diff --git a/docs/modes.rst b/docs/modes.rst
index 1e3c3c2..86e24e7 100644
--- a/docs/modes.rst
+++ b/docs/modes.rst
@@ -1,28 +1,47 @@
 ``glom`` Modes
 ==============
 
-A mode determines how python built-in
-data structures are evaluated.  A mode is used
-similar to a spec: whatever python data structure
-is passed to the mode class init will be evaluated
-under that mode.
+.. note::
 
-Modes do not change the behavior of `T`, or spec classes;
-they only modify `dict`, `tuple`, `list`, etc.
+   Be sure to read ":doc:`custom_spec_types`" before diving into the
+   deep details below.
 
-Once set, the mode remains in place until it is
-overridden by another mode.
+A glom "mode" determines how Python built-in data structures are
+evaluated. Think of it like a dialect for how :class:`dict`,
+:class:`tuple`, :class:`list`, etc., are interpreted in a spec. Modes
+do not change the behavior of `T`, or many other core
+specifiers. Modes are one of the keys to keeping glom specs short and
+readable.
 
-The default behavior of glom is the :class:`~glom.Auto`
-mode.  The next most common mode is :class:`~glom.Fill`.
+A mode is used similar to a spec: whatever Python data structure is
+passed to the mode type constructor will be evaluated under that
+mode. Once set, the mode remains in place until it is overridden by
+another mode.
 
-custom modes
-------------
+glom only has a few modes:
 
-A mode is a spec which sets `scope[MODE]` to a function
-which accepts target, spec, and scope and returns a result.
+  1. :class:`~glom.Auto` - The default glom behavior, used for data
+     transformation, with the spec acting as a template.
+  2. :class:`~glom.Fill` - A variant of the default transformation
+     behavior; preferring to "fill" containers instead of
+     iterating, chaining, etc.
+  3. :class:`~glom.Match` - Treats the spec as a pattern, checking
+     that the target matches.
 
-For example, here is an abbreviated version of :class:`~glom.Fill`
+Adding a new mode is relatively rare, but when it comes up this
+document includes relevant details.
+
+
+Writing custom Modes
+--------------------
+
+A mode is a spec which sets ``scope[MODE]`` to a function which
+accepts ``target``, ``spec``, and ``scope`` and returns a result, a
+signature very similar to the top-level :func:`~glom.glom` method
+itself.
+
+For example, here is an abbreviated version of the :class:`~glom.Fill`
+mode:
 
 
 .. code-block:: python
@@ -49,4 +68,11 @@ For example, here is an abbreviated version of :class:`~glom.Fill`
              return spec(target)
         return spec
 
+Like any other :doc:`Specifier Type <custom_spec_types>`, ``Fill`` has
+a ``glomit()`` method, and this method sets the ``MODE`` key in the
+:ref:`glom scope <glom_scope>` to our ``_fill`` function. The name
+itself doesn't matter, but the signature must match exactly:
+``(target, spec, scope)``.
 
+As mentioned above, custom modes are relatively rare for glom. If you
+write one, `let us know <https://github.com/mahmoud/glom/issues>`_!
diff --git a/docs/mutation.rst b/docs/mutation.rst
new file mode 100644
index 0000000..580980a
--- /dev/null
+++ b/docs/mutation.rst
@@ -0,0 +1,33 @@
+Assignment & Mutation
+=====================
+
+.. automodule:: glom.mutation
+
+.. contents:: Contents
+   :local:
+
+Assignment
+----------
+
+Deeply assign within an existing structure, given a path and a value.
+
+.. autofunction:: glom.assign
+
+.. autoclass:: glom.Assign
+
+Deletion
+--------
+
+Delete attributes from objects and keys from containers.
+
+.. autofunction:: glom.delete
+
+.. autoclass:: glom.Delete
+
+
+Exceptions
+----------
+
+.. autoclass:: glom.PathAssignError
+
+.. autoclass:: glom.PathDeleteError
diff --git a/docs/snippets.rst b/docs/snippets.rst
index 8974584..2db872b 100644
--- a/docs/snippets.rst
+++ b/docs/snippets.rst
@@ -1,5 +1,5 @@
-Snippets
-========
+Examples & Snippets
+===================
 
 glom can do a lot of things, in the right hands. This doc makes those
 hands yours, through sample code of useful building blocks and common
diff --git a/docs/streaming.rst b/docs/streaming.rst
new file mode 100644
index 0000000..a608117
--- /dev/null
+++ b/docs/streaming.rst
@@ -0,0 +1,24 @@
+Streaming & Iteration
+=====================
+
+.. versionadded:: 19.10.0
+
+.. automodule:: glom.streaming
+
+.. contents:: Contents
+   :local:
+
+.. autoclass:: glom.Iter
+
+   .. automethod:: map
+   .. automethod:: filter
+   .. automethod:: chunked
+   .. automethod:: split
+   .. automethod:: flatten
+   .. automethod:: unique
+   .. automethod:: limit
+   .. automethod:: slice
+   .. automethod:: takewhile
+   .. automethod:: dropwhile
+   .. automethod:: all
+   .. automethod:: first
diff --git a/glom/core.py b/glom/core.py
index b5a0442..55b5904 100644
--- a/glom/core.py
+++ b/glom/core.py
@@ -1,11 +1,8 @@
 """*glom gets results.*
 
-If there was ever a Python example of "big things come in small
-packages", ``glom`` might be it.
-
 The ``glom`` package has one central entrypoint,
 :func:`glom.glom`. Everything else in the package revolves around that
-one function.
+one function. Sometimes, big things come in small packages.
 
 A couple of conventional terms you'll see repeated many times below:
 
@@ -148,8 +145,8 @@ class GlomError(Exception):
             return self._finalized_str
         elif getattr(self, '_scope', None) is not None:
             self._target_spec_trace = format_target_spec_trace(self._scope)
-            parts = ["error raised while processing.",
-                     " Target-spec trace, with error detail (most recent last):",
+            parts = ["error raised while processing, details below.",
+                     " Target-spec trace (most recent last):",
                      self._target_spec_trace]
             parts.extend(self._tb_lines)
             self._finalized_str = "\n".join(parts)
@@ -1873,13 +1870,12 @@ def register_op(op_name, **kwargs):
 
 
 class Glommer(object):
-    """All the wholesome goodness that it takes to make glom work. This
-    type mostly serves to encapsulate the type registration context so
-    that advanced uses of glom don't need to worry about stepping on
-    each other's toes.
+    """The :class:`Glommer` type mostly serves to encapsulate type
+    registration context so that advanced uses of glom don't need to
+    worry about stepping on each other.
 
     Glommer objects are lightweight and, once instantiated, provide
-    the :func:`glom()` method we know and love:
+    a :func:`glom()` method:
 
     >>> glommer = Glommer()
     >>> glommer.glom({}, 'a.b.c', default='d')
@@ -1896,6 +1892,7 @@ class Glommer(object):
           default actions include dict access, list and iterable
           iteration, and generic object attribute access. Defaults to
           True.
+
     """
     def __init__(self, **kwargs):
         register_default_types = kwargs.pop('register_default_types', True)
diff --git a/glom/matching.py b/glom/matching.py
index dd8e8b3..42be7d8 100644
--- a/glom/matching.py
+++ b/glom/matching.py
@@ -1,5 +1,10 @@
 """
-Contains the code for match-mode, and match-mode adjacent helper Specs
+.. versionadded:: 20.7.0
+
+Sometimes you want to confirm that your target data matches your
+code's assumptions. With glom, you don't need a separate validation
+step, you can do these checks inline with your glom spec, using
+:class:`~glom.Match` and friends.
 """
 
 import re
@@ -566,16 +571,22 @@ M = _MType()
 
 
 class Optional(object):
-    """
-    Used as a `dict` key in `Match()` mode,
-    marks that a value match key which would otherwise
-    be required is optional and should not raise
-    `MatchError` even if no keys match.
+    """Used as a :class:`dict` key in a :class:`~glom.Match()` spec,
+    marks that a value match key which would otherwise be required is
+    optional and should not raise :exc:`~glom.MatchError` even if no
+    keys match.
+
+    For example::
+
+      >>> spec = Match({Optional("name"): str})
+      >>> glom({"name": "alice"}, spec)
+      {'name': 'alice'}
+      >>> glom({}, spec)
+      {}
+      >>> spec = Match({Optional("name", default=""): str})
+      >>> glom({}, spec)
+      {'name': ''}
 
-    For example, `{Optional("name", default=""): str}`
-    would match `{"name": "alice"}` and also `{}`.
-
-    (In the case of `{}`, the result would be `{"name": ""}`)
     """
     __slots__ = ('key', 'default')
 
@@ -590,25 +601,46 @@ class Optional(object):
     def glomit(self, target, scope):
         if target != self.key:
             raise MatchError("target {} != spec {}", target, self.key)
+        return target
 
     def __repr__(self):
         return '%s(%s)' % (self.__class__.__name__, bbrepr(self.key))
 
 
 class Required(object):
-    """
-    Used as a `dict` key in `Match()` mode,
-    marks that a non value match key which would otherwise
-    not be required should raise `MatchError` if at least
-    one key in the target does not match.
-
-    For example, `{object: object}` will match any
-    `dict`, including `{}`.  Because `object` is a type,
-    it is not an error by default if no keys match.
-
-    `{Required(object): object}` will not match `{}`,
-    because the `Required()` means `MatchError` will
-    be raised if there isn't at least one key.
+    """Used as a :class:`dict` key in :class:`~glom.Match()` mode, marks
+    that a key which might otherwise not be required should raise
+    :exc:`~glom.MatchError` if the key in the target does not match.
+
+    For example::
+
+      >>> spec = Match({object: object})
+
+    This spec will match any dict, because :class:`object` is the base
+    type of every object::
+
+      >>> glom({}, spec)
+      {}
+
+    ``{}`` will also match because match mode does not require at
+    least one match by default. If we want to require that a key
+    matches, we can use :class:`~glom.Required`::
+
+      >>> spec = Match({Required(object): object})
+      >>> glom({}, spec)
+      Traceback (most recent call last):
+      ...
+      MatchError: error raised while processing.
+       Target-spec trace, with error detail (most recent last):
+       - Target: {}
+       - Spec: Match({Required(object): <type 'object'>})
+       - Spec: {Required(object): <type 'object'>}
+      MatchError: target missing expected keys Required(object)
+
+    Now our spec requires at least one key of any type. You can refine
+    the spec by putting more specific subpatterns inside of
+    :class:`~glom.Required`.
+
     """
     __slots__ = ('key',)
 
@@ -674,7 +706,7 @@ def _handle_dict(target, spec, scope):
         else:
             raise MatchError("key {!r} didn't match any of {!r}", key, spec_keys)
     if required:
-        raise MatchError("missing keys {} from target {}", required, target)
+        raise MatchError("target missing expected keys: {}", ', '.join([bbrepr(r) for r in required]))
     return result
 
 
diff --git a/glom/mutation.py b/glom/mutation.py
index 87e8fdd..231a9bb 100644
--- a/glom/mutation.py
+++ b/glom/mutation.py
@@ -1,5 +1,11 @@
-"""
-This module contains Specs that perform mutations.
+"""By default, glom aims to safely return a transformed copy of your
+data. But sometimes you really need to transform an existing object.
+
+When you already have a large or complex bit of nested data that you
+are sure you want to modify in-place, glom has you covered, with the
+:func:`~glom.assign` function, and the :func:`~glom.Assign` specifier
+type.
+
 """
 import operator
 from pprint import pprint
diff --git a/glom/streaming.py b/glom/streaming.py
index 6c4c165..9b83abf 100644
--- a/glom/streaming.py
+++ b/glom/streaming.py
@@ -1,8 +1,12 @@
-"""
-Helpers for streaming use cases -- that is, specifier types which yield their
-results incrementally so that they can be applied to targets which
-are themselves streaming (e.g. chunks of rows from a database, lines
-from a file) without excessive memory usage.
+"""glom's helpers for streaming use cases.
+
+Specifier types which yield their results incrementally so that they
+can be applied to targets which are themselves streaming (e.g. chunks
+of rows from a database, lines from a file) without excessive memory
+usage.
+
+glom's streaming functionality revolves around a single :class:`Iter`
+Specifier type, which has methods to transform the target stream.
 """
 
 from itertools import islice, dropwhile, takewhile, chain
@@ -21,10 +25,10 @@ from .core import glom, T, STOP, SKIP, _MISSING, Path, TargetRegistry, Call, Spe
 from .matching import Check
 
 class Iter(object):
-    """``Iter()`` is glom's counterpart to the built-in :func:`iter()`
+    """``Iter()`` is glom's counterpart to Python's built-in :func:`iter()`
     function. Given an iterable target, ``Iter()`` yields the result
     of applying the passed spec to each element of the target, similar
-    to the built-in `[]` spec, but streaming.
+    to the built-in ``[]`` spec, but streaming.
 
     The following turns a list of strings into integers using Iter(),
     before deduplicating and converting it to a tuple:
diff --git a/glom/test/test_error.py b/glom/test/test_error.py
index 60e03fd..3365498 100644
--- a/glom/test/test_error.py
+++ b/glom/test/test_error.py
@@ -130,8 +130,8 @@ Traceback (most recent call last):
     glom(target, spec)
   File "core.py", line ___, in glom
     raise err
-glom.core.GlomError.wrap(Exception): error raised while processing.
- Target-spec trace, with error detail (most recent last):
+glom.core.GlomError.wrap(Exception): error raised while processing, details below.
+ Target-spec trace (most recent last):
  - Target: [None]
  - Spec: {'results': [{'value': <function _raise_exc at
  - Spec: [{'value': <function _raise_exc at
@@ -155,8 +155,8 @@ Traceback (most recent call last):
     glom(target, spec)
   File "core.py", line ___, in glom
     raise err
-glom.core.PathAccessError: error raised while processing.
- Target-spec trace, with error detail (most recent last):
+glom.core.PathAccessError: error raised while processing, details below.
+ Target-spec trace (most recent last):
  - Target: [None]
  - Spec: {'results': [{'valuÃ©': 'value'}]}
  - Spec: [{'valuÃ©': 'value'}]
@@ -195,16 +195,16 @@ Traceback (most recent call last):
     glom(target, spec)
   File "core.py", line ___, in glom
     raise err
-glom.core.PathAccessError: error raised while processing.
- Target-spec trace, with error detail (most recent last):
+glom.core.PathAccessError: error raised while processing, details below.
+ Target-spec trace (most recent last):
  - Target: [None]
  - Spec: {'results': [{'value': <function _subglom_wrap at
  - Spec: [{'value': <function _subglom_wrap at
  - Target: None
  - Spec: {'value': <function _subglom_wrap at
  - Spec: <function _subglom_wrap at
-glom.core.PathAccessError: error raised while processing.
- Target-spec trace, with error detail (most recent last):
+glom.core.PathAccessError: error raised while processing, details below.
+ Target-spec trace (most recent last):
  - Target: ['Nested']
  - Spec: {'internal': ['val']}
  - Spec: ['val']
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
