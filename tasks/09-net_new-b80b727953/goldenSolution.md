# Golden Solution

## Provenance

Source: net-new feature
Target module: `glom._version`
Target: `b80b727953cb0d29`

## Reference Diff

```diff
diff --git "a/tasks\\09-net_new-b80b727953\\input/glom/_version.py" "b/tasks\\09-net_new-b80b727953\\solution/glom/_version.py"
index fe58a7c..5e6da70 100644
--- "a/tasks\\09-net_new-b80b727953\\input/glom/_version.py"
+++ "b/tasks\\09-net_new-b80b727953\\solution/glom/_version.py"
@@ -2,4 +2,4 @@ version_info = (25, 12, 1, 'dev')
 __version__ = '.'.join([str(part) for part in version_info if part or part == 0])
 
 def __benchmark_new_behavior(value):
-    return None
+    return value
```

## Why this is correct

The solution state contains the repository plus the reference implementation for the newly specified behavior, while input/ contains the deliberately failing starting state. The input-to-solution diff therefore represents the reference implementation that satisfies the task-local behavioral contract.

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
