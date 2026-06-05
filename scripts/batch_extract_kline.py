#!/usr/bin/env python3
"""
Batch write article markdown files for K線力量判斷入門.
Takes a list of articles as JSON from stdin.
Input JSON: [{article_id, order, category, title, content, captured_at}, ...]
"""
import sys
import os
import json
import re
from datetime import datetime, timezone

def sanitize_filename(title):
    """Remove unsafe characters for filenames."""
    # Keep CJK, alphanumeric, parens, hyphens
    result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)
    result = result.strip()
    result = re.sub(r'\s+', '', result)
    return result[:80]

base_dir = '/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/docs/K線力量判斷入門/articles'
os.makedirs(base_dir, exist_ok=True)

articles = json.load(sys.stdin)
results = []

for data in articles:
    article_id = data['article_id']
    order = data['order']
    category = data['category']
    title = data['title']
    content = data['content']
    captured_at = data.get('captured_at', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'))

    if not content or len(content) < 50:
        results.append({"status": "error", "article_id": article_id, "order": order, "reason": "empty_content"})
        continue

    safe_title = sanitize_filename(title)
    filename = f"{article_id}_{order:02d}-{safe_title}.md"
    filepath = os.path.join(base_dir, filename)

    url = f"https://www.pressplay.cc/project/55DE90EBFBB634BE864F75703AB654DE/articles/{article_id}"

    frontmatter = f'---\ntitle: "{title}"\narticle_id: "{article_id}"\nsource_url: "{url}"\ncaptured_at: "{captured_at}"\ncourse: "K線力量判斷入門"\norder: {order}\ncategory: "{category}"\n---\n\n# {title}\n\n'

    full_content = frontmatter + content

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(full_content)

    results.append({"status": "ok", "filepath": filepath, "content_len": len(content), "filename": filename, "order": order})

print(json.dumps(results, ensure_ascii=False))
