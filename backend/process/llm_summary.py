def summarize_diff(diff_result: dict, timeout=30):
    """
    Generates a high-level, human-readable summary of document changes.
    Uses LLM ONLY for summarization (not detection).
    Safe to fail (returns None if LLM unavailable).
    """
    print("[LLM] Preparing diff summary request...")

    # Get stats from new format
    stats = diff_result.get("stats", {})
    lines = diff_result.get("lines", [])
    total_lines = diff_result.get("total_lines", len(lines))

    added_count = stats.get("added", 0)
    modified_count = stats.get("modified", 0)
    removed_count = stats.get("removed", 0)
    equal_count = stats.get("equal", 0)

    print(f"[LLM] Changes - Added: {added_count}, "
          f"Removed: {removed_count}, "
          f"Modified: {modified_count}, "
          f"Unchanged: {equal_count}")

    # Filter lines by status
    added_lines = [l for l in lines if l.get("status") == "added"]
    modified_lines = [l for l in lines if l.get("status") == "modified"]
    removed_lines = [l for l in lines if l.get("status") == "removed"]

    # Build detailed change list
    change_summary = []

    if added_lines:
        change_summary.append("=" * 60)
        change_summary.append("ADDED CONTENT:")
        change_summary.append("=" * 60)
        for i, item in enumerate(added_lines[:20], 1):  # Limit to first 20
            line_num = item.get("line", "?")
            text = item.get("text", item.get("new_text", ""))
            change_summary.append(f"Line {line_num}: {text}")
        if len(added_lines) > 20:
            change_summary.append(f"... and {len(added_lines) - 20} more additions")
        change_summary.append("")

    if modified_lines:
        change_summary.append("=" * 60)
        change_summary.append("MODIFIED CONTENT:")
        change_summary.append("=" * 60)
        for i, item in enumerate(modified_lines[:20], 1):  # Limit to first 20
            line_num = item.get("line", "?")
            old_text = item.get("old_text", "")
            new_text = item.get("new_text", "")
            change_summary.append(f"Line {line_num}: '{old_text}' → '{new_text}'")
        if len(modified_lines) > 20:
            change_summary.append(f"... and {len(modified_lines) - 20} more modifications")
        change_summary.append("")

    if removed_lines:
        change_summary.append("=" * 60)
        change_summary.append("REMOVED CONTENT:")
        change_summary.append("=" * 60)
        for i, item in enumerate(removed_lines[:20], 1):  # Limit to first 20
            line_num = item.get("line", "?")
            text = item.get("text", item.get("old_text", ""))
            change_summary.append(f"Line {line_num}: {text}")
        if len(removed_lines) > 20:
            change_summary.append(f"... and {len(removed_lines) - 20} more removals")
        change_summary.append("")

    if not added_lines and not modified_lines and not removed_lines:
        change_summary.append("No changes detected between documents.")

    # Add summary statistics
    change_summary.append("=" * 60)
    change_summary.append("SUMMARY STATISTICS:")
    change_summary.append("=" * 60)
    change_summary.append(f"Total Lines: {total_lines}")
    change_summary.append(f"Unchanged: {equal_count}")
    change_summary.append(f"Added: {added_count}")
    change_summary.append(f"Modified: {modified_count}")
    change_summary.append(f"Removed: {removed_count}")
    change_summary.append(f"Total Changes: {added_count + modified_count + removed_count}")

    total_changes = added_count + modified_count + removed_count
    print(f"[LLM] ✓ Formatted summary with {total_changes} total changes")
    return "\n".join(change_summary)
