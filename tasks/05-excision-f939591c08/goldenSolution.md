# Golden Solution

## Provenance

Source: excision (red → green)
Target module: `glom.cli`
Target: `function:glom.cli.main`

## Reference Diff

```diff
diff --git "a/tasks\\05-excision-f939591c08\\input/glom/cli.py" "b/tasks\\05-excision-f939591c08\\solution/glom/cli.py"
index 295b04d..2987064 100644
--- "a/tasks\\05-excision-f939591c08\\input/glom/cli.py"
+++ "b/tasks\\05-excision-f939591c08\\solution/glom/cli.py"
@@ -99,7 +99,8 @@ def get_command():
 
 
 def main(argv):
-    return None
+    cmd = get_command()
+    return cmd.run(argv) or 0
 
 
 def console_main():
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
