import requests

OLLAMA_API = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2:1b"


def summarize_diff(diff_result: dict, timeout=30):
    """
    Generates a high-level, human-readable summary of document changes.
    Uses LLM ONLY for summarization (not detection).
    Safe to fail (returns None if LLM unavailable).
    """
    print("[LLM] Preparing diff summary request...")
    print(f"[LLM] Changes - Added: {len(diff_result.get('added', []))}, "
          f"Removed: {len(diff_result.get('removed', []))}, "
          f"Modified: {len(diff_result.get('modified', []))}")

    # Format changes for display
    added = diff_result.get("added", [])
    modified = diff_result.get("modified", [])
    removed = diff_result.get("removed", [])
    
    # Build detailed change list
    change_summary = []
    
    if added:
        change_summary.append("=" * 60)
        change_summary.append("ADDED CONTENT:")
        change_summary.append("=" * 60)
        for i, item in enumerate(added[:20], 1):  # Limit to first 20
            change_summary.append(f"{i}. {item}")
        if len(added) > 20:
            change_summary.append(f"... and {len(added) - 20} more additions")
        change_summary.append("")
    
    if modified:
        change_summary.append("=" * 60)
        change_summary.append("MODIFIED CONTENT:")
        change_summary.append("=" * 60)
        for i, item in enumerate(modified[:20], 1):  # Limit to first 20
            change_summary.append(f"{i}. {item}")
        if len(modified) > 20:
            change_summary.append(f"... and {len(modified) - 20} more modifications")
        change_summary.append("")
    
    if removed:
        change_summary.append("=" * 60)
        change_summary.append("REMOVED CONTENT:")
        change_summary.append("=" * 60)
        for i, item in enumerate(removed[:20], 1):  # Limit to first 20
            change_summary.append(f"{i}. {item}")
        if len(removed) > 20:
            change_summary.append(f"... and {len(removed) - 20} more removals")
        change_summary.append("")
    
    if not added and not modified and not removed:
        change_summary.append("No changes detected between documents.")
    
    # Add summary statistics
    change_summary.append("=" * 60)
    change_summary.append("SUMMARY STATISTICS:")
    change_summary.append("=" * 60)
    change_summary.append(f"Total Added: {len(added)}")
    change_summary.append(f"Total Modified: {len(modified)}")
    change_summary.append(f"Total Removed: {len(removed)}")
    change_summary.append(f"Total Changes: {len(added) + len(modified) + len(removed)}")
    
    print(f"[LLM] ✓ Formatted summary with {len(added) + len(modified) + len(removed)} total changes")
    return "\n".join(change_summary)
