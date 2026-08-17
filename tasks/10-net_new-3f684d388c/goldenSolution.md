# Golden Solution

## Provenance

Source: net-new feature
Target module: `glom.matching`
Target: `3f684d388ceb65e4`

## Reference Diff

```diff
diff --git "a/tasks\\10-net_new-3f684d388c\\input/glom/matching.py" "b/tasks\\10-net_new-3f684d388c\\solution/glom/matching.py"
index 74a6278..c86a7bb 100644
--- "a/tasks\\10-net_new-3f684d388c\\input/glom/matching.py"
+++ "b/tasks\\10-net_new-3f684d388c\\solution/glom/matching.py"
@@ -1054,4 +1054,4 @@ class CheckError(GlomError):
         return f'{cn}({self.msgs!r}, {self.check_obj!r}, {self.path!r})'
 
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
