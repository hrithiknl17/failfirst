from diff_extraction import FileChange, filter_changes, parse_unified_diff

SAMPLE = """\
diff --git a/src/Header.tsx b/src/Header.tsx
index 1111111..2222222 100644
--- a/src/Header.tsx
+++ b/src/Header.tsx
@@ -1,3 +1,4 @@
 import x from 'y';
-const title = 'Old';
+const title = 'New';
+const sub = 'Sub';
 export default title;
diff --git a/src/New.tsx b/src/New.tsx
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/New.tsx
@@ -0,0 +1,2 @@
+export const A = 1;
+export const B = 2;
diff --git a/old.css b/old.css
deleted file mode 100644
index 4444444..0000000
--- a/old.css
+++ /dev/null
@@ -1 +0,0 @@
-body {}
diff --git a/src/a.ts b/src/b.ts
similarity index 90%
rename from src/a.ts
rename to src/b.ts
index 5555555..6666666 100644
--- a/src/a.ts
+++ b/src/b.ts
@@ -1 +1 @@
-x
+y
diff --git a/src/same.ts b/src/moved.ts
similarity index 100%
rename from src/same.ts
rename to src/moved.ts
diff --git a/media/logo.png b/media/logo.png
index 7777777..8888888 100644
Binary files a/media/logo.png and b/media/logo.png differ
diff --git a/package-lock.json b/package-lock.json
index 9999999..aaaaaaa 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1 +1 @@
-{"v": 1}
+{"v": 2}
"""


def _by_path(changes):
    return {c.path: c for c in changes}


def test_parses_every_file_with_status_and_counts():
    changes = _by_path(parse_unified_diff(SAMPLE))
    assert set(changes) == {
        "src/Header.tsx", "src/New.tsx", "old.css", "src/b.ts", "src/moved.ts",
        "media/logo.png", "package-lock.json",
    }

    header = changes["src/Header.tsx"]
    assert (header.status, header.added, header.removed) == ("modified", 2, 1)
    assert header.patch.startswith("@@ -1,3 +1,4 @@")
    assert "--- a/src/Header.tsx" not in header.patch  # file headers stripped

    assert changes["src/New.tsx"].status == "added"
    assert changes["src/New.tsx"].added == 2

    deleted = changes["old.css"]
    assert (deleted.status, deleted.removed) == ("deleted", 1)

    renamed = changes["src/b.ts"]
    assert (renamed.status, renamed.old_path) == ("renamed", "src/a.ts")

    pure_rename = changes["src/moved.ts"]
    assert (pure_rename.status, pure_rename.old_path, pure_rename.patch) == ("renamed", "src/same.ts", "")

    binary = changes["media/logo.png"]
    assert binary.binary and binary.patch == ""


def test_old_path_only_set_for_renames():
    changes = _by_path(parse_unified_diff(SAMPLE))
    assert changes["src/Header.tsx"].old_path is None
    assert changes["old.css"].old_path is None


def test_empty_diff_parses_to_nothing():
    assert parse_unified_diff("") == []


def test_noise_is_dropped_with_reason():
    kept, dropped = filter_changes(parse_unified_diff(SAMPLE))
    assert "package-lock.json" not in {c.path for c in kept}
    assert dropped == [("package-lock.json", "noise: matches **/package-lock.json")]


def test_build_output_is_noise_but_src_dist_is_not():
    files = [FileChange("dist/index.js", "modified", "@@\n+x"), FileChange("src/dist/x.ts", "modified", "@@\n+x")]
    kept, dropped = filter_changes(files)
    assert [c.path for c in kept] == ["src/dist/x.ts"]
    assert [p for p, _ in dropped] == ["dist/index.js"]


def test_per_file_truncation():
    patch = "\n".join(["@@ -1 +1 @@"] + [f"+line {i}" for i in range(50)])
    kept, _ = filter_changes([FileChange("src/big.ts", "modified", patch, added=50)], max_lines_per_file=10)
    assert kept[0].truncated
    assert len(kept[0].patch.split("\n")) == 10
    assert kept[0].added == 50  # counts describe the real change, not the trimmed patch


def test_total_budget_leaves_later_files_listed_but_empty():
    patch = "\n".join(["@@ -1 +1 @@"] + ["+x"] * 9)  # 10 lines
    files = [FileChange(f"src/f{i}.ts", "modified", patch) for i in range(3)]
    kept, _ = filter_changes(files, max_lines_per_file=100, max_total_lines=15)
    assert [c.truncated for c in kept] == [False, True, True]
    assert len(kept[1].patch.split("\n")) == 5
    assert kept[2].patch == ""
    assert len(kept) == 3  # nothing silently disappears
