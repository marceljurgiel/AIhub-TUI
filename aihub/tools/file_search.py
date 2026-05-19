"""
AIHub Tool: Local file search (v0.1.0).
Searches for files by glob pattern and optionally greps inside them for content.
"""
import glob
import os


def search_files(root: str, pattern: str, content_query: str = "") -> str:
    """
    Search for files matching a glob pattern under a root directory,
    optionally grep-filtering by content substring.

    Args:
        root:          Root directory to search recursively.
        pattern:       Glob filename pattern (e.g. '*.py', '*.md').
        content_query: Optional substring to find inside matched files.
                       If empty, all matched files are returned.

    Returns:
        Formatted string listing matching files and (if content_query is set)
        the matching lines with line numbers.
    """
    root = os.path.expanduser(root)

    if not os.path.exists(root):
        return f"[Search Error] Directory not found: {root}"

    # Recursive glob search
    search_pattern = os.path.join(root, "**", pattern)
    try:
        all_matches = sorted(glob.glob(search_pattern, recursive=True))
    except Exception as e:
        return f"[Search Error] Glob failed: {e}"

    # Also check non-recursive (direct children)
    direct_pattern = os.path.join(root, pattern)
    direct_matches = sorted(glob.glob(direct_pattern))
    all_matches = sorted(set(all_matches + direct_matches))

    # Filter to files only
    file_matches = [p for p in all_matches if os.path.isfile(p)]

    if not file_matches:
        return f"[Search] No files matching '{pattern}' found under: {root}"

    # If no content query, just return the file list
    if not content_query:
        lines = [f"🗂 Files matching '{pattern}' under {root}:\n"]
        for p in file_matches[:50]:  # cap at 50 results
            size = os.path.getsize(p)
            lines.append(f"  📄 {p}  ({size} bytes)")
        if len(file_matches) > 50:
            lines.append(f"  ... and {len(file_matches) - 50} more")
        return "\n".join(lines)

    # Grep mode: search inside each file for content_query
    grep_results = []
    for filepath in file_matches[:100]:  # cap at 100 files to grep
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                file_lines = f.readlines()
        except Exception:
            continue

        for lineno, line in enumerate(file_lines, 1):
            if content_query.lower() in line.lower():
                grep_results.append({
                    "file":    filepath,
                    "lineno":  lineno,
                    "content": line.rstrip(),
                })

    if not grep_results:
        return (
            f"[Search] '{content_query}' not found in any '{pattern}' files under: {root}"
        )

    # Format results, grouping by file
    current_file = None
    output_lines = [f"🔎 Grep '{content_query}' in '{pattern}' files under {root}:\n"]
    for r in grep_results[:200]:  # cap at 200 matches total
        if r["file"] != current_file:
            current_file = r["file"]
            output_lines.append(f"\n  📄 {current_file}")
        output_lines.append(f"    L{r['lineno']:>4}: {r['content']}")

    if len(grep_results) > 200:
        output_lines.append(f"\n  ... and {len(grep_results) - 200} more matches")

    return "\n".join(output_lines)
